#!/usr/bin/env python3
"""Evaluate direct 8x16-to-12x12 glyph matching against known pairs."""
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

BASE8, STRIDE8 = 0x00094028, 32
BASE12, STRIDE12 = 0x0008AC40, 18
COUNT12 = 1992


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


def resize(mask: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    image = Image.fromarray((mask > 0).astype(np.uint8) * 255, mode="L")
    return np.asarray(image.resize(size, Image.Resampling.NEAREST), dtype=np.float32) / 255.0


def distance(left: np.ndarray, right: np.ndarray, metric: str) -> float:
    if metric == "binary12":
        a = resize(left, (12, 12))
        b = right
        return float(np.abs(a - b).sum())
    if metric == "binary8":
        a = left > 0
        b = resize(right, (8, 16)) > 0
        return float(np.logical_xor(a, b).sum())
    if metric == "projection":
        a = resize(left, (12, 12))
        b = right
        return float(np.abs(a.sum(axis=0) - b.sum(axis=0)).sum() + np.abs(a.sum(axis=1) - b.sum(axis=1)).sum())
    raise ValueError(metric)


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=ROM_DEFAULT)
    parser.add_argument("--bijection", type=Path, default=BIJECTION_DEFAULT)
    parser.add_argument("--map12", type=Path, default=MAP12_DEFAULT)
    args = parser.parse_args(argv)
    data = args.rom.read_bytes()
    bijection = json.loads(args.bijection.read_text(encoding="utf-8"))["slot_bijection_8x16_to_12x12"]
    map12 = {int(k, 16): v for k, v in json.loads(args.map12.read_text(encoding="utf-8"))["verified_charmap"].items()}
    pairs = [(int(a, 16), int(b, 16), map12[int(b, 16)]) for a, b in bijection.items() if int(b, 16) in map12]
    all12 = [(slot, glyph12(data, slot)) for slot in range(COUNT12)]
    report = {}
    for metric in ("binary12", "binary8", "projection"):
        correct = 0
        ranks = []
        for slot8, slot12, _char in pairs:
            target = glyph8(data, slot8)
            ranked = sorted((distance(target, candidate, metric), slot) for slot, candidate in all12)
            rank = next(index for index, (_score, slot) in enumerate(ranked, start=1) if slot == slot12)
            ranks.append(rank)
            correct += rank == 1
        report[metric] = {
            "pairs": len(ranks),
            "top1": correct,
            "top1_percent": round(correct * 100 / len(ranks), 2) if ranks else 0,
            "median_rank": int(np.median(ranks)) if ranks else 0,
            "rank_le_10": sum(rank <= 10 for rank in ranks),
        }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
