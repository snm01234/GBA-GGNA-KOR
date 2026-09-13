#!/usr/bin/env python3
"""Infer 8x16 Japanese glyph labels from the paired 12x12 atlas.

The two text engines use different slot numbers, but their dictionary entries
provide a small, exact cross-font pairing.  This helper uses those pairs only
to calibrate a shape matcher, then emits candidates for the remaining 8x16
slots.  It never changes the immutable source or translation state.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parent.parent
ROM_DEFAULT = ROOT / "SD Gundam GGeneration Advance (Japan).gba"
BIJECTION_DEFAULT = ROOT / "analysis" / "dictionary_comparison_20260827.json"
MAP12_DEFAULT = ROOT / "analysis" / "ggen_advance_12x12_unicode_charmap_20260827.json"
OUT_DEFAULT = ROOT / "analysis" / "ggen_advance_8x16_crossfont_charmap_20260827.json"

BASE8, STRIDE8, COUNT8 = 0x00094028, 32, 2068
BASE12, STRIDE12, COUNT12 = 0x0008AC40, 18, 1992


def glyph8(data: bytes, slot: int) -> np.ndarray:
    raw = data[BASE8 + slot * STRIDE8 : BASE8 + (slot + 1) * STRIDE8]
    result = np.zeros((16, 8), dtype=np.float32)
    for y in range(16):
        for half in range(2):
            value = raw[y * 2 + half]
            for x in range(4):
                result[y, half * 4 + x] = value & 3
                value >>= 2
    return result


def glyph12(data: bytes, slot: int) -> np.ndarray:
    raw = data[BASE12 + slot * STRIDE12 : BASE12 + (slot + 1) * STRIDE12]
    bits = []
    for value in raw:
        bits.extend((value >> bit) & 1 for bit in range(8))
    return np.asarray(bits[:144], dtype=np.float32).reshape(12, 12)


def resized8(mask: np.ndarray) -> np.ndarray:
    image = Image.fromarray((mask > 0).astype(np.uint8) * 255, mode="L")
    return np.asarray(image.resize((12, 12), Image.Resampling.NEAREST), dtype=np.float32) / 255.0


def resized12(mask: np.ndarray) -> np.ndarray:
    image = Image.fromarray((mask > 0).astype(np.uint8) * 255, mode="L")
    return np.asarray(image.resize((8, 16), Image.Resampling.NEAREST), dtype=np.float32) / 255.0


def f1(left: np.ndarray, right: np.ndarray) -> float:
    intersection = float(np.logical_and(left, right).sum())
    total = float(left.sum() + right.sum())
    return (2.0 * intersection / total) if total else 1.0


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=ROM_DEFAULT)
    parser.add_argument("--bijection", type=Path, default=BIJECTION_DEFAULT)
    parser.add_argument("--map12", type=Path, default=MAP12_DEFAULT)
    parser.add_argument("--out", type=Path, default=OUT_DEFAULT)
    parser.add_argument("--top", type=int, default=5)
    args = parser.parse_args(argv)

    data = args.rom.read_bytes()
    bijection = json.loads(args.bijection.read_text(encoding="utf-8"))["slot_bijection_8x16_to_12x12"]
    map12_payload = json.loads(args.map12.read_text(encoding="utf-8"))
    map12 = {int(k, 16): str(v) for k, v in map12_payload["verified_charmap"].items()}
    known = [
        (int(slot8, 16), int(slot12, 16), map12[int(slot12, 16)])
        for slot8, slot12 in bijection.items()
        if int(slot12, 16) in map12
    ]
    candidate_slots = sorted(map12)
    candidate_masks = np.stack([glyph12(data, slot) > 0 for slot in candidate_slots])
    candidate_pixels = candidate_masks.reshape(len(candidate_slots), -1)

    calibration = []
    for slot8, slot12, char in known:
        target = resized8(glyph8(data, slot8)) > 0
        # F1 is robust to the different bit depths and to blank padding.
        intersections = np.logical_and(candidate_masks, target).sum(axis=(1, 2))
        totals = candidate_masks.sum(axis=(1, 2)) + target.sum()
        scores = np.divide(2.0 * intersections, totals, out=np.ones_like(intersections, dtype=np.float32), where=totals != 0)
        order = np.argsort(-scores, kind="stable")
        true_index = candidate_slots.index(slot12)
        rank = int(np.where(order == true_index)[0][0]) + 1
        true_score = float(scores[true_index])
        margin = true_score - float(scores[order[1]]) if true_index == order[0] else true_score - float(scores[order[0]])
        calibration.append({"slot8": f"0x{slot8:04X}", "slot12": f"0x{slot12:04X}", "char": char, "rank": rank, "score": round(true_score, 4), "margin": round(margin, 4)})

    candidates = []
    for slot8 in range(COUNT8):
        if any(slot8 == item[0] for item in known):
            continue
        target = resized8(glyph8(data, slot8)) > 0
        intersections = np.logical_and(candidate_masks, target).sum(axis=(1, 2))
        totals = candidate_masks.sum(axis=(1, 2)) + target.sum()
        scores = np.divide(2.0 * intersections, totals, out=np.ones_like(intersections, dtype=np.float32), where=totals != 0)
        order = np.argsort(-scores, kind="stable")[: max(args.top, 2)]
        best, second = int(order[0]), int(order[1])
        candidates.append({
            "slot8": f"0x{slot8:04X}",
            "char": map12[candidate_slots[best]],
            "slot12": f"0x{candidate_slots[best]:04X}",
            "score": round(float(scores[best]), 4),
            "margin": round(float(scores[best] - scores[second]), 4),
            "alternatives": [
                {"char": map12[candidate_slots[index]], "slot12": f"0x{candidate_slots[index]:04X}", "score": round(float(scores[index]), 4)}
                for index in order
            ],
        })

    rank_values = [item["rank"] for item in calibration]
    payload = {
        "schema_version": 1,
        "method": "cross_font_f1_nearest_12x12_verified_charmap",
        "rom_sha256": __import__("hashlib").sha256(args.rom.read_bytes()).hexdigest(),
        "candidate_12x12_slots": len(candidate_slots),
        "calibration_pairs": len(calibration),
        "calibration_top1": sum(rank == 1 for rank in rank_values),
        "calibration_rank_le_5": sum(rank <= 5 for rank in rank_values),
        "calibration_median_rank": int(np.median(rank_values)) if rank_values else 0,
        "calibration": calibration,
        "candidates": candidates,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: payload[k] for k in ("candidate_12x12_slots", "calibration_pairs", "calibration_top1", "calibration_rank_le_5", "calibration_median_rank")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
