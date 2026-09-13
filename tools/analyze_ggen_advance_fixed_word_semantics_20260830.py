#!/usr/bin/env python3
"""Identify fixed 32x16 Japanese UI words by exact native 12x12 glyph geometry.

The scanner complements the screenshot/NMI inventory.  It decodes each known UI
resource family, reconstructs every 4x2 tilemap in display orientation, and
compares each palette-index plane against exact glyph masks from the clean ROM's
native 12x12 font using the verified charmap.  This is especially useful for
closing unit-list labels such as 確定/搭載/出撃 without relying on visual guesses.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from analyze_ggen_advance_action_graphics_scan_20260830 import lzss_decompress, decode_tile  # noqa: E402
from ggen_advance_project_paths import ADVANCE_ROOT  # noqa: E402

ROM_BASE = 0x08000000
JP_ROM = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Japan).gba"
CHARMAP = ADVANCE_ROOT / "analysis" / "ggen_advance_12x12_identified_charmap_20260828.json"
OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_fixed_word_semantics_20260830.json"
EXPECTED_SHA = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"
FONT12_BASE = 0x0008AC40
FONT12_STRIDE = 18

FAMILIES = {
    "map_action": {"table": 0x000D23E0, "max_entries": 44},
    "unit_list_candidate": {"table": 0x000D54E4, "max_entries": 17},
    "list_badges_candidate": {"table": 0x000D87BC, "max_entries": 13},
    "deployment_candidate": {"table": 0x000DAB70, "max_entries": 25},
    "status": {"table": 0x000E0518, "max_entries": 69},
}

TERMS = [
    "移動", "隊列", "攻撃", "間接", "捕獲", "変形", "交信", "発進", "確定", "合体", "個別",
    "搭載", "出撃", "相性", "汎用", "宇宙", "地上", "万能", "水陸", "飛行",
    "待機", "詳細", "能力", "情報", "範囲", "回復", "補給", "地形", "帰還", "離脱", "散開",
]


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def u16(data: bytes, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def glyph_points(data: bytes, slot: int) -> set[tuple[int, int]]:
    raw = data[FONT12_BASE + slot * FONT12_STRIDE : FONT12_BASE + (slot + 1) * FONT12_STRIDE]
    gate(len(raw) == FONT12_STRIDE, f"font slot overrun 0x{slot:04X}")
    pts: set[tuple[int, int]] = set()
    for y in range(12):
        for x in range(12):
            bit = y * 12 + x
            if raw[bit // 8] & (1 << (bit & 7)):
                pts.add((x, y))
    return pts


def parse_map(data: bytes, ptr: int) -> dict[str, Any] | None:
    if not (ROM_BASE <= ptr < ROM_BASE + len(data)):
        return None
    off = ptr - ROM_BASE
    if off + 4 > len(data):
        return None
    w, h = data[off], data[off + 1]
    if not (1 <= w <= 64 and 1 <= h <= 32 and off + 4 + w * h * 2 <= len(data)):
        return None
    cells = list(struct.unpack_from(f"<{w*h}H", data, off + 4))
    return {"offset": off, "width": w, "height": h, "cells": cells}


def stitch(atlas: bytes, obj: dict[str, Any]) -> list[list[int]]:
    w, h = int(obj["width"]), int(obj["height"])
    out = [[0] * (w * 8) for _ in range(h * 8)]
    for ty in range(h):
        for tx in range(w):
            cell = int(obj["cells"][ty * w + tx])
            tile = decode_tile(atlas, cell & 0x03FF)
            hf, vf = bool(cell & 0x0400), bool(cell & 0x0800)
            for yy in range(8):
                sy = 7 - yy if vf else yy
                for xx in range(8):
                    sx = 7 - xx if hf else xx
                    out[ty * 8 + yy][tx * 8 + xx] = tile[sy * 8 + sx]
    return out


def dice(a: set[tuple[int, int]], b: set[tuple[int, int]]) -> float:
    if not a or not b:
        return 0.0
    return 2.0 * len(a & b) / (len(a) + len(b))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rom", type=Path, default=JP_ROM)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    data = args.rom.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    gate(digest == EXPECTED_SHA, f"unexpected JP hash {digest}")
    cm = json.loads(CHARMAP.read_text(encoding="utf-8"))["verified_charmap"]
    rev = {char: int(slot, 16) for slot, char in cm.items()}
    available_terms = [term for term in TERMS if all(char in rev for char in term)]
    glyphs = {char: glyph_points(data, rev[char]) for term in available_terms for char in term}

    report_families: dict[str, Any] = {}
    for family_name, spec in FAMILIES.items():
        table = int(spec["table"])
        atlas_ptr = u32(data, table)
        gate(ROM_BASE <= atlas_ptr < ROM_BASE + len(data), f"{family_name} atlas pointer invalid")
        atlas_off = atlas_ptr - ROM_BASE
        header = u32(data, atlas_off)
        gate((header & 0xFFFF0000) == 0x80000000, f"{family_name} atlas not custom LZSS")
        body_len = header & 0xFFFF
        atlas = lzss_decompress(data[atlas_off + 4 : atlas_off + 4 + body_len])
        resources = []
        for idx in range(1, int(spec["max_entries"])):
            ptr = u32(data, table + idx * 4)
            obj = parse_map(data, ptr)
            if obj is None or (obj["width"], obj["height"]) not in {(4, 2), (3, 2)}:
                continue
            pixels = stitch(atlas, obj)
            value_sets = {
                value: {(x, y) for y in range(16) for x in range(int(obj["width"]) * 8) if pixels[y][x] == value}
                for value in range(1, 16)
            }
            matches = []
            for term in available_terms:
                for x0 in range(0, int(obj["width"]) * 8 - 24 + 1):
                    for y0 in range(0, 5):
                        target: set[tuple[int, int]] = set()
                        for char_index, char in enumerate(term):
                            for x, y in glyphs[char]:
                                target.add((x0 + char_index * 12 + x, y0 + y))
                        for value, observed in value_sets.items():
                            score = dice(target, observed)
                            if score >= 0.35:
                                matches.append({
                                    "term": term,
                                    "score": score,
                                    "palette_index": value,
                                    "x": x0,
                                    "y": y0,
                                    "target_pixels": len(target),
                                    "observed_pixels": len(observed),
                                    "intersection": len(target & observed),
                                })
            matches.sort(key=lambda row: row["score"], reverse=True)
            resources.append({
                "resource_index": idx,
                "file_offset": f"0x{obj['offset']:08X}",
                "palette_banks": sorted({(int(cell) >> 12) & 0xF for cell in obj["cells"]}),
                "tile_ids": [f"0x{int(cell)&0x3FF:03X}" for cell in obj["cells"]],
                "top_matches": matches[:12],
            })
        report_families[family_name] = {
            "table_file_offset": f"0x{table:08X}",
            "atlas_pointer": f"0x{atlas_ptr:08X}",
            "atlas_file_offset": f"0x{atlas_off:08X}",
            "decoded_tiles": len(atlas) // 32,
            "four_by_two_resources": resources,
        }

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_fixed_word_semantics_20260830",
        "result": "PASS",
        "source": {"path": args.rom.name, "sha256": digest},
        "method": "exact clean-ROM 12x12 glyph mask vs palette-index plane; alignment x=0..8,y=0..4; Dice score",
        "terms": available_terms,
        "families": report_families,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    compact = {}
    for family, item in report_families.items():
        compact[family] = [
            {"resource": row["resource_index"], "best": row["top_matches"][0] if row["top_matches"] else None}
            for row in item["four_by_two_resources"]
        ]
    print(json.dumps({"result": "PASS", "out": str(args.out), "family_counts": {name: len(item["four_by_two_resources"]) for name, item in report_families.items()}}, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
