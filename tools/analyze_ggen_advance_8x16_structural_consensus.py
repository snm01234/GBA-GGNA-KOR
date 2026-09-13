#!/usr/bin/env python3
"""Read-only high-confidence structural consensus for unresolved GGA 8x16 slots.

Consensus channels:
1. Exact 8x16<->12x12 dictionary anchors with a constant-offset interval.
2. Independent local ROM-bitmap DP alignment between unique same-character anchors.
3. Windows Japanese-font ensemble rank for the proposed character.

The default promotion-review gate is intentionally conservative:
- dictionary interval gap <= 23
- DP agrees on the exact same 12x12 slot/character
- raw 8x16<->12x12 pair shape F1 >= 0.40
- Windows-font ensemble rank <= 20
- ID-command-only quarantine excluded

No project file is modified.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import analyze_ggen_advance_8x16_piecewise_alignment as dpmod
import analyze_ggen_advance_8x16_ordered_block_candidates as fontmod

ROOT = Path(__file__).resolve().parent.parent
DICT_DEFAULT = ROOT / "analysis" / "dictionary_comparison_20260827.json"


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rom", type=Path, default=dpmod.ROM_DEFAULT)
    ap.add_argument("--map8", type=Path, default=dpmod.MAP8_DEFAULT)
    ap.add_argument("--map12", type=Path, default=dpmod.MAP12_DEFAULT)
    ap.add_argument("--merged", type=Path, default=dpmod.MERGED_DEFAULT)
    ap.add_argument("--dictionary", type=Path, default=DICT_DEFAULT)
    ap.add_argument("--max-offset-gap", type=int, default=23)
    ap.add_argument("--min-pair-score", type=float, default=0.40)
    ap.add_argument("--max-font-rank", type=int, default=20)
    ap.add_argument("--top", type=int, default=200)
    args = ap.parse_args(argv)

    for path in (args.rom, args.map8, args.map12, args.merged, args.dictionary):
        try:
            path.resolve().relative_to(ROOT.resolve())
        except ValueError:
            raise SystemExit(f"refused path outside advance workspace: {path}")

    data = args.rom.read_bytes()
    map8 = dpmod.load_map(args.map8)
    map12 = dpmod.load_map(args.map12)
    anchors = dpmod.unique_char_anchors(map8, map12)
    cache8, cache12 = dpmod.make_mask_cache(data)
    params = dpmod.Params(-0.10, 0.0, 0.0)

    # Channel 1: dictionary exact-anchor constant-offset intervals.
    raw_pairs = json.loads(args.dictionary.read_text(encoding="utf-8"))["slot_bijection_8x16_to_12x12"]
    pairs = sorted((int(a, 16), int(b, 16)) for a, b in raw_pairs.items())
    offset_candidates: dict[int, tuple[int, str, int]] = {}
    for (left8, left12), (right8, right12) in zip(pairs, pairs[1:]):
        gap = right8 - left8
        if gap <= 1 or gap > args.max_offset_gap or right12 - left12 != gap:
            continue
        delta = left12 - left8
        for slot8 in range(left8 + 1, right8):
            slot12 = slot8 + delta
            if slot12 in map12:
                offset_candidates[slot8] = (slot12, map12[slot12], gap)

    # Channel 2: local bitmap DP, using current verified map only as block anchors.
    dp_candidates: dict[int, tuple[int, str, float]] = {}
    for left, right in zip(anchors, anchors[1:]):
        if right[1] <= left[1]:
            continue
        span8 = right[0] - left[0]
        span12 = right[1] - left[1]
        if span8 <= 1 or span12 <= 1 or span8 > 64 or span12 > 96:
            continue
        slots8 = list(range(left[0] + 1, right[0]))
        slots12 = list(range(left[1] + 1, right[1]))
        mapping, _ = dpmod.align_block(
            [cache8[s] for s in slots8],
            [cache12[s] for s in slots12],
            slots8,
            slots12,
            params,
        )
        for slot8, (slot12, score) in mapping.items():
            if slot12 in map12:
                dp_candidates[slot8] = (slot12, map12[slot12], score)

    freq, samples = dpmod.pending_slots(args.merged, map8)
    structural: list[dict[str, Any]] = []
    for slot8, count in freq.items():
        if slot8 in dpmod.QUARANTINE:
            continue
        left = offset_candidates.get(slot8)
        right = dp_candidates.get(slot8)
        if left is None or right is None:
            continue
        if left[0] != right[0] or left[1] != right[1] or right[2] < args.min_pair_score:
            continue
        structural.append({
            "slot8": slot8,
            "slot12": left[0],
            "char": left[1],
            "pending_records": count,
            "offset_gap": left[2],
            "pair_score": right[2],
            "samples": samples.get(slot8, []),
        })

    # Channel 3: system-font shape rank.
    candidate_chars = sorted(set(map12.values()))
    score_map = fontmod.ensemble_scores(data, [row["slot8"] for row in structural], candidate_chars)
    for row in structural:
        scores = score_map[row["slot8"]]
        ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        rank = next(i for i, (char, _score) in enumerate(ranked, start=1) if char == row["char"])
        row["font_rank"] = rank
        row["font_score"] = scores[row["char"]]
        row["font_top5"] = [{"char": c, "score": round(v, 4)} for c, v in ranked[:5]]
        row["promotion_gate"] = rank <= args.max_font_rank

    structural.sort(key=lambda row: (not row["promotion_gate"], -row["pending_records"], row["font_rank"], row["slot8"]))
    promoted = [row for row in structural if row["promotion_gate"]]
    payload = {
        "schema_version": 1,
        "method": "dictionary-offset + ROM bitmap DP + Windows-font ensemble consensus",
        "verified_8x16_slots": len(map8),
        "pending_unique_slots": len(freq),
        "parameters": {
            "max_offset_gap": args.max_offset_gap,
            "min_pair_score": args.min_pair_score,
            "max_font_rank": args.max_font_rank,
            "dp": params.key,
        },
        "structural_consensus_count": len(structural),
        "promotion_gate_count": len(promoted),
        "promotion_gate_pending_record_coverage": sum(row["pending_records"] for row in promoted),
        "promotion_candidates": [
            {
                **{k: v for k, v in row.items() if k not in {"slot8", "slot12"}},
                "slot8": f"0x{row['slot8']:04X}",
                "slot12": f"0x{row['slot12']:04X}",
                "pair_score": round(row["pair_score"], 6),
                "font_score": round(row["font_score"], 6),
            }
            for row in promoted[: args.top]
        ],
        "review_candidates": [
            {
                **{k: v for k, v in row.items() if k not in {"slot8", "slot12"}},
                "slot8": f"0x{row['slot8']:04X}",
                "slot12": f"0x{row['slot12']:04X}",
                "pair_score": round(row["pair_score"], 6),
                "font_score": round(row["font_score"], 6),
            }
            for row in structural if not row["promotion_gate"]
        ][: args.top],
        "notes": [
            "Read-only; no charmap/source/ROM writes.",
            "Quarantined ID-command-only slots are excluded.",
            "The three channels are intentionally independent enough that agreement is stronger than any single matcher.",
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
