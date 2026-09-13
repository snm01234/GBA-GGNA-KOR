#!/usr/bin/env python3
"""Calibrate Shift-JIS ordered Viterbi recovery for unresolved GGA 8x16 glyphs.

The 8x16 production/UI atlas is not identical to the 12x12 scenario atlas, but
large local regions preserve Japanese character ordering.  Rather than OCRing
one glyph at a time, this analyzer chooses the globally best increasing
Shift-JIS character sequence between two verified 8x16 anchors.

Safety is established with leave-one-out (LOO): a verified 8x16 glyph is
hidden, the two neighboring verified anchors bound the candidate character
range, and Viterbi must recover the hidden character.  The default promotion
rule was selected from observed LOO error modes:

* internal span <= 8 slots;
* candidate characters strictly outnumber slots (so the solution is not a
  forced one-to-one fill);
* candidate_count <= 1.5 * slot_count;
* the selected character is locally within the top 2 Windows-font bitmap
  candidates for that slot.

This tool is read-only.  It never modifies charmap/source/ROM data.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import analyze_ggen_advance_8x16_ordered_block_candidates as fontmod

ROOT = Path(__file__).resolve().parent.parent
ROM_DEFAULT = ROOT / "SD Gundam GGeneration Advance (Japan).gba"
MAP8_DEFAULT = ROOT / "analysis" / "ggen_advance_8x16_charmap_supplement_20260828.json"
MAP12_DEFAULT = ROOT / "analysis" / "ggen_advance_12x12_identified_charmap_20260828.json"
MERGED_DEFAULT = ROOT / "analysis" / "ggen_advance_translation_merged_20260828.json"
RESERVED = {0x07F8, 0x07FB, 0x07FC, 0x07FD, 0x07FE, 0x0813}
QUARANTINE = {0x03D9, 0x0101, 0x05F2, 0x0514, 0x0652}


def load_map(path: Path) -> dict[int, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {int(str(k), 16): str(v) for k, v in payload["verified_charmap"].items()}


def ordered_known(map8: dict[int, str]) -> list[tuple[int, str, int]]:
    rows = []
    for slot, char in sorted(map8.items()):
        value = fontmod.sjis_value(char)
        if value is None or not (0x0140 <= slot <= 0x07D0):
            continue
        rows.append((slot, char, value))
    return rows


def candidate_charset(map12: dict[int, str]) -> list[str]:
    chars = {char for char in map12.values() if fontmod.sjis_value(char) is not None}
    return sorted(chars, key=lambda char: fontmod.sjis_value(char) or -1)


def eligible_block(
    left: tuple[int, str, int],
    right: tuple[int, str, int],
    chars: list[str],
    *,
    max_span: int,
    max_candidate_ratio: float,
    require_extra_candidate: bool,
) -> tuple[list[int], list[str]] | None:
    if left[2] >= right[2]:
        return None
    span = right[0] - left[0] - 1
    if span < 1 or span > max_span:
        return None
    candidates = [
        char
        for char in chars
        if left[2] < (fontmod.sjis_value(char) or -1) < right[2]
    ]
    if len(candidates) < span:
        return None
    if require_extra_candidate and len(candidates) <= span:
        return None
    if len(candidates) > span * max_candidate_ratio:
        return None
    return list(range(left[0] + 1, right[0])), candidates


def viterbi(
    slots: list[int],
    candidates: list[str],
    scores: dict[int, dict[str, float]],
) -> list[str]:
    """Pick the maximum-score increasing subsequence of candidate characters."""
    n = len(slots)
    m = len(candidates)
    neg = -1e30
    dp = [[neg] * (m + 1) for _ in range(n + 1)]
    back: list[list[int | None]] = [[None] * (m + 1) for _ in range(n + 1)]
    for j in range(m + 1):
        dp[0][j] = 0.0
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            skip = dp[i][j - 1]
            take = dp[i - 1][j - 1] + scores[slots[i - 1]][candidates[j - 1]]
            if take >= skip:
                dp[i][j] = take
                back[i][j] = 1
            else:
                dp[i][j] = skip
                back[i][j] = 0
    i, j = n, m
    out: list[str | None] = [None] * n
    while i > 0 and j > 0:
        if back[i][j] == 1:
            out[i - 1] = candidates[j - 1]
            i -= 1
            j -= 1
        else:
            j -= 1
    if any(value is None for value in out):
        raise AssertionError("viterbi failed to fill every slot")
    return [str(value) for value in out]


def local_rank(
    slot: int,
    char: str,
    candidates: list[str],
    scores: dict[int, dict[str, float]],
) -> int:
    ranked = sorted(
        ((scores[slot][candidate], candidate) for candidate in candidates),
        key=lambda item: (-item[0], item[1]),
    )
    return next(index for index, (_score, candidate) in enumerate(ranked, start=1) if candidate == char)


def pending_info(
    merged_path: Path,
    map8: dict[int, str],
) -> tuple[dict[int, int], dict[int, set[str]], dict[int, list[dict[str, Any]]]]:
    payload = json.loads(merged_path.read_text(encoding="utf-8"))
    freq: dict[int, int] = defaultdict(int)
    categories: dict[int, set[str]] = defaultdict(set)
    samples: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in payload.get("records", []):
        if row.get("translation_status") != "pending" or row.get("translation_policy") != "translate":
            continue
        if row.get("source_scope") not in {"production", "non_scenario_ui"}:
            continue
        # Renderer proof: configuration_option_text is drawn in 12x12 mode
        # (0x080004B8 sets object+0x64 bit0; 0x08001238 -> 0x08001354).
        if row.get("semantic_category") == "configuration_option_text":
            continue
        for raw in row.get("source_unresolved_slots", []):
            try:
                slot = int(str(raw), 16)
            except (TypeError, ValueError):
                continue
            if slot in map8 or slot in RESERVED:
                continue
            freq[slot] += 1
            categories[slot].add(str(row.get("semantic_category", "")))
            if len(samples[slot]) < 6:
                samples[slot].append({
                    "record_id": row.get("record_id"),
                    "scope": row.get("source_scope"),
                    "semantic_category": row.get("semantic_category"),
                    "source_text": row.get("source_text"),
                })
    return dict(freq), categories, samples


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
    ap.add_argument("--top", type=int, default=200)
    args = ap.parse_args(argv)
    for path in (args.rom, args.map8, args.map12, args.merged):
        try:
            path.resolve().relative_to(ROOT.resolve())
        except ValueError:
            raise SystemExit(f"refused path outside advance workspace: {path}")

    map8 = load_map(args.map8)
    map12 = load_map(args.map12)
    known = ordered_known(map8)
    chars = candidate_charset(map12)

    # Build all LOO blocks first so bitmap scores are computed once.
    loo_specs: list[tuple[tuple[int, str, int], tuple[int, str, int], tuple[int, str, int], list[int], list[str]]] = []
    score_slots: set[int] = set()
    score_chars: set[str] = set()
    for index in range(1, len(known) - 1):
        left, hidden, right = known[index - 1], known[index], known[index + 1]
        if not (left[2] < hidden[2] < right[2]):
            continue
        block = eligible_block(
            left,
            right,
            chars,
            max_span=args.max_span,
            max_candidate_ratio=args.max_candidate_ratio,
            require_extra_candidate=True,
        )
        if block is None:
            continue
        slots, candidates = block
        loo_specs.append((left, hidden, right, slots, candidates))
        score_slots.update(slots)
        score_chars.update(candidates)

    # Also gather real adjacent-anchor blocks for candidate generation.
    real_specs: list[tuple[tuple[int, str, int], tuple[int, str, int], list[int], list[str]]] = []
    for left, right in zip(known, known[1:]):
        block = eligible_block(
            left,
            right,
            chars,
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

    scores = fontmod.ensemble_scores(
        args.rom.read_bytes(),
        sorted(score_slots),
        sorted(score_chars),
    ) if score_slots and score_chars else {}

    loo_events: list[dict[str, Any]] = []
    for left, hidden, right, slots, candidates in loo_specs:
        predicted = viterbi(slots, candidates, scores)
        offset = hidden[0] - left[0] - 1
        char = predicted[offset]
        rank = local_rank(hidden[0], char, candidates, scores)
        accepted = rank <= args.max_local_rank
        loo_events.append({
            "slot": f"0x{hidden[0]:04X}",
            "expected": hidden[1],
            "predicted": char,
            "correct": char == hidden[1],
            "accepted": accepted,
            "local_rank": rank,
            "local_score": round(scores[hidden[0]][char], 6),
            "span": len(slots),
            "candidate_count": len(candidates),
            "left_anchor": left[1],
            "right_anchor": right[1],
        })

    accepted_loo = [event for event in loo_events if event["accepted"]]
    accepted_correct = sum(bool(event["correct"]) for event in accepted_loo)

    freq, categories, samples = pending_info(args.merged, map8)
    candidates_out: dict[int, dict[str, Any]] = {}
    for left, right, slots, candidates in real_specs:
        predicted = viterbi(slots, candidates, scores)
        for slot, char in zip(slots, predicted):
            if slot not in freq or slot in QUARANTINE:
                continue
            rank = local_rank(slot, char, candidates, scores)
            if rank > args.max_local_rank:
                continue
            row = {
                "slot": f"0x{slot:04X}",
                "char": char,
                "pending_records": freq[slot],
                "local_rank": rank,
                "local_score": round(scores[slot][char], 6),
                "span": len(slots),
                "candidate_count": len(candidates),
                "left_anchor": {"slot": f"0x{left[0]:04X}", "char": left[1]},
                "right_anchor": {"slot": f"0x{right[0]:04X}", "char": right[1]},
                "semantic_categories": sorted(categories.get(slot, set())),
                "samples": samples.get(slot, []),
            }
            existing = candidates_out.get(slot)
            if existing is None or (row["local_rank"], -row["local_score"]) < (existing["local_rank"], -existing["local_score"]):
                candidates_out[slot] = row

    candidate_rows = sorted(
        candidates_out.values(),
        key=lambda row: (-row["pending_records"], row["local_rank"], -row["local_score"], int(row["slot"], 16)),
    )

    payload = {
        "schema_version": 1,
        "method": "Shift-JIS monotone Viterbi over Windows-font bitmap likelihoods",
        "verified_8x16_slots": len(map8),
        "verified_12x12_slots": len(map12),
        "parameters": {
            "max_span": args.max_span,
            "max_candidate_ratio": args.max_candidate_ratio,
            "require_extra_candidate": True,
            "max_local_rank": args.max_local_rank,
        },
        "loo": {
            "events": len(loo_events),
            "accepted_events": len(accepted_loo),
            "accepted_correct": accepted_correct,
            "accepted_wrong": len(accepted_loo) - accepted_correct,
            "accepted_precision": round(accepted_correct / len(accepted_loo), 6) if accepted_loo else 0.0,
            "wrong_examples": [event for event in accepted_loo if not event["correct"]][:30],
        },
        "candidate_count": len(candidate_rows),
        "candidate_pending_record_coverage": sum(row["pending_records"] for row in candidate_rows),
        "candidates": candidate_rows[: args.top],
        "quarantined_slots": [f"0x{slot:04X}" for slot in sorted(QUARANTINE)],
        "notes": [
            "Read-only; no charmap/source/ROM writes.",
            "The candidate sequence is chosen jointly, not by independent per-glyph OCR.",
            "Promotion should additionally reject candidates contradicted by strong decoded context or exact structural evidence.",
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
