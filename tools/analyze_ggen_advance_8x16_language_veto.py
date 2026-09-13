#!/usr/bin/env python3
"""Detect duplicate/out-of-order exceptions in GGA 8x16 Viterbi candidates.

The monotone Shift-JIS Viterbi model is accurate on its calibrated local
blocks, but the 8x16 atlas contains duplicate/out-of-order characters.  Those
exceptions often reveal themselves linguistically: the structural candidate
breaks a Japanese compound while a character already verified elsewhere in
8x16 creates a dictionary compound and sharply lowers Janome's path cost.

This analyzer therefore uses language only as a conservative veto/override
signal.  It does NOT attempt free-form character prediction.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from janome.tokenizer import Tokenizer

import analyze_ggen_advance_8x16_language_rerank as lang

ROOT = Path(__file__).resolve().parent.parent


def compound_metrics(
    tokenizer: Tokenizer,
    template: str,
    slot: int,
    char: str,
    grams: dict[int, Any],
) -> dict[str, Any]:
    text, positions = lang.fill_slot_with_positions(template, slot, char)
    tokens = list(tokenizer.tokenize(text))
    cursor = 0
    compound_positions: set[int] = set()
    compounds: list[str] = []
    for token in tokens:
        surface = token.surface
        start, end = cursor, cursor + len(surface)
        node = token.node
        if getattr(node, "node_type", "") == "SYS_DICT" and len(surface) >= 2:
            hit = False
            for index, position in enumerate(positions):
                if start <= position < end:
                    compound_positions.add(index)
                    hit = True
            if hit:
                compounds.append(surface)
        cursor = end
    morph_cost, token_count, unknown_count = lang.morph_metrics(tokenizer, text)
    return {
        "text": text,
        "compound_hits": len(compound_positions),
        "compounds": compounds,
        "morph_cost": morph_cost,
        "token_count": token_count,
        "unknown_count": unknown_count,
        "ngram_score": lang.crossing_ngram_score(text, positions, grams),
    }


def aggregate_metrics(
    tokenizer: Tokenizer,
    contexts: list[dict[str, Any]],
    slot: int,
    char: str,
    grams: dict[int, Any],
) -> dict[str, Any]:
    rows = [compound_metrics(tokenizer, context["template"], slot, char, grams) for context in contexts]
    return {
        "char": char,
        "context_count": len(rows),
        "compound_hits": sum(row["compound_hits"] for row in rows),
        "compound_contexts": sum(bool(row["compound_hits"]) for row in rows),
        "morph_cost": sum(row["morph_cost"] for row in rows),
        "token_count": sum(row["token_count"] for row in rows),
        "unknown_count": sum(row["unknown_count"] for row in rows),
        "ngram_score": sum(row["ngram_score"] for row in rows),
        "compounds": sorted({surface for row in rows for surface in row["compounds"]}),
        "completed": [row["text"] for row in rows],
    }


def candidate_pool_by_ngram(
    contexts: list[dict[str, Any]],
    slot: int,
    chars: list[str],
    grams: dict[int, Any],
    keep: int,
    must_include: tuple[str, ...] = (),
) -> list[str]:
    scored = []
    for char in chars:
        score = 0.0
        for context in contexts:
            text, positions = lang.fill_slot_with_positions(context["template"], slot, char)
            score += lang.crossing_ngram_score(text, positions, grams)
        scored.append((score, char))
    scored.sort(key=lambda item: (-item[0], item[1]))
    out = [char for _score, char in scored[:keep]]
    for char in must_include:
        if char and char not in out:
            out.append(char)
    return out


def find_best_override(
    proposal: dict[str, Any],
    alternatives: list[dict[str, Any]],
    *,
    min_cost_gain: int,
    min_ngram_gain: float,
) -> dict[str, Any] | None:
    eligible = []
    for alt in alternatives:
        if alt["char"] == proposal["char"]:
            continue
        if alt["compound_hits"] <= proposal["compound_hits"]:
            continue
        cost_gain = proposal["morph_cost"] - alt["morph_cost"]
        ngram_gain = alt["ngram_score"] - proposal["ngram_score"]
        if cost_gain < min_cost_gain or ngram_gain < min_ngram_gain:
            continue
        eligible.append({**alt, "cost_gain": cost_gain, "ngram_gain": ngram_gain})
    if not eligible:
        return None
    eligible.sort(
        key=lambda row: (
            -row["compound_hits"],
            -row["cost_gain"],
            -row["ngram_gain"],
            row["morph_cost"],
            row["char"],
        )
    )
    return eligible[0]


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rom", type=Path, default=lang.ROM_DEFAULT)
    ap.add_argument("--map8", type=Path, default=lang.MAP8_DEFAULT)
    ap.add_argument("--map12", type=Path, default=lang.MAP12_DEFAULT)
    ap.add_argument("--merged", type=Path, default=lang.MERGED_DEFAULT)
    ap.add_argument("--top-ngram", type=int, default=32)
    ap.add_argument("--calibration-limit", type=int, default=180)
    ap.add_argument("--top", type=int, default=120)
    args = ap.parse_args(argv)

    for path in (args.rom, args.map8, args.map12, args.merged, *lang.CORPUS_DEFAULTS):
        if not path.exists():
            continue
        try:
            path.resolve().relative_to(ROOT.resolve())
        except ValueError:
            raise SystemExit(f"refused path outside advance workspace: {path}")

    map8 = lang.load_map(args.map8)
    map12 = lang.load_map(args.map12)
    merged = json.loads(args.merged.read_text(encoding="utf-8"))
    _texts, grams = lang.build_corpus(list(lang.CORPUS_DEFAULTS))
    tokenizer = Tokenizer()

    # Duplicate/out-of-order failures can only be repaired safely with a
    # character that is already independently verified somewhere in 8x16.
    verified_chars = sorted({char for char in map8.values() if len(char) == 1 and not char.isspace()})

    # Calibration asks: if the correct verified character were the structural
    # proposal, would this veto rule incorrectly replace it with another known
    # 8x16 character?  Choose the most permissive zero-false-veto threshold.
    calibration = []
    for slot, expected in sorted(map8.items()):
        if not (0x0140 <= slot <= 0x07D0) or len(expected) != 1:
            continue
        contexts = lang.contexts_by_slot(merged, map8, hidden_slot=slot, trusted_only=True).get(slot, [])
        if not contexts:
            continue
        pool = candidate_pool_by_ngram(contexts, slot, verified_chars, grams, args.top_ngram, (expected,))
        metrics = [aggregate_metrics(tokenizer, contexts, slot, char, grams) for char in pool]
        proposal = next(row for row in metrics if row["char"] == expected)
        calibration.append((slot, expected, contexts, proposal, metrics))
        if len(calibration) >= args.calibration_limit:
            break

    threshold_rows = []
    for min_cost_gain in (2000, 4000, 6000, 8000, 10000, 12000, 16000):
        for min_ngram_gain in (0.0, 0.5, 1.0, 2.0, 3.0):
            false_vetoes = []
            for slot, expected, contexts, proposal, metrics in calibration:
                override = find_best_override(
                    proposal,
                    metrics,
                    min_cost_gain=min_cost_gain,
                    min_ngram_gain=min_ngram_gain,
                )
                if override is not None:
                    false_vetoes.append({
                        "slot": f"0x{slot:04X}",
                        "expected": expected,
                        "override": override["char"],
                        "cost_gain": override["cost_gain"],
                        "ngram_gain": round(override["ngram_gain"], 6),
                        "proposal_compounds": proposal["compounds"],
                        "override_compounds": override["compounds"],
                        "completed_expected": proposal["completed"][:3],
                        "completed_override": override["completed"][:3],
                    })
            threshold_rows.append({
                "min_cost_gain": min_cost_gain,
                "min_ngram_gain": min_ngram_gain,
                "events": len(calibration),
                "false_vetoes": len(false_vetoes),
                "false_examples": false_vetoes[:12],
            })

    zero_false = [row for row in threshold_rows if row["false_vetoes"] == 0 and row["events"] >= 20]
    zero_false.sort(key=lambda row: (row["min_cost_gain"], row["min_ngram_gain"]))
    selected = zero_false[0] if zero_false else sorted(
        threshold_rows,
        key=lambda row: (row["false_vetoes"], row["min_cost_gain"], row["min_ngram_gain"]),
    )[0]

    # Generate the current Viterbi candidates using the already calibrated
    # structural gate, then apply only the conservative language veto.
    class VArgs:
        rom = args.rom
        map8 = args.map8
        map12 = args.map12
        merged = args.merged
        max_span = 8
        max_candidate_ratio = 1.5
        max_local_rank = 2

    structural = lang.viterbi_candidates(VArgs, map8, map12)
    unresolved_ctx = lang.contexts_by_slot(merged, map8, trusted_only=True)
    results = []
    for candidate in structural:
        slot = int(candidate["slot"])
        contexts = unresolved_ctx.get(slot, [])
        if not contexts:
            results.append({**candidate, "language_veto_status": "no_trusted_single_unknown_context"})
            continue
        pool = candidate_pool_by_ngram(
            contexts,
            slot,
            verified_chars,
            grams,
            args.top_ngram,
            (candidate["char"],),
        )
        metrics = [aggregate_metrics(tokenizer, contexts, slot, char, grams) for char in pool]
        proposal = next(row for row in metrics if row["char"] == candidate["char"])
        override = find_best_override(
            proposal,
            metrics,
            min_cost_gain=selected["min_cost_gain"],
            min_ngram_gain=selected["min_ngram_gain"],
        )
        if override is not None:
            status = "strong_duplicate_override"
        elif proposal["compound_hits"] > 0:
            status = "compound_supported"
        else:
            status = "neutral_no_compound"
        results.append({
            **candidate,
            "language_veto_status": status,
            "context_count": len(contexts),
            "proposal_metrics": {
                k: (round(v, 6) if isinstance(v, float) else v)
                for k, v in proposal.items()
                if k != "char"
            },
            "override": None if override is None else {
                "char": override["char"],
                "cost_gain": override["cost_gain"],
                "ngram_gain": round(override["ngram_gain"], 6),
                "compound_hits": override["compound_hits"],
                "compounds": override["compounds"],
                "morph_cost": override["morph_cost"],
                "ngram_score": round(override["ngram_score"], 6),
                "completed": override["completed"][:6],
            },
        })

    status_counts: dict[str, int] = {}
    for row in results:
        key = row["language_veto_status"]
        status_counts[key] = status_counts.get(key, 0) + 1

    payload = {
        "schema_version": 1,
        "method": "conservative Janome compound veto for duplicate/out-of-order 8x16 exceptions",
        "verified_8x16_slots": len(map8),
        "verified_alternative_characters": len(verified_chars),
        "calibration": {
            "events": len(calibration),
            "selected_threshold": {
                "min_cost_gain": selected["min_cost_gain"],
                "min_ngram_gain": selected["min_ngram_gain"],
                "false_vetoes": selected["false_vetoes"],
            },
            "thresholds": [
                {k: v for k, v in row.items() if k != "false_examples"}
                for row in sorted(threshold_rows, key=lambda row: (row["false_vetoes"], row["min_cost_gain"], row["min_ngram_gain"]))[:20]
            ],
            "nearest_false_examples": next(
                (row["false_examples"] for row in sorted(threshold_rows, key=lambda row: (row["false_vetoes"], row["min_cost_gain"], row["min_ngram_gain"])) if row["false_vetoes"]),
                [],
            ),
        },
        "structural_candidate_count": len(results),
        "status_counts": status_counts,
        "candidates": sorted(results, key=lambda row: (-int(row.get("pending_records", 0)), int(row["slot"])))[: args.top],
        "notes": [
            "Read-only: no ROM/charmap/source writes.",
            "Only already-verified 8x16 characters are eligible duplicate overrides.",
            "compound_supported is positive evidence; neutral candidates remain held unless independently confirmed.",
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
