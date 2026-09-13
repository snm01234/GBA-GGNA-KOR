#!/usr/bin/env python3
"""Resolve the left unit-list `持` as independent fixed 8x16 graphics.

Runtime rejected both the E0518-only closure and the D54 clone hypothesis for
the left list row.  This analyzer follows the proven battle `実/攻/命/弾`
method: identify literal-referenced fixed graphic descriptors and compare their
pixel geometry against the known clean status `持`.

Two C439-family 1x2 descriptors are selected under the same 0x08005D24 status
predicate and passed to 0x080638E4.  Their dark index-4 footprint is a 45/45
exact match to the clean status `持` outline, shifted one scanline upward.
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
ROOT = THIS_DIR.parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import build_ggen_advance_status_ui_tile_overlay_poc as status  # noqa: E402
from analyze_ggen_advance_fixed_word_semantics_20260830 import parse_map, stitch, u32  # noqa: E402

ROM_BASE = 0x08000000
JP_ROM = ROOT / "SD Gundam GGeneration Advance (Japan).gba"
INPUT_ROM = ROOT / "outputs" / "20260830_ggen_advance_status_badges" / "ggen_advance_status_badges_hold_full_followup_candidate_20260830.gba"
OUT = ROOT / "analysis" / "ggen_advance_unit_list_hold_fixed_graphics_20260830.json"
EXPECTED_JP_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"
EXPECTED_INPUT_SHA256 = "de69dbc5f20a83784a1edc39760e3a4a5cb73210b584964fcb0c2070b6ca0ad1"

STATUS_TABLE = 0x000E0518
STATUS_RESOURCE = 12
D54_TABLE = 0x000D54E4
D54_ORIGINAL_POINTER = 0x080D45DC

FIXED_HEADER_PREFIX = bytes.fromhex("0A0001021000040014004000")
HEADER_BYTES = 0x14
GRAPHIC_BYTES = 0x40
OUTLINE_INDEX = 4
FACE_INDEX = 10

TARGETS = {
    "variant_B": {
        "descriptor_offset": 0x00C43954,
        "graphic_offset": 0x00C43968,
        "literal_refs": [0x08075014, 0x0807517C],
        "expected_tail": "0000000000000100",
        "background_index": 11,
    },
    "variant_A": {
        "descriptor_offset": 0x00C439A8,
        "graphic_offset": 0x00C439BC,
        "literal_refs": [0x08075610, 0x08075780],
        "expected_tail": "0000000000300130",
        "background_index": 10,
    },
}

SIBLING_REFS = {
    "pre_status_B": {"descriptor_offset": 0x00C43C04, "literal_refs": [0x08074F74]},
    "pre_status_A": {"descriptor_offset": 0x00C43C58, "literal_refs": [0x08075578]},
    "suffix_B": {"descriptor_offset": 0x00C43ACC, "literal_refs": [0x0807501C, 0x08075184]},
    "suffix_A": {"descriptor_offset": 0x00C43B00, "literal_refs": [0x08075618, 0x08075788]},
}

# The same logical condition that selected the status-family `持` is evaluated
# immediately before the fixed descriptor draw in both list variants.
PREDICATE = 0x08005D24
DRAW_HELPER = 0x080638E4
PREDICATE_CALLS = [0x08074FEE, 0x08075156, 0x080755EA, 0x0807575A]
DRAW_CALLS = [0x08075072, 0x080751DA, 0x0807566E, 0x080757DE]


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def decode_8x16(raw: bytes) -> list[list[int]]:
    gate(len(raw) == GRAPHIC_BYTES, "8x16 payload size drift")
    out = [[0] * 8 for _ in range(16)]
    for y in range(16):
        base = 0 if y < 8 else 32
        row = base + (y & 7) * 4
        for x in range(8):
            value = raw[row + (x >> 1)]
            out[y][x] = (value >> (4 * (x & 1))) & 0xF
    return out


def literal_value(data: bytes, address: int) -> int:
    return struct.unpack_from("<I", data, address - ROM_BASE)[0]


def thumb_bl_target(data: bytes, address: int) -> int:
    off = address - ROM_BASE
    h1, h2 = struct.unpack_from("<HH", data, off)
    gate((h1 & 0xF800) == 0xF000 and (h2 & 0xF800) == 0xF800, f"not Thumb BL at 0x{address:08X}")
    disp = ((h1 & 0x07FF) << 12) | ((h2 & 0x07FF) << 1)
    if disp & (1 << 22):
        disp -= 1 << 23
    return (address + 4 + disp) & 0xFFFFFFFF


def clean_status_pixels(data: bytes) -> list[list[int]]:
    ptr = u32(data, STATUS_TABLE)
    gate(ptr == 0x080DC848, f"clean status atlas pointer drift: 0x{ptr:08X}")
    off = ptr - ROM_BASE
    header = u32(data, off)
    gate(header & 0x80000000, "clean status atlas not compressed")
    clen = header & 0xFFFF
    atlas = status.lzss_decompress(data[off + 4 : off + 4 + clen])
    obj = parse_map(data, u32(data, STATUS_TABLE + STATUS_RESOURCE * 4))
    gate(obj is not None and (obj["width"], obj["height"]) == (1, 2), "status resource[12] drift")
    return stitch(atlas, obj)


def find_header_family(data: bytes) -> list[int]:
    hits: list[int] = []
    start = 0
    while True:
        pos = data.find(FIXED_HEADER_PREFIX, start)
        if pos < 0:
            break
        hits.append(pos)
        start = pos + 1
    return hits


def pointer_refs(data: bytes, target_offset: int) -> list[int]:
    pattern = struct.pack("<I", ROM_BASE + target_offset)
    refs: list[int] = []
    start = 0
    while True:
        pos = data.find(pattern, start)
        if pos < 0:
            break
        refs.append(ROM_BASE + pos)
        start = pos + 1
    return refs


def outline_shift_score(status_pixels: list[list[int]], fixed_pixels: list[list[int]]) -> dict[str, Any]:
    source = {(x, y) for y, row in enumerate(status_pixels) for x, v in enumerate(row) if v == OUTLINE_INDEX}
    fixed = {(x, y) for y, row in enumerate(fixed_pixels) for x, v in enumerate(row) if v == OUTLINE_INDEX}
    best: tuple[float, int, int, int] | None = None
    for dy in range(-3, 4):
        shifted = {(x, y + dy) for x, y in fixed if 0 <= y + dy < 16}
        inter = len(source & shifted)
        score = 2.0 * inter / (len(source) + len(shifted)) if source or shifted else 1.0
        row = (score, dy, inter, len(shifted))
        if best is None or row[0] > best[0]:
            best = row
    assert best is not None
    return {"dice": best[0], "fixed_to_status_dy": best[1], "intersection": best[2], "fixed_pixels": best[3], "status_pixels": len(source)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--jp", type=Path, default=JP_ROM)
    ap.add_argument("--input", type=Path, default=INPUT_ROM)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    jp = args.jp.read_bytes()
    source = args.input.read_bytes()
    gate(sha256(jp) == EXPECTED_JP_SHA256, "Japanese ROM hash drift")
    gate(sha256(source) == EXPECTED_INPUT_SHA256, "tested status candidate hash drift")
    gate(struct.unpack_from("<I", source, D54_TABLE)[0] == D54_ORIGINAL_POINTER, "input unexpectedly carries rejected D54 redirect")

    status_pixels = clean_status_pixels(jp)
    family = find_header_family(jp)
    gate(family == [0x00C4306C, 0x00C43804, 0x00C43858, 0x00C438AC, 0x00C43900, 0x00C43954, 0x00C439A8, 0x00C43C04, 0x00C43C58], f"C439 descriptor family drift: {[hex(x) for x in family]}")

    target_reports = []
    for name, spec in TARGETS.items():
        desc = int(spec["descriptor_offset"])
        graphic = int(spec["graphic_offset"])
        gate(graphic == desc + HEADER_BYTES, f"{name} graphic offset mismatch")
        gate(jp[desc : desc + len(FIXED_HEADER_PREFIX)] == FIXED_HEADER_PREFIX, f"{name} descriptor prefix drift")
        gate(jp[desc + 12 : desc + 20].hex().upper() == str(spec["expected_tail"]).upper(), f"{name} descriptor flags drift")
        gate(source[desc : desc + HEADER_BYTES + GRAPHIC_BYTES] == jp[desc : desc + HEADER_BYTES + GRAPHIC_BYTES], f"{name} already differs before fixed-list patch")
        refs = pointer_refs(jp, desc)
        gate(refs == spec["literal_refs"], f"{name} literal ref drift: {[hex(x) for x in refs]}")
        pixels = decode_8x16(jp[graphic : graphic + GRAPHIC_BYTES])
        match = outline_shift_score(status_pixels, pixels)
        gate(match == {"dice": 1.0, "fixed_to_status_dy": 1, "intersection": 45, "fixed_pixels": 45, "status_pixels": 45}, f"{name} 持 outline match drift: {match}")
        bg = int(spec["background_index"])
        gate(all(v == bg for v in pixels[0]), f"{name} top background row drift")
        gate(all(v == 15 for v in pixels[15]), f"{name} bottom delimiter row drift")
        target_reports.append({
            "variant": name,
            "descriptor_file_offset": f"0x{desc:08X}",
            "descriptor_address": f"0x{ROM_BASE + desc:08X}",
            "graphic_file_offset": f"0x{graphic:08X}",
            "literal_refs": [f"0x{x:08X}" for x in refs],
            "background_index": bg,
            "outline_match_to_status_hold": match,
            "graphic_sha256": sha256(jp[graphic : graphic + GRAPHIC_BYTES]),
            "pixel_rows": ["".join(format(v, "X") for v in row) for row in pixels],
        })

    sibling_reports = []
    for name, spec in SIBLING_REFS.items():
        desc = int(spec["descriptor_offset"])
        refs = pointer_refs(jp, desc)
        gate(refs == spec["literal_refs"], f"sibling {name} literal ref drift")
        sibling_reports.append({"name": name, "descriptor_file_offset": f"0x{desc:08X}", "literal_refs": [f"0x{x:08X}" for x in refs]})

    for call in PREDICATE_CALLS:
        gate(thumb_bl_target(jp, call) == PREDICATE, f"predicate call drift at 0x{call:08X}")
    for call in DRAW_CALLS:
        gate(thumb_bl_target(jp, call) == DRAW_HELPER, f"draw call drift at 0x{call:08X}")

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_unit_list_hold_fixed_graphics_20260830",
        "result": "PASS",
        "source": {
            "jp": {"path": str(args.jp.relative_to(ROOT)), "sha256": sha256(jp)},
            "tested_status_candidate": {"path": str(args.input.relative_to(ROOT)), "sha256": sha256(source)},
        },
        "rejected_hypothesis": {
            "name": "D54 atlas clone",
            "reason": "runtime test of the 27f0a505... candidate left the list 持 unchanged",
            "input_d54_pointer_verified_original": f"0x{D54_ORIGINAL_POINTER:08X}",
        },
        "finding": {
            "architecture": "independent literal-referenced fixed 8x16 graphics, analogous to battle 実/攻/命/弾 fixed resources",
            "descriptor_format": "0x14-byte C439-family header + 0x40-byte vertical 8x16 4bpp graphic; external state/palette flags in header",
            "header_prefix": FIXED_HEADER_PREFIX.hex().upper(),
            "descriptor_family_offsets": [f"0x{x:08X}" for x in family],
            "predicate": f"0x{PREDICATE:08X}",
            "draw_helper": f"0x{DRAW_HELPER:08X}",
            "predicate_calls": [f"0x{x:08X}" for x in PREDICATE_CALLS],
            "draw_calls": [f"0x{x:08X}" for x in DRAW_CALLS],
            "outline_proof": "both targets have 45/45 exact index-4 outline geometry versus clean status resource[12], with fixed art one scanline above status art",
        },
        "targets": target_reports,
        "preserved_siblings": sibling_reports,
        "implementation_policy": {
            "base_candidate": "use de69... status/detail-tested candidate, not rejected D54 candidate",
            "patch_payload_only": True,
            "descriptor_headers_unchanged": True,
            "two_variants": "patch both B- and A-background variants so normal/focus/state rendering is covered",
            "font": "same Galmuri7 `지` mask already approved in status/detail screen, shifted one scanline upward to match native fixed-resource alignment",
            "face_index": FACE_INDEX,
            "contour_index": OUTLINE_INDEX,
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "out": str(args.out),
        "targets": [{"variant": r["variant"], "descriptor": r["descriptor_file_offset"], "graphic": r["graphic_file_offset"], "refs": r["literal_refs"], "match": r["outline_match_to_status_hold"]} for r in target_reports],
        "predicate": f"0x{PREDICATE:08X}",
        "draw_helper": f"0x{DRAW_HELPER:08X}",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
