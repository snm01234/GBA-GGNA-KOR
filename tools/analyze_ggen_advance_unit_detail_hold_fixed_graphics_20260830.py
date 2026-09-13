#!/usr/bin/env python3
"""Identify the remaining right-side unit-detail `持` fixed graphic.

Runtime verification of the previous candidate proved the left list badge is
now translated, while the small badge immediately before ability text such as
`Iフィールド` still renders Japanese `持` on the right detail pane.

This analyzer closes that remaining consumer.  The relevant branch uses the
same property predicate 0x08005D24 as the already-resolved list badge, but a
separate compressed 1x1 fixed-graphic resource pair in the C491xx family.
"""
from __future__ import annotations

import hashlib
import json
import struct
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import build_ggen_advance_status_ui_tile_overlay_poc as status  # noqa: E402

JP_ROM = ROOT / "SD Gundam GGeneration Advance (Japan).gba"
CURRENT_CANDIDATE = ROOT / "outputs" / "20260830_ggen_advance_status_badges" / "ggen_advance_status_badges_hold_fixed_list_followup_candidate_20260830.gba"
OUT = ROOT / "analysis" / "ggen_advance_unit_detail_hold_fixed_graphics_20260830.json"

EXPECTED_JP_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"
EXPECTED_CURRENT_SHA256 = "04bf4f64b3f0512f86152029680fb58cbebb93c64943bf3a09aaff40ec578d80"

PREDICATE = 0x08005D24
DRAW_HELPER = 0x080638E4
DECOMPRESS_HELPER = 0x08001A84

# Compressed 1x1 fixed graphic variants used by the right unit-detail pane.
TARGETS = {
    "variant_B": {
        "descriptor": 0x00C491C0,
        "literal_refs": [0x080752F0, 0x08075458],
        "predicate_calls": [0x080752C2, 0x0807542A],
    },
    "variant_A": {
        "descriptor": 0x00C491F4,
        "literal_refs": [0x080758F4, 0x08075A5C],
        "predicate_calls": [0x080758C6, 0x08075A2E],
    },
}

