#!/usr/bin/env python3
"""Language-rerank unresolved GGA 8x16 Viterbi candidates.

This analyzer addresses the main failure mode of monotone Shift-JIS recovery:
the 8x16 atlas contains duplicate/out-of-order characters.  A structurally
plausible Viterbi choice can therefore be linguistically impossible, e.g.
護力増大 instead of 戦力増大 or 散伏する instead of 散開する.

Evidence channels:
* same-ROM Japanese bigram/trigram/4-gram counts from already decoded corpora;
* Janome Viterbi morphological path cost;
* the existing Shift-JIS/font Viterbi proposal as a weak structural prior.

Calibration is leave-one-out over verified 8x16 slots.  A verified slot is
hidden in trusted production/UI rows that otherwise decode completely.  The
language model must recover the verified character from the same candidate
pool used for real unresolved rows.  This tool is read-only.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from janome.tokenizer import Tokenizer

import analyze_ggen_advance_8x16_sjis_viterbi as sjisv
import analyze_ggen_advance_8x16_ordered_block_candidates as fontmod

ROOT = Path(__file__).resolve().parent.parent
MAP8_DEFAULT = ROOT / "analysis" / "ggen_advance_8x16_charmap_supplement_20260828.json"
MAP12_DEFAULT = ROOT / "analysis" / "ggen_advance_12x12_identified_charmap_20260828.json"
MERGED_DEFAULT = ROOT / "analysis" / "ggen_advance_translation_merged_20260828.json"
ROM_DEFAULT = ROOT / "SD Gundam GGeneration Advance (Japan).gba"
CORPUS_DEFAULTS = (
    ROOT / "analysis" / "_tmp_ko_production.json",
    ROOT / "analysis" / "ggen_advance_map_script_translation_source_20260828.json",
    ROOT / "analysis" / "ggen_advance_scenario_pending_closed_strings_20260828.json",
    ROOT / "analysis" / "ggen_advance_scenario_slot_complete_dialogue_20260828.json",
)

SLOT_RE = re.compile(r"<([0-9A-Fa-f]{4})>")
RESERVED = {0x07F8, 0x07FB, 0x07FC, 0x07FD, 0x07FE, 0x0813}
QUARANTINE = {0x03D9, 0x0101, 0x05F2, 0x0514, 0x0652}

# Families with reasonably stable natural-language semantics.  The two noisy
# families are intentionally excluded from language promotion evidence.
TRUSTED_CATEGORIES = {
    "id_command_name",
    "unit_name",
    "character_name",
    "stage_battle_condition_component",
    "stage_battle_condition_text",
    "stage_battle_condition_target_label",
    "stage_battle_condition_static_label",
    "stage_battle_condition_line",
    "id_command_effect_summary",
    "unit_name_alternate",
    "unit_defense_ability",
    "series_title",
    "weapon_name",
    "stage_code",
    "stage_location_name",
    "unit_configuration_action_label",
    "map_system_selector_static_label",
    "unit_ai_type",
    "ui_menu_or_status_text",
    "map_system_function_help",
    "map_system_selector_help",
    "upgrade_part_name",
    "selector_empty_state_message",
    "character_list_state_marker",
    "scroll_list_label",
}


def load_map(path: Path) -> dict[int, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {int(str(k), 16): str(v) for k, v in data["verified_charmap"].items()}


def walk_strings(value: Any, key: str | None = None) -> Iterable[str]:
    """Yield Japanese source strings from heterogeneous project corpus JSON."""
    if isinstance(value, dict):
        # _tmp_ko_production: Japanese strings are dictionary keys.
        if "translations" in value and isinstance(value["translations"], dict):
            yield from (str(k) for k in value["translations"].keys())
        for k, v in value.items():
            if k == "translations":
                continue
            if k in {"jp", "source_text", "source_text_seed", "joined"} and isinstance(v, str):
                yield v
            elif k == "parts" and isinstance(v, list):
                yield from (str(item) for item in v if isinstance(item, str))
            elif isinstance(v, (dict, list)):
                yield from walk_strings(v, k)
    elif isinstance(value, list):
        for item in value:
            yield from walk_strings(item, key)


def clean_corpus_string(text: str) -> str | None:
    text = text.strip()
    if not text or SLOT_RE.search(text):
        return None
    # Skip obvious mojibake/replacement data and very long script aggregates.
    if "�" in text or len(text) > 100:
        return None
    return text


def build_corpus(paths: list[Path]) -> tuple[list[str], dict[int, Counter[str]]]:
    texts: set[str] = set()
    for path in paths:
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        for raw in walk_strings(payload):
            text = clean_corpus_string(raw)
            if text:
                texts.add(text)
    grams: dict[int, Counter[str]] = {2: Counter(), 3: Counter(), 4: Counter()}
    for text in texts:
        for n, counter in grams.items():
            counter.update(text[i : i + n] for i in range(len(text) - n + 1))
    return sorted(texts), grams


def decode_template(source_text: str, map8: dict[int, str], hidden_slot: int | None = None) -> tuple[str, set[int]]:
    unresolved: set[int] = set()

    def repl(match: re.Match[str]) -> str:
        slot = int(match.group(1), 16)
        if slot in RESERVED:
            return ""
        if slot == hidden_slot or slot not in map8:
            unresolved.add(slot)
            return f"¤{slot:04X}¤"
        return map8[slot]

    return SLOT_RE.sub(repl, source_text), unresolved


def fill_slot(template: str, slot: int, char: str) -> str:
    return template.replace(f"¤{slot:04X}¤", char)


def fill_slot_with_positions(template: str, slot: int, char: str) -> tuple[str, list[int]]:
    """Fill a slot while preserving the exact positions introduced by it."""
    marker = f"¤{slot:04X}¤"
    parts = template.split(marker)
    if len(parts) == 1:
        return template, []
    out: list[str] = []
    positions: list[int] = []
    length = 0
    for index, part in enumerate(parts):
        out.append(part)
        length += len(part)
        if index < len(parts) - 1:
            positions.append(length)
            out.append(char)
            length += len(char)
    return "".join(out), positions


def crossing_ngram_score(text: str, positions: list[int], grams: dict[int, Counter[str]]) -> float:
    """Score only n-grams crossing the exact substituted slot positions."""
    score = 0.0
    if not positions:
        return 0.0
    for n, weight in ((2, 1.0), (3, 1.8), (4, 2.4)):
        counter = grams[n]
        seen: set[tuple[int, int]] = set()
        for pos in positions:
            for start in range(max(0, pos - n + 1), min(pos + 1, len(text) - n + 1)):
                key = (n, start)
                if key in seen:
                    continue
                seen.add(key)
                count = counter.get(text[start : start + n], 0)
                score += weight * math.log1p(count)
    return score


def morph_metrics(tokenizer: Tokenizer, text: str) -> tuple[int, int, int]:
    """Return (final lattice min_cost, token_count, unknown_count)."""
    tokens = list(tokenizer.tokenize(text))
    if not tokens:
        return 0, 0, 0
    nodes = [token.node for token in tokens]
    unknown = sum(1 for node in nodes if getattr(node, "node_type", "") == "UNKNOWN")
    final_raw = getattr(nodes[-1], "min_cost", None)
    if final_raw is None:
        final_cost = sum(int(getattr(node, "cost", 0) or 0) for node in nodes)
    else:
        final_cost = int(final_raw)
    return final_cost, len(tokens), unknown


def contexts_by_slot(
    merged: dict[str, Any],
    map8: dict[int, str],
    *,
    hidden_slot: int | None = None,
    trusted_only: bool = True,
) -> dict[int, list[dict[str, Any]]]:
    out: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in merged.get("records", []):
        if row.get("translation_policy") != "translate":
            continue
        if row.get("source_scope") not in {"production", "non_scenario_ui"}:
            continue
        category = str(row.get("semantic_category", ""))
        if trusted_only and category not in TRUSTED_CATEGORIES:
            continue
        source = str(row.get("source_text", ""))
        if not source:
            continue
        decoded, unresolved = decode_template(source, map8, hidden_slot=hidden_slot)
        unresolved = {slot for slot in unresolved if slot not in RESERVED}
        if len(unresolved) != 1:
            continue
        slot = next(iter(unresolved))
        if len(out[slot]) >= 12:
            continue
        out[slot].append({
            "record_id": row.get("record_id"),
            "semantic_category": category,
            "template": decoded,
            "source_text": source,
        })
    return out


def char_pool(map8: dict[int, str], map12: dict[int, str]) -> list[str]:
    chars = set(map8.values()) | set(map12.values())
    return sorted(
        char for char in chars
        if len(char) == 1 and char not in {"<", ">"} and not char.isspace()
    )


def ngram_ranked_pool(
    slot: int,
    contexts: list[dict[str, Any]],
    chars: list[str],
    grams: dict[int, Counter[str]],
    *,
    keep: int,
    must_include: Iterable[str] = (),
) -> list[tuple[str, float]]:
    scored: list[tuple[str, float]] = []
    for char in chars:
        total = 0.0
        for context in contexts:
            text, positions = fill_slot_with_positions(context["template"], slot, char)
            total += crossing_ngram_score(text, positions, grams)
        scored.append((char, total))
    scored.sort(key=lambda item: (-item[1], item[0]))
    selected = scored[:keep]
    selected_chars = {char for char, _ in selected}
    lookup = dict(scored)
    for char in must_include:
        if char and char not in selected_chars:
            selected.append((char, lookup.get(char, 0.0)))
            selected_chars.add(char)
    return selected


def language_candidates(
    slot: int,
    contexts: list[dict[str, Any]],
    chars: list[str],
    grams: dict[int, Counter[str]],
    tokenizer: Tokenizer,
    *,
    top_ngram: int,
    must_include: Iterable[str] = (),
) -> list[dict[str, Any]]:
    pool = ngram_ranked_pool(slot, contexts, chars, grams, keep=top_ngram, must_include=must_include)
    rows = []
    for char, ngram_score in pool:
        morph_cost = 0
        token_count = 0
        unknown_count = 0
        completed = []
        for context in contexts:
            text = fill_slot(context["template"], slot, char)
            completed.append(text)
            cost, tokens, unknown = morph_metrics(tokenizer, text)
            morph_cost += cost
            token_count += tokens
            unknown_count += unknown
        rows.append({
            "char": char,
            "ngram_score": ngram_score,
            "morph_cost": morph_cost,
            "token_count": token_count,
            "unknown_count": unknown_count,
            "completed": completed,
        })
    return rows


def choose_best(rows: list[dict[str, Any]], morph_weight: float, unknown_penalty: float) -> list[dict[str, Any]]:
    ranked = []
    for row in rows:
        score = row["ngram_score"] - morph_weight * row["morph_cost"] - unknown_penalty * row["unknown_count"]
        ranked.append({**row, "combined_score": score})
    ranked.sort(key=lambda row: (-row["combined_score"], row["morph_cost"], -row["ngram_score"], row["char"]))
    return ranked


def viterbi_candidates(args: argparse.Namespace, map8: dict[int, str], map12: dict[int, str]) -> list[dict[str, Any]]:
    known = sjisv.ordered_known(map8)
    chars = sjisv.candidate_charset(map12)
    real_specs = []
    score_slots: set[int] = set()
    score_chars: set[str] = set()
    for left, right in zip(known, known[1:]):
        block = sjisv.eligible_block(
            left, right, chars,
            max_span=args.max_span,
            max_candidate_ratio=args.max_candidate_ratio,
            require_extra_candidate=True,
        )
        if block is None:
            continue
        slots, candidates = block
        real_specs.append((left, right, slots, candidates))
        score_slots.update(slots)
        score_chars.update(candidates)
    scores = fontmod.ensemble_scores(args.rom.read_bytes(), sorted(score_slots), sorted(score_chars))
    merged_freq, categories, samples = sjisv.pending_info(args.merged, map8)
    out: dict[int, dict[str, Any]] = {}
    for left, right, slots, candidates in real_specs:
        predicted = sjisv.viterbi(slots, candidates, scores)
        for slot, char in zip(slots, predicted):
            if slot not in merged_freq or slot in QUARANTINE:
                continue
            rank = sjisv.local_rank(slot, char, candidates, scores)
            if rank > args.max_local_rank:
                continue
            out[slot] = {
                "slot": slot,
                "char": char,
                "local_rank": rank,
                "local_score": scores[slot][char],
                "pending_records": merged_freq[slot],
                "semantic_categories": sorted(categories.get(slot, set())),
                "samples": samples.get(slot, []),
            }
    return list(out.values())


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rom", type=Path, default=ROM_DEFAULT)
    ap.add_argument("--map8", type=Path, default=MAP8_DEFAULT)
    ap.add_argument("--map12", type=Path, default=MAP12_DEFAULT)
    ap.add_argument("--merged", type=Path, default=MERGED_DEFAULT)
    ap.add_argument("--max-span", type=int, default=8)
    ap.add_argument("--max-candidate-ratio", type=float, default=1.5)
    ap.add_argument("--max-local-rank", type=int, default=2)
    ap.add_argument("--top-ngram", type=int, default=16)
    ap.add_argument("--calibration-limit", type=int, default=160)
    ap.add_argument("--top", type=int, default=120)
    args = ap.parse_args(argv)

    paths = [args.rom, args.map8, args.map12, args.merged, *CORPUS_DEFAULTS]
    for path in paths:
        if not path.exists():
            continue
        try:
            path.resolve().relative_to(ROOT.resolve())
        except ValueError:
            raise SystemExit(f"refused path outside advance workspace: {path}")

    map8 = load_map(args.map8)
    map12 = load_map(args.map12)
    merged = json.loads(args.merged.read_text(encoding="utf-8"))
    corpus_texts, grams = build_corpus(list(CORPUS_DEFAULTS))
    chars = char_pool(map8, map12)
    tokenizer = Tokenizer()

    # Calibration: hide verified slots that have at least one trusted row which
    # otherwise decodes completely.  Rank expected character among language
    # alternatives, then grid-search the morph weight.
    calibration_specs = []
    for slot, expected in sorted(map8.items()):
        if slot < 0x0140 or slot > 0x07D0 or len(expected) != 1:
            continue
        ctx_map = contexts_by_slot(merged, map8, hidden_slot=slot, trusted_only=True)
        contexts = ctx_map.get(slot, [])
        if not contexts:
            continue
        rows = language_candidates(
            slot, contexts, chars, grams, tokenizer,
            top_ngram=args.top_ngram, must_include=(expected,),
        )
        calibration_specs.append((slot, expected, contexts, rows))
        if len(calibration_specs) >= args.calibration_limit:
            break

    grid = []
    for morph_weight in (0.0, 0.00005, 0.0001, 0.00015, 0.0002, 0.0003, 0.0005):
        for unknown_penalty in (0.0, 1.0, 2.0, 4.0):
            events = []
            for slot, expected, contexts, rows in calibration_specs:
                ranked = choose_best(rows, morph_weight, unknown_penalty)
                predicted = ranked[0]["char"] if ranked else None
                expected_rank = next((i for i, row in enumerate(ranked, 1) if row["char"] == expected), None)
                margin = (ranked[0]["combined_score"] - ranked[1]["combined_score"]) if len(ranked) > 1 else 999.0
                events.append({
                    "slot": f"0x{slot:04X}",
                    "expected": expected,
                    "predicted": predicted,
                    "correct": predicted == expected,
                    "expected_rank": expected_rank,
                    "margin": margin,
                    "contexts": [ctx["template"] for ctx in contexts[:3]],
                })
            correct = sum(event["correct"] for event in events)
            grid.append({
                "morph_weight": morph_weight,
                "unknown_penalty": unknown_penalty,
                "events": len(events),
                "correct": correct,
                "precision": correct / len(events) if events else 0.0,
                "rows": events,
            })
    grid.sort(key=lambda row: (-row["precision"], -row["correct"], row["morph_weight"], row["unknown_penalty"]))
    best = grid[0] if grid else {"morph_weight": 0.0, "unknown_penalty": 0.0, "events": 0, "correct": 0, "precision": 0.0, "rows": []}

    # Real unresolved Viterbi candidates.  Only rows with trusted single-slot
    # contexts are language-ranked; others remain structure-only holds.
    unresolved_ctx = contexts_by_slot(merged, map8, trusted_only=True)
    real_rows = []
    for candidate in viterbi_candidates(args, map8, map12):
        slot = int(candidate["slot"])
        contexts = unresolved_ctx.get(slot, [])
        if not contexts:
            real_rows.append({**candidate, "language_status": "no_trusted_single_unknown_context"})
            continue
        rows = language_candidates(
            slot, contexts, chars, grams, tokenizer,
            top_ngram=args.top_ngram, must_include=(candidate["char"],),
        )
        ranked = choose_best(rows, best["morph_weight"], best["unknown_penalty"])
        top1 = ranked[0]
        structural = next(row for row in ranked if row["char"] == candidate["char"])
        top_margin = (ranked[0]["combined_score"] - ranked[1]["combined_score"]) if len(ranked) > 1 else 999.0
        structural_rank = next(i for i, row in enumerate(ranked, 1) if row["char"] == candidate["char"])
        real_rows.append({
            **candidate,
            "language_status": "ranked",
            "context_count": len(contexts),
            "language_char": top1["char"],
            "language_margin": round(top_margin, 6),
            "structural_language_rank": structural_rank,
            "structural_combined_score": round(structural["combined_score"], 6),
            "language_combined_score": round(top1["combined_score"], 6),
            "language_ngram_score": round(top1["ngram_score"], 6),
            "language_morph_cost": top1["morph_cost"],
            "structural_ngram_score": round(structural["ngram_score"], 6),
            "structural_morph_cost": structural["morph_cost"],
            "completed_structural": structural["completed"][:6],
            "completed_language": top1["completed"][:6],
            "language_top5": [
                {
                    "char": row["char"],
                    "score": round(row["combined_score"], 6),
                    "ngram": round(row["ngram_score"], 6),
                    "morph_cost": row["morph_cost"],
                    "unknown": row["unknown_count"],
                }
                for row in ranked[:5]
            ],
        })

    payload = {
        "schema_version": 1,
        "method": "same-ROM ngram + Janome rerank of Shift-JIS Viterbi candidates",
        "verified_8x16_slots": len(map8),
        "corpus_unique_strings": len(corpus_texts),
        "corpus_ngram_types": {str(n): len(counter) for n, counter in grams.items()},
        "trusted_categories": sorted(TRUSTED_CATEGORIES),
        "calibration": {
            "events": best["events"],
            "correct": best["correct"],
            "precision": round(best["precision"], 6),
            "morph_weight": best["morph_weight"],
            "unknown_penalty": best["unknown_penalty"],
            "wrong_examples": [row for row in best["rows"] if not row["correct"]][:30],
            "top_parameter_sets": [
                {k: v for k, v in row.items() if k != "rows"}
                for row in grid[:10]
            ],
        },
        "viterbi_candidate_count": len(real_rows),
        "language_ranked_count": sum(row.get("language_status") == "ranked" for row in real_rows),
        "structural_language_agreement": sum(
            row.get("language_status") == "ranked" and row.get("char") == row.get("language_char")
            for row in real_rows
        ),
        "structural_language_disagreement": sum(
            row.get("language_status") == "ranked" and row.get("char") != row.get("language_char")
            for row in real_rows
        ),
        "candidates": sorted(
            real_rows,
            key=lambda row: (-int(row.get("pending_records", 0)), int(row.get("slot", 0))),
        )[: args.top],
        "notes": [
            "Read-only: no charmap/source/ROM writes.",
            "configuration_option_text and id_command_description are excluded from language evidence.",
            "Language disagreement is a hold/override signal, not an automatic promotion by itself.",
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
