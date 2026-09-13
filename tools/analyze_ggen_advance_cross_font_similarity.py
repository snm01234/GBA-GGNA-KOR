#!/usr/bin/env python3
"""Measure whether the 8x16 and 12x12 Japanese atlases share glyph shapes."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parent.parent
ROM_DEFAULT = ROOT / "SD Gundam GGeneration Advance (Japan).gba"
SEED8_DEFAULT = ROOT / "font_tables" / "ggen_advance_japanese_charmap_seed_20260826.json"
SEED12_DEFAULT = ROOT / "analysis" / "scenario_event_12x12_charmap_seed_20260827.json"

BASE8 = 0x00094028
STRIDE8 = 32
COUNT8 = 2068
BASE12 = 0x0008AC40
STRIDE12 = 18
COUNT12 = 1992


def mask8(data: bytes, slot: int) -> np.ndarray:
    raw = data[BASE8 + slot * STRIDE8 : BASE8 + (slot + 1) * STRIDE8]
    result = np.zeros((16, 8), dtype=np.uint8)
    for y in range(16):
        for half in range(2):
            value = raw[y * 2 + half]
            for x in range(4):
                result[y, half * 4 + x] = value & 0x03
                value >>= 2
    return result


def mask12(data: bytes, slot: int) -> np.ndarray:
    raw = data[BASE12 + slot * STRIDE12 : BASE12 + (slot + 1) * STRIDE12]
    bits = []
    for value in raw:
        bits.extend((value >> bit) & 1 for bit in range(8))
    return np.asarray(bits[:144], dtype=np.uint8).reshape(12, 12)


def resized(mask: np.ndarray, size: tuple[int, int], threshold: int = 1) -> np.ndarray:
    image = Image.fromarray((mask >= threshold).astype(np.uint8) * 255, mode="L")
    return (np.asarray(image.resize(size, Image.Resampling.NEAREST)) > 0).astype(np.uint8)


def f1(left: np.ndarray, right: np.ndarray) -> float:
    intersection = int(np.logical_and(left, right).sum())
    total = int(left.sum() + right.sum())
    return (2.0 * intersection / total) if total else 1.0


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=ROM_DEFAULT)
    parser.add_argument("--seed8", type=Path, default=SEED8_DEFAULT)
    parser.add_argument("--seed12", type=Path, default=SEED12_DEFAULT)
    parser.add_argument("--out", type=Path, default=ROOT / "analysis" / "ggen_advance_cross_font_similarity_20260827.json")
    args = parser.parse_args(argv)

    data = args.rom.read_bytes()
    map8 = {char: int(slot, 16) for slot, char in json.loads(args.seed8.read_text(encoding="utf-8"))["verified_charmap"].items()}
    map12 = {char: int(slot, 16) for slot, char in json.loads(args.seed12.read_text(encoding="utf-8"))["verified_charmap"].items()}
    shared = sorted(set(map8) & set(map12))
    scores = []
    for char in shared:
        left = mask8(data, map8[char])
        right = mask12(data, map12[char])
        candidates = []
        for threshold in (1, 2, 3):
            candidates.append({
                "threshold": threshold,
                "f1_12_to_8": round(f1(left >= threshold, resized(right, (8, 16))), 4),
                "f1_8_to_12": round(f1(resized(left, (12, 12)), right), 4),
            })
        scores.append({"char": char, "slot8": f"0x{map8[char]:04X}", "slot12": f"0x{map12[char]:04X}", "scores": candidates})
    payload = {"shared_characters": len(shared), "scores": scores}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for threshold in (1, 2, 3):
        values = [item["scores"][threshold - 1]["f1_12_to_8"] for item in scores]
        print(json.dumps({"threshold": threshold, "shared": len(values), "mean_12_to_8": round(sum(values) / len(values), 4) if values else 0, "high_0_8": sum(value >= 0.8 for value in values), "high_0_7": sum(value >= 0.7 for value in values)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
