#!/usr/bin/env python3
"""Calibrate and apply piecewise 8x16<->12x12 font sequence alignment.

This is a read-only analysis tool.  It treats the two ROM font atlases as
ordered glyph sequences and uses already verified same-character anchors to
split them into local monotone blocks.  Within each block, a Needleman-Wunsch
style dynamic program aligns raw glyph shapes, allowing insertions/deletions.

The primary safety gate is leave-one-out (LOO): an already verified 8x16 anchor
is hidden, its surrounding anchors define the local block, and the alignment
must recover the hidden character through the 12x12 charmap.  Parameters are
chosen from a small deterministic grid and only rules meeting the requested
precision floor are eligible for candidate generation.

No charmap, source JSON, or ROM is modified.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
ROM_DEFAULT = ROOT / "SD Gundam GGeneration Advance (Japan).gba"
MAP8_DEFAULT = ROOT / "analysis" / "ggen_advance_8x16_charmap_supplement_20260828.json"
MAP12_DEFAULT = ROOT / "analysis" / "ggen_advance_12x12_identified_charmap_20260828.json"
MERGED_DEFAULT = ROOT / "analysis" / "ggen_advance_translation_merged_20260828.json"

BASE8 = 0x00094028
STRIDE8 = 32
COUNT8 = 2068
BASE12 = 0x0008AC40
STRIDE12 = 18
COUNT12 = 1992
RESERVED = {0x07F8, 0x07FB, 0x07FC, 0x07FD, 0x07FE, 0x0813}
QUARANTINE = {0x03D9, 0x0101, 0x05F2, 0x0514, 0x0652}


def load_map(path: Path) -> dict[int, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {int(str(k), 16): str(v) for k, v in payload["verified_charmap"].items()}


def decode8(data: bytes, slot: int) -> list[list[int]]:
    raw = data[BASE8 + slot * STRIDE8 : BASE8 + (slot + 1) * STRIDE8]
    out = [[0] * 8 for _ in range(16)]
    for y in range(16):
        for half in range(2):
            value = raw[y * 2 + half]
            for x in range(4):
                out[y][half * 4 + x] = 1 if (value & 0x03) else 0
                value >>= 2
    return out


def decode12(data: bytes, slot: int) -> list[list[int]]:
    raw = data[BASE12 + slot * STRIDE12 : BASE12 + (slot + 1) * STRIDE12]
    bits: list[int] = []
    for value in raw:
        bits.extend((value >> bit) & 1 for bit in range(8))
    return [bits[y * 12 : (y + 1) * 12] for y in range(12)]


def bbox(mask: list[list[int]]) -> tuple[int, int, int, int] | None:
    ys: list[int] = []
    xs: list[int] = []
    for y, row in enumerate(mask):
        for x, value in enumerate(row):
            if value:
                ys.append(y)
                xs.append(x)
    if not xs:
        return None
    return min(xs), min(ys), max(xs) + 1, max(ys) + 1


def normalized(mask: list[list[int]], size: int = 11) -> tuple[int, ...]:
    box = bbox(mask)
    if box is None:
        return tuple([0] * (size * size))
    left, top, right, bottom = box
    crop = [[mask[y][x] for x in range(left, right)] for y in range(top, bottom)]
    h = len(crop)
    w = len(crop[0])
    image = Image.new("L", (w, h), 0)
    image.putdata([255 if value else 0 for row in crop for value in row])
    resized = image.resize((size, size), Image.Resampling.NEAREST)
    return tuple(1 if value else 0 for value in resized.getdata())


def f1(a: tuple[int, ...], b: tuple[int, ...]) -> float:
    inter = sum(1 for x, y in zip(a, b) if x and y)
    total = sum(a) + sum(b)
    return (2.0 * inter / total) if total else 1.0


def japanese_cp932(char: str) -> bool:
    if len(char) != 1 or char == "��":
        return False
    try:
        return len(char.encode("cp932")) == 2
    except UnicodeEncodeError:
        return False


def unique_char_anchors(map8: dict[int, str], map12: dict[int, str]) -> list[tuple[int, int, str]]:
    reverse12: dict[str, list[int]] = defaultdict(list)
    for slot, char in map12.items():
        reverse12[char].append(slot)
    anchors = [
        (slot8, reverse12[char][0], char)
        for slot8, char in map8.items()
        if slot8 >= 0x0140
        and japanese_cp932(char)
        and len(reverse12.get(char, ())) == 1
    ]
    return sorted(anchors)


def adjacent_block(
    anchors: list[tuple[int, int, str]],
    target8: int,
    *,
    max_span8: int,
    max_span12: int,
) -> tuple[tuple[int, int, str], tuple[int, int, str]] | None:
    left = None
    right = None
    for anchor in anchors:
        if anchor[0] < target8:
            left = anchor
        elif anchor[0] > target8:
            right = anchor
            break
    if left is None or right is None:
        return None
    if right[1] <= left[1]:
        return None
    span8 = right[0] - left[0]
    span12 = right[1] - left[1]
    if span8 <= 1 or span12 <= 1 or span8 > max_span8 or span12 > max_span12:
        return None
    return left, right


@dataclass(frozen=True)
class Params:
    gap: float
    pos_weight: float
    min_pair_score: float

    @property
    def key(self) -> str:
        return f"gap{self.gap:.2f}_pos{self.pos_weight:.2f}_min{self.min_pair_score:.2f}"


def align_block(
    masks8: list[tuple[int, ...]],
    masks12: list[tuple[int, ...]],
    slots8: list[int],
    slots12: list[int],
    params: Params,
) -> tuple[dict[int, tuple[int, float]], float]:
    """Global align internal sequences; return 8slot -> (12slot, raw shape score)."""
    n = len(slots8)
    m = len(slots12)
    neg_inf = -1e30
    dp = [[neg_inf] * (m + 1) for _ in range(n + 1)]
    back: list[list[str | None]] = [[None] * (m + 1) for _ in range(n + 1)]
    dp[0][0] = 0.0
    for i in range(1, n + 1):
        dp[i][0] = dp[i - 1][0] + params.gap
        back[i][0] = "U"
    for j in range(1, m + 1):
        dp[0][j] = dp[0][j - 1] + params.gap
        back[0][j] = "L"
    for i in range(1, n + 1):
        pi = i / (n + 1)
        for j in range(1, m + 1):
            pj = j / (m + 1)
            shape = f1(masks8[i - 1], masks12[j - 1])
            diag = dp[i - 1][j - 1] + shape - params.pos_weight * abs(pi - pj)
            up = dp[i - 1][j] + params.gap
            left = dp[i][j - 1] + params.gap
            best = diag
            op = "D"
            if up > best + 1e-12:
                best = up
                op = "U"
            if left > best + 1e-12:
                best = left
                op = "L"
            dp[i][j] = best
            back[i][j] = op
    mapping: dict[int, tuple[int, float]] = {}
    i, j = n, m
    while i or j:
        op = back[i][j]
        if op == "D":
            shape = f1(masks8[i - 1], masks12[j - 1])
            if shape >= params.min_pair_score:
                mapping[slots8[i - 1]] = (slots12[j - 1], shape)
            i -= 1
            j -= 1
        elif op == "U":
            i -= 1
        elif op == "L":
            j -= 1
        else:
            break
    return mapping, dp[n][m]


def make_mask_cache(data: bytes) -> tuple[dict[int, tuple[int, ...]], dict[int, tuple[int, ...]]]:
    return (
        {slot: normalized(decode8(data, slot)) for slot in range(COUNT8)},
        {slot: normalized(decode12(data, slot)) for slot in range(COUNT12)},
    )


def recover_one(
    hidden: tuple[int, int, str],
    anchors: list[tuple[int, int, str]],
    cache8: dict[int, tuple[int, ...]],
    cache12: dict[int, tuple[int, ...]],
    map12: dict[int, str],
    params: Params,
    *,
    max_span8: int,
    max_span12: int,
) -> dict[str, Any] | None:
    reduced = [anchor for anchor in anchors if anchor[0] != hidden[0]]
    block = adjacent_block(reduced, hidden[0], max_span8=max_span8, max_span12=max_span12)
    if block is None:
        return None
    left, right = block
    slots8 = list(range(left[0] + 1, right[0]))
    slots12 = list(range(left[1] + 1, right[1]))
    mapping, score = align_block(
        [cache8[s] for s in slots8],
        [cache12[s] for s in slots12],
        slots8,
        slots12,
        params,
    )
    paired = mapping.get(hidden[0])
    if paired is None:
        return {
            "slot8": hidden[0],
            "expected": hidden[2],
            "predicted": None,
            "correct": False,
            "pair_score": None,
            "block_score": score,
            "span8": right[0] - left[0],
            "span12": right[1] - left[1],
        }
    slot12, pair_score = paired
    predicted = map12.get(slot12)
    return {
        "slot8": hidden[0],
        "expected": hidden[2],
        "predicted": predicted,
        "slot12": slot12,
        "correct": predicted == hidden[2],
        "pair_score": pair_score,
        "block_score": score,
        "span8": right[0] - left[0],
        "span12": right[1] - left[1],
    }


def parameter_grid() -> list[Params]:
    return [
        Params(gap=gap, pos_weight=pos, min_pair_score=minimum)
        for gap in (-0.10, -0.20, -0.30, -0.40, -0.50)
        for pos in (0.0, 0.15, 0.30, 0.50, 0.75)
        for minimum in (0.0, 0.35, 0.45, 0.55)
    ]


def pending_slots(path: Path, map8: dict[int, str]) -> tuple[Counter[int], dict[int, list[dict[str, Any]]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    freq: Counter[int] = Counter()
    samples: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in payload.get("records", []):
        if row.get("translation_status") != "pending" or row.get("translation_policy") != "translate":
            continue
        if row.get("source_scope") not in {"production", "non_scenario_ui"}:
            continue
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
            if len(samples[slot]) < 4:
                samples[slot].append({
                    "record_id": row.get("record_id"),
                    "semantic_category": row.get("semantic_category"),
                    "source_text": row.get("source_text"),
                })
    return freq, samples


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rom", type=Path, default=ROM_DEFAULT)
    ap.add_argument("--map8", type=Path, default=MAP8_DEFAULT)
    ap.add_argument("--map12", type=Path, default=MAP12_DEFAULT)
    ap.add_argument("--merged", type=Path, default=MERGED_DEFAULT)
    ap.add_argument("--max-span8", type=int, default=64)
    ap.add_argument("--max-span12", type=int, default=96)
    ap.add_argument("--min-precision", type=float, default=1.0)
    ap.add_argument("--min-events", type=int, default=20)
    ap.add_argument("--top", type=int, default=120)
    args = ap.parse_args(argv)
    for path in (args.rom, args.map8, args.map12, args.merged):
        try:
            path.resolve().relative_to(ROOT.resolve())
        except ValueError:
            raise SystemExit(f"refused path outside advance workspace: {path}")

    data = args.rom.read_bytes()
    map8 = load_map(args.map8)
    map12 = load_map(args.map12)
    anchors = unique_char_anchors(map8, map12)
    cache8, cache12 = make_mask_cache(data)

    evaluations: list[dict[str, Any]] = []
    for params in parameter_grid():
        events: list[dict[str, Any]] = []
        for hidden in anchors:
            result = recover_one(
                hidden, anchors, cache8, cache12, map12, params,
                max_span8=args.max_span8, max_span12=args.max_span12,
            )
            if result is not None:
                events.append(result)
        if not events:
            continue
        correct = sum(bool(event["correct"]) for event in events)
        evaluations.append({
            "params": params,
            "events": len(events),
            "correct": correct,
            "wrong": len(events) - correct,
            "precision": correct / len(events),
            "details": events,
        })
    evaluations.sort(key=lambda item: (-item["precision"], -item["events"], item["params"].key))
    eligible = [
        item for item in evaluations
        if item["precision"] >= args.min_precision and item["events"] >= args.min_events
    ]
    selected = eligible[0] if eligible else (evaluations[0] if evaluations else None)

    freq, samples = pending_slots(args.merged, map8)
    candidates: list[dict[str, Any]] = []
    block_seen: set[tuple[int, int, int, int]] = set()
    if selected is not None:
        params: Params = selected["params"]
        # Adjacent anchors define non-overlapping monotone blocks.
        for left, right in zip(anchors, anchors[1:]):
            if right[1] <= left[1]:
                continue
            span8 = right[0] - left[0]
            span12 = right[1] - left[1]
            if span8 <= 1 or span12 <= 1 or span8 > args.max_span8 or span12 > args.max_span12:
                continue
            block_key = (left[0], right[0], left[1], right[1])
            if block_key in block_seen:
                continue
            block_seen.add(block_key)
            slots8 = list(range(left[0] + 1, right[0]))
            slots12 = list(range(left[1] + 1, right[1]))
            mapping, block_score = align_block(
                [cache8[s] for s in slots8],
                [cache12[s] for s in slots12],
                slots8,
                slots12,
                params,
            )
            for slot8, (slot12, pair_score) in mapping.items():
                if slot8 not in freq or slot8 in QUARANTINE:
                    continue
                char = map12.get(slot12)
                if char is None:
                    continue
                candidates.append({
                    "slot8": f"0x{slot8:04X}",
                    "slot12": f"0x{slot12:04X}",
                    "char": char,
                    "pending_records": freq[slot8],
                    "pair_score": round(pair_score, 6),
                    "block_score": round(block_score, 6),
                    "span8": span8,
                    "span12": span12,
                    "left_anchor": {"slot8": f"0x{left[0]:04X}", "slot12": f"0x{left[1]:04X}", "char": left[2]},
                    "right_anchor": {"slot8": f"0x{right[0]:04X}", "slot12": f"0x{right[1]:04X}", "char": right[2]},
                    "samples": samples.get(slot8, []),
                })
    candidates.sort(key=lambda item: (-item["pending_records"], -item["pair_score"], int(item["slot8"], 16)))

    def serial_eval(item: dict[str, Any]) -> dict[str, Any]:
        p: Params = item["params"]
        return {
            "params": p.key,
            "gap": p.gap,
            "pos_weight": p.pos_weight,
            "min_pair_score": p.min_pair_score,
            "events": item["events"],
            "correct": item["correct"],
            "wrong": item["wrong"],
            "precision": round(item["precision"], 6),
        }

    payload = {
        "schema_version": 1,
        "method": "piecewise local dynamic-programming alignment of ROM 8x16 and 12x12 glyph sequences",
        "verified_8x16_slots": len(map8),
        "verified_12x12_slots": len(map12),
        "unique_same_char_anchors": len(anchors),
        "pending_unique_slots": len(freq),
        "quarantined_slots": [f"0x{x:04X}" for x in sorted(QUARANTINE)],
        "limits": {"max_span8": args.max_span8, "max_span12": args.max_span12},
        "safety_floor": {"min_precision": args.min_precision, "min_events": args.min_events},
        "selected": serial_eval(selected) if selected else None,
        "selected_is_eligible": selected in eligible if selected is not None else False,
        "top_parameter_sets": [serial_eval(item) for item in evaluations[:20]],
        "candidate_count": len(candidates),
        "candidate_pending_record_coverage": sum(item["pending_records"] for item in candidates),
        "top_candidates": candidates[: args.top],
        "selected_wrong_examples": [
            {
                "slot8": f"0x{event['slot8']:04X}",
                "expected": event["expected"],
                "predicted": event["predicted"],
                "slot12": f"0x{event['slot12']:04X}" if event.get("slot12") is not None else None,
                "pair_score": round(event["pair_score"], 6) if event.get("pair_score") is not None else None,
                "span8": event["span8"],
                "span12": event["span12"],
            }
            for event in (selected["details"] if selected else [])
            if not event["correct"]
        ][:30],
        "notes": [
            "Read-only: no charmap/source/ROM writes.",
            "ID-command-only quarantine slots are never emitted as candidates.",
            "A parameter set is promotion-eligible only if it meets the requested LOO precision/event floor.",
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
