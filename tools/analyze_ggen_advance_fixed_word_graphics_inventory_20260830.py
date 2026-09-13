#!/usr/bin/env python3
"""Inventory 4x2 fixed-word graphics and match likely Japanese UI labels.

This read-only analyzer focuses on the 519-tile status/deployment UI atlas used
by resource_table at 0x080E0518.  It inventories every 4x2 resource and uses
the ROM's own identified 12x12 Japanese glyph bitmaps to score likely two-kanji
labels visible in map-unit, deployment, and unit-list screens.

It does not patch the ROM.  Its purpose is to turn screenshot guesses into a
reproducible shortlist before a graphic builder changes any shared atlas tile.
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

import build_ggen_advance_status_ui_tile_overlay_poc as status
import build_ggen_advance_ko_poc as fontops
from ggen_advance_project_paths import ADVANCE_ROOT, ORIGINAL_ROM

ROM_BASE = 0x08000000
EXPECTED_JP_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"
CHARMAP = ADVANCE_ROOT / "analysis" / "ggen_advance_12x12_identified_charmap_20260828.json"
DEFAULT_OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_fixed_word_graphics_inventory_20260830.json"
RESOURCE_TABLE = status.RESOURCE_TABLE
RESOURCE_COUNT = 69
CANDIDATE_TERMS = (
    "移動", "攻撃", "交信", "捕獲", "確定", "出撃", "発進",
    "汎用", "宇宙", "相性", "地上", "万能", "水陸", "飛行", "水中",
)


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def decode_atlas(data: bytes) -> bytes:
    header = u32(data, status.ATLAS_RESOURCE)
    gate(header & 0x80000000, "status atlas is not compressed")
    comp_len = header & 0xFFFF
    atlas = status.lzss_decompress(data[status.ATLAS_RESOURCE + 4 : status.ATLAS_RESOURCE + 4 + comp_len])
    gate(len(atlas) == status.ATLAS_EXPECTED_DECODED, f"status atlas decoded size drift: {len(atlas)}")
    return atlas


def parse_resource(data: bytes, index: int) -> dict[str, Any] | None:
    address = u32(data, RESOURCE_TABLE + index * 4)
    if not ROM_BASE <= address < ROM_BASE + 0x01000000:
        return None
    offset = address - ROM_BASE
    if offset + 4 > len(data):
        return None
    width, height = data[offset], data[offset + 1]
    count = width * height
    if width == 0 or height == 0 or count > 1024 or offset + 4 + count * 2 > len(data):
        return None
    cells = list(struct.unpack_from(f"<{count}H", data, offset + 4))
    return {
        "index": index,
        "address": address,
        "offset": offset,
        "width": width,
        "height": height,
        "cells": cells,
    }


def stitch(atlas: bytes, row: dict[str, Any]) -> list[list[int]]:
    width = int(row["width"])
    height = int(row["height"])
    out = [[0] * (width * 8) for _ in range(height * 8)]
    for ty in range(height):
        for tx in range(width):
            tile_id = int(row["cells"][ty * width + tx]) & 0x03FF
            tile = status.decode_tile(atlas, tile_id)
            for y in range(8):
                out[ty * 8 + y][tx * 8 : tx * 8 + 8] = tile[y]
    return out


def load_slot_map() -> dict[str, int]:
    raw = json.loads(CHARMAP.read_text(encoding="utf-8"))["verified_charmap"]
    result: dict[str, int] = {}
    for slot_text, char in raw.items():
        result.setdefault(char, int(slot_text, 16))
    return result


def glyph_mask(data: bytes, slot: int) -> list[list[bool]]:
    start = fontops.FONT_12X12_BASE + slot * fontops.FONT_12X12_STRIDE
    raw = data[start : start + fontops.FONT_12X12_STRIDE]
    image = fontops.unpack_12x12(raw)
    return [[bool(image.getpixel((x, y))) for x in range(12)] for y in range(12)]


def word_mask(data: bytes, slots: dict[str, int], text: str) -> list[list[bool]]:
    gate(len(text) == 2, f"candidate term must be two characters: {text}")
    gate(all(ch in slots for ch in text), f"candidate term glyph missing: {text}")
    left = glyph_mask(data, slots[text[0]])
    right = glyph_mask(data, slots[text[1]])
    out = [[False] * 24 for _ in range(12)]
    for y in range(12):
        out[y][0:12] = left[y]
        out[y][12:24] = right[y]
    return out


def dice(a: set[tuple[int, int]], b: set[tuple[int, int]]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return 2.0 * len(a & b) / (len(a) + len(b))


def best_match(pixels: list[list[int]], expected: list[list[bool]]) -> dict[str, Any]:
    # The native fixed-word family uses one bright face index plus a darker
    # contour.  Try every palette index independently and every placement of a
    # 24x12 two-kanji source bitmap inside the 32x16 chunk.
    height = len(pixels)
    width = len(pixels[0])
    target = {(x, y) for y in range(12) for x in range(24) if expected[y][x]}
    best = {"score": -1.0, "palette_index": -1, "x": -1, "y": -1, "observed_pixels": 0, "target_pixels": len(target)}
    for palette_index in range(1, 16):
        for y0 in range(0, height - 12 + 1):
            for x0 in range(0, width - 24 + 1):
                observed = {
                    (x - x0, y - y0)
                    for y in range(y0, y0 + 12)
                    for x in range(x0, x0 + 24)
                    if pixels[y][x] == palette_index
                }
                score = dice(target, observed)
                if score > float(best["score"]):
                    best = {
                        "score": score,
                        "palette_index": palette_index,
                        "x": x0,
                        "y": y0,
                        "observed_pixels": len(observed),
                        "target_pixels": len(target),
                    }
    return best


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rom", type=Path, default=ORIGINAL_ROM)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    data = args.rom.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    gate(len(data) == 16 * 1024 * 1024, "Japanese ROM size drift")
    gate(digest == EXPECTED_JP_SHA256, f"Japanese ROM hash drift: {digest}")
    atlas = decode_atlas(data)
    slots = load_slot_map()
    masks = {term: word_mask(data, slots, term) for term in CANDIDATE_TERMS}

    resources = [row for i in range(RESOURCE_COUNT) if (row := parse_resource(data, i)) is not None]
    chunks = [row for row in resources if (int(row["width"]), int(row["height"])) == (4, 2)]
    inventory: list[dict[str, Any]] = []
    for row in chunks:
        pixels = stitch(atlas, row)
        scores = {term: best_match(pixels, mask) for term, mask in masks.items()}
        ranked = sorted(scores.items(), key=lambda item: float(item[1]["score"]), reverse=True)
        inventory.append({
            "resource_index": row["index"],
            "file_offset": f"0x{int(row['offset']):08X}",
            "tile_ids": [f"0x{int(cell) & 0x03FF:03X}" for cell in row["cells"]],
            "top_matches": [
                {"term": term, **details}
                for term, details in ranked[:6]
            ],
        })

    by_term: dict[str, list[dict[str, Any]]] = {}
    for term in CANDIDATE_TERMS:
        rows = []
        for item in inventory:
            match = next(row for row in item["top_matches"] if row["term"] == term) if any(row["term"] == term for row in item["top_matches"]) else None
            if match is None:
                # Recompute only when the term did not land in the top six.
                resource = next(row for row in chunks if row["index"] == item["resource_index"])
                match = {"term": term, **best_match(stitch(atlas, resource), masks[term])}
            rows.append({"resource_index": item["resource_index"], "file_offset": item["file_offset"], **match})
        by_term[term] = sorted(rows, key=lambda row: float(row["score"]), reverse=True)[:8]

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_fixed_word_graphics_inventory",
        "result": "PASS",
        "source": {"path": args.rom.name, "sha256": digest},
        "atlas": {
            "resource_file_offset": f"0x{status.ATLAS_RESOURCE:08X}",
            "decoded_bytes": len(atlas),
            "decoded_tiles": len(atlas) // 32,
            "resource_table_file_offset": f"0x{RESOURCE_TABLE:08X}",
            "resource_count": RESOURCE_COUNT,
            "four_by_two_resource_count": len(chunks),
        },
        "candidate_terms": list(CANDIDATE_TERMS),
        "four_by_two_inventory": inventory,
        "best_resources_by_term": by_term,
        "known_contract": {
            "41": "汎用",
            "42": "宇宙",
            "43": "地上",
            "44": "万能",
            "45": "水陸",
            "46": "飛行",
            "pending_from_previous_audit": [47, 64, 65],
        },
        "note": "Scores are glyph-shape evidence only; runtime ownership/semantics must be proven before patching a previously unidentified resource.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "out": str(args.out),
        "four_by_two_resources": len(chunks),
        "pending_47": next(x for x in inventory if x["resource_index"] == 47)["top_matches"][:4],
        "pending_64": next(x for x in inventory if x["resource_index"] == 64)["top_matches"][:4],
        "pending_65": next(x for x in inventory if x["resource_index"] == 65)["top_matches"][:4],
    }, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