# Direct/uncompressed siblings from the same renderer family.  Their inner
# Japanese glyph is the same; the compressed detail-pane copy only closes the
# right/bottom background edge.
DIRECT_SIBLINGS = {
    "variant_B": 0x00C43ACC,
    "variant_A": 0x00C43B00,
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def decode_tile(raw: bytes) -> list[list[int]]:
    gate(len(raw) == 32, f"tile must be 32 bytes, got {len(raw)}")
    return [
        [((raw[y * 4 + x // 2] >> (4 * (x & 1))) & 0xF) for x in range(8)]
        for y in range(8)
    ]


def mask(tile: list[list[int]], values: set[int]) -> set[tuple[int, int]]:
    return {(x, y) for y in range(8) for x in range(8) if tile[y][x] in values}


def dice(a: set[tuple[int, int]], b: set[tuple[int, int]]) -> float:
    return 2 * len(a & b) / (len(a) + len(b)) if a or b else 1.0


def decode_descriptor(data: bytes, offset: int) -> dict:
    header = data[offset : offset + 0x14]
    gate(len(header) == 0x14, "descriptor header truncated")
    flags = header[0]
    width = header[2]
    height = header[3]
    map_rel = struct.unpack_from("<H", header, 4)[0]
    graphic_rel = struct.unpack_from("<H", header, 8)[0]
    graphic_len = struct.unpack_from("<H", header, 10)[0]
    gate(flags & 0x10, f"descriptor 0x{offset:08X} is not compressed")
    gate((width, height) == (1, 1), f"descriptor size drift at 0x{offset:08X}: {width}x{height}")
    gate(map_rel == 0x10 and graphic_rel == 0x14, f"descriptor offsets drift at 0x{offset:08X}")
    map_cell = struct.unpack_from("<H", data, offset + map_rel)[0]
    body = data[offset + graphic_rel : offset + graphic_rel + graphic_len]
    decoded = status.lzss_decompress(body)
    gate(len(decoded) == 32, f"decoded graphic is not one 8x8 tile at 0x{offset:08X}")
    return {
        "flags": flags,
        "width": width,
        "height": height,
        "map_rel": map_rel,
        "graphic_rel": graphic_rel,
        "graphic_len": graphic_len,
        "map_cell": map_cell,
        "compressed_sha256": sha256(body),
        "decoded": decoded,
        "pixels": decode_tile(decoded),
    }


def main() -> int:
    jp = JP_ROM.read_bytes()
    current = CURRENT_CANDIDATE.read_bytes()
    gate(sha256(jp) == EXPECTED_JP_SHA256, "Japanese ROM hash drift")
    gate(sha256(current) == EXPECTED_CURRENT_SHA256, "current candidate hash drift")

    rows = []
    decoded_variants = {}
    for name, spec in TARGETS.items():
        desc = int(spec["descriptor"])
        info = decode_descriptor(jp, desc)
        decoded_variants[name] = info

        # Current candidate intentionally has not touched this remaining pair.
        current_info = decode_descriptor(current, desc)
        gate(current_info["decoded"] == info["decoded"], f"remaining detail graphic already changed: {name}")

        expected_addr = 0x08000000 + desc
        actual_refs = [
            0x08000000 + off
            for off in range(0, len(jp) - 3, 4)
            if u32(jp, off) == expected_addr
        ]
        gate(actual_refs == spec["literal_refs"], f"literal refs drift for {name}: {actual_refs}")

        sibling = DIRECT_SIBLINGS[name]
        sibling_header = jp[sibling : sibling + 0x14]
        gate(sibling_header[:12] == bytes.fromhex("0a0001011000020014002000"), f"direct sibling header drift: {name}")
        sibling_tile = decode_tile(jp[sibling + 0x14 : sibling + 0x34])

        # D/E/F are the bright Japanese strokes; adding index 4 includes its
        # dark contour.  The compressed/detail copy differs only at the closed
        # edge, proving this is the same glyph rendered in another plaque form.
        bright_a = mask(info["pixels"], {13, 14, 15})
        bright_b = mask(sibling_tile, {13, 14, 15})
        full_a = mask(info["pixels"], {4, 13, 14, 15})
        full_b = mask(sibling_tile, {4, 13, 14, 15})
        bright_dice = dice(bright_a, bright_b)
        full_dice = dice(full_a, full_b)
        gate(bright_dice > 0.96, f"bright glyph mismatch for {name}: {bright_dice}")
        gate(full_dice > 0.99, f"full glyph mismatch for {name}: {full_dice}")

        rows.append({
            "variant": name,
            "descriptor_file_offset": f"0x{desc:08X}",
            "descriptor_gba_address": f"0x{0x08000000 + desc:08X}",
            "flags": f"0x{info['flags']:02X}",
            "resource_size_tiles": [1, 1],
            "map_cell": f"0x{info['map_cell']:04X}",
            "compressed_length": info["graphic_len"],
            "decoded_bytes": 32,
            "decoded_sha256": sha256(info["decoded"]),
            "literal_refs": [f"0x{x:08X}" for x in spec["literal_refs"]],
            "predicate_calls": [f"0x{x:08X}" for x in spec["predicate_calls"]],
            "direct_sibling_file_offset": f"0x{sibling:08X}",
            "direct_sibling_bright_mask_dice": bright_dice,
            "direct_sibling_full_mask_dice": full_dice,
            "decoded_pixels_hex": ["".join(format(v, "X") for v in row) for row in info["pixels"]],
        })

    # A/B variants must carry the same glyph; only their A/B background edge
    # differs.  This is the normal/focus (or alternating palette) pair.
    b = decoded_variants["variant_B"]["pixels"]
    a = decoded_variants["variant_A"]["pixels"]
    diffs = []
    for y in range(8):
        for x in range(8):
            if a[y][x] != b[y][x]:
                diffs.append([x, y, b[y][x], a[y][x]])
    gate(diffs, "A/B variants unexpectedly identical")
    gate(all(old == 11 and new == 10 for _, _, old, new in diffs), f"A/B difference is not pure B->A background: {diffs}")

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_unit_detail_hold_fixed_graphics_20260830",
        "result": "PASS",
        "runtime_feedback": "left list `持` is fixed, but right unit-detail ability badge before text such as Iフィールド still shows Japanese `持`",
        "finding": {
            "consumer_class": "compressed 1x1 fixed graphic, independent of E0518/D54 atlas edits",
            "predicate": f"0x{PREDICATE:08X}",
            "draw_helper": f"0x{DRAW_HELPER:08X}",
            "compressed_graphic_decoder": f"0x{DECOMPRESS_HELPER:08X}",
            "descriptor_flag_bit_0x10": "set; 0x080638E4 routes the 0x14-relative payload through 0x08001A84 before drawing",
            "targets": rows,
            "variant_difference_pixels": diffs,
            "why_previous_patches_missed_it": "the visible 8x8 badge is a compressed fixed-graphic resource selected directly by code; it is neither an E0518 status-atlas tile nor the rejected D54 clone, and its 8x8 glyph shape is distinct from the earlier 8x16 fixed-list badge",
        },
        "status": "consumer identified; no ROM modification in this analysis step",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "out": str(OUT),
        "targets": [row["descriptor_file_offset"] for row in rows],
        "predicate": f"0x{PREDICATE:08X}",
        "draw_helper": f"0x{DRAW_HELPER:08X}",
        "status": report["status"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
