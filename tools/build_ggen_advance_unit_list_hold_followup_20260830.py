#!/usr/bin/env python3
"""Patch the remaining D54/list `持` clones on top of the tested hold follow-up.

The preceding candidate already fixes every E0518/status consumer and removes
the three-dot residue.  Runtime testing still showed original `持` glyphs in
the left unit-list rows.  Static comparison proves that D54 tiles
0x0B8/0x0B9/0x0BC/0x0BD are byte-exact clean-JP clones of status tiles
0x09B/0x09C/0x09F/0x0A0.

This builder therefore does not rasterize `지` again.  It copies the already
runtime-tested Korean tile payloads from the active status atlas into a cloned
D54 atlas, redirects only D54 table[0], and leaves every D54 tilemap/resource
and all other D54 tiles unchanged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

from PIL import Image

THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import build_ggen_advance_status_ui_tile_overlay_poc as status  # noqa: E402
from analyze_ggen_advance_fixed_word_semantics_20260830 import (  # noqa: E402
    ROM_BASE,
    parse_map,
    stitch,
    u32,
)

INPUT_ROM = ROOT / "outputs" / "20260830_ggen_advance_status_badges" / "ggen_advance_status_badges_hold_full_followup_candidate_20260830.gba"
JP_ROM = ROOT / "SD Gundam GGeneration Advance (Japan).gba"
OUT_DIR = ROOT / "outputs" / "20260830_ggen_advance_status_badges"
DEFAULT_OUT = OUT_DIR / "ggen_advance_status_badges_hold_full_list_followup_candidate_20260830.gba"
DEFAULT_MANIFEST = ROOT / "analysis" / "ggen_advance_status_badges_hold_full_list_followup_20260830.json"
DEFAULT_PREVIEW = OUT_DIR / "ggen_advance_status_badges_hold_full_list_followup_preview_20260830.png"

EXPECTED_INPUT_SHA256 = "de69dbc5f20a83784a1edc39760e3a4a5cb73210b584964fcb0c2070b6ca0ad1"
EXPECTED_JP_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"

STATUS_TABLE = 0x000E0518
D54_TABLE = 0x000D54E4
D54_ORIGINAL_ATLAS_ADDRESS = 0x080D45DC
D54_ORIGINAL_ATLAS_OFFSET = 0x000D45DC
D54_EXPECTED_DECODED = 6080
D54_EXPECTED_DECODED_SHA256 = "e7dcb1b0e4ab59cbafab5cffb0fd3720256019979c01cb2522f77e618f61976b"
D54_RESOURCE_COUNT = 17

# 0x01270000 is already occupied by the approved action-menu allocation.
# 0x01280000 is the next measured zero-filled 64 KiB page in the current input.
LIST_ATLAS_ALLOC = 0x01280000
LIST_ATLAS_ADDRESS = ROM_BASE + LIST_ATLAS_ALLOC

STATUS_TO_D54 = {
    0x09B: 0x0B8,
    0x09C: 0x0B9,
    0x09F: 0x0BC,
    0x0A0: 0x0BD,
}
D54_TARGET_TILES = sorted(STATUS_TO_D54.values())
TARGET_RESOURCES = (14, 16)
PROTECTED_RESOURCE = 15


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def decode_resource(data: bytes, offset: int, expected_size: int | None = None) -> tuple[bytearray, int]:
    header = struct.unpack_from("<I", data, offset)[0]
    gate(header & 0x80000000, f"resource at 0x{offset:08X} is not compressed")
    body_len = header & 0xFFFF
    decoded = status.lzss_decompress(data[offset + 4 : offset + 4 + body_len])
    if expected_size is not None:
        gate(len(decoded) == expected_size, f"decoded size drift at 0x{offset:08X}: {len(decoded)}")
    return bytearray(decoded), body_len


def active_status_atlas(data: bytes) -> tuple[bytes, int, int]:
    pointer = struct.unpack_from("<I", data, STATUS_TABLE)[0]
    gate(ROM_BASE <= pointer < ROM_BASE + len(data), f"active status pointer invalid: 0x{pointer:08X}")
    offset = pointer - ROM_BASE
    decoded, body_len = decode_resource(data, offset, status.ATLAS_EXPECTED_DECODED)
    return bytes(decoded), offset, body_len


def tile_bytes(atlas: bytes | bytearray, tile_id: int) -> bytes:
    return bytes(atlas[tile_id * 32 : tile_id * 32 + 32])


def set_tile(atlas: bytearray, tile_id: int, payload: bytes) -> None:
    gate(len(payload) == 32, f"tile payload size drift for 0x{tile_id:03X}")
    atlas[tile_id * 32 : tile_id * 32 + 32] = payload


def resource_obj(data: bytes, index: int) -> dict:
    obj = parse_map(data, u32(data, D54_TABLE + index * 4))
    gate(obj is not None, f"D54 resource[{index}] missing")
    return obj


def block_sha(atlas: bytes | bytearray, obj: dict) -> str:
    pixels = stitch(bytes(atlas), obj)
    return sha256(bytes(value for row in pixels for value in row))


def build_preview(atlas: bytes, source_rom: bytes, out: Path) -> None:
    specs = [(14, "지"), (15, "suffix-only"), (16, "지+suffix")]
    scale = 5
    pad = 8
    gap = 10
    blocks = []
    for index, label in specs:
        obj = resource_obj(source_rom, index)
        pixels = stitch(atlas, obj)
        blocks.append((label, pixels))
    max_w = max(len(p[0]) for _, p in blocks)
    canvas_w = max_w * scale + pad * 2
    canvas_h = sum(len(p) * scale + gap for _, p in blocks) + pad
    image = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    palette = {
        3: (70, 40, 20, 255),
        4: (20, 45, 35, 255),
        5: (116, 57, 1, 255),
        6: (239, 41, 15, 255),
        7: (80, 180, 120, 255),
        8: (30, 150, 105, 255),
        9: (255, 181, 40, 255),
        10: (251, 229, 59, 255),
        11: (255, 255, 141, 255),
        13: (80, 115, 80, 255),
        14: (210, 235, 210, 255),
        15: (255, 255, 255, 255),
    }
    y0 = pad
    for _, pixels in blocks:
        for y, row in enumerate(pixels):
            for x, value in enumerate(row):
                rgba = palette.get(value, (90, 90, 90, 255))
                for sy in range(scale):
                    for sx in range(scale):
                        image.putpixel((pad + x * scale + sx, y0 + y * scale + sy), rgba)
        y0 += len(pixels) * scale + gap
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", type=Path, default=INPUT_ROM)
    ap.add_argument("--jp", type=Path, default=JP_ROM)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--preview", type=Path, default=DEFAULT_PREVIEW)
    args = ap.parse_args()

    source = args.input.read_bytes()
    jp = args.jp.read_bytes()
    gate(len(source) == 32 * 1024 * 1024, "input candidate must be 32 MiB")
    gate(sha256(source) == EXPECTED_INPUT_SHA256, f"input candidate hash drift: {sha256(source)}")
    gate(sha256(jp) == EXPECTED_JP_SHA256, "Japanese ROM hash drift")

    status_atlas, status_offset, status_body_len = active_status_atlas(source)

    d54_pointer_before = struct.unpack_from("<I", source, D54_TABLE)[0]
    gate(d54_pointer_before == D54_ORIGINAL_ATLAS_ADDRESS, f"D54 pointer already redirected: 0x{d54_pointer_before:08X}")
    d54, d54_body_len = decode_resource(source, D54_ORIGINAL_ATLAS_OFFSET, D54_EXPECTED_DECODED)
    before_d54 = bytes(d54)
    gate(sha256(before_d54) == D54_EXPECTED_DECODED_SHA256, f"D54 atlas hash drift: {sha256(before_d54)}")

    jp_status_pointer = struct.unpack_from("<I", jp, STATUS_TABLE)[0]
    gate(jp_status_pointer == 0x080DC848, "clean status pointer drift")
    jp_status, _ = decode_resource(jp, jp_status_pointer - ROM_BASE, status.ATLAS_EXPECTED_DECODED)

    # Prove source-clone identity and copy the already-tested Korean payload.
    tile_reports = []
    for status_id, d54_id in STATUS_TO_D54.items():
        clean_status_payload = tile_bytes(jp_status, status_id)
        clean_d54_payload = tile_bytes(before_d54, d54_id)
        tested_korean_payload = tile_bytes(status_atlas, status_id)
        gate(clean_d54_payload == clean_status_payload, f"clean clone mismatch 0x{status_id:03X}->0x{d54_id:03X}")
        gate(tested_korean_payload != clean_status_payload, f"status Korean tile 0x{status_id:03X} is not patched")
        set_tile(d54, d54_id, tested_korean_payload)
        tile_reports.append({
            "status_source_tile": f"0x{status_id:03X}",
            "d54_target_tile": f"0x{d54_id:03X}",
            "clean_source_sha256": sha256(clean_status_payload),
            "korean_payload_sha256": sha256(tested_korean_payload),
            "copied_byte_exact_from_tested_status_followup": True,
        })

    changed_tiles = [
        tile_id for tile_id in range(len(d54) // 32)
        if tile_bytes(d54, tile_id) != tile_bytes(before_d54, tile_id)
    ]
    gate(changed_tiles == D54_TARGET_TILES, f"unexpected D54 tile changes: {[hex(x) for x in changed_tiles]}")

    # Ownership gates: target payloads are private to resource[14]/[16].
    refs = {tile_id: [] for tile_id in D54_TARGET_TILES}
    all_resource_shas_before = {}
    all_resource_shas_after = {}
    for index in range(2, D54_RESOURCE_COUNT):
        obj = resource_obj(source, index)
        all_resource_shas_before[index] = block_sha(before_d54, obj)
        all_resource_shas_after[index] = block_sha(d54, obj)
        for pos, cell in enumerate(obj["cells"]):
            tile_id = int(cell) & 0x03FF
            if tile_id in refs:
                refs[tile_id].append(index)
    gate(refs == {0x0B8: [14], 0x0B9: [14], 0x0BC: [16], 0x0BD: [16]}, f"D54 target ownership drift: {refs}")
    changed_resources = [i for i in all_resource_shas_before if all_resource_shas_before[i] != all_resource_shas_after[i]]
    gate(changed_resources == [14, 16], f"unexpected D54 resource changes: {changed_resources}")
    gate(all_resource_shas_before[PROTECTED_RESOURCE] == all_resource_shas_after[PROTECTED_RESOURCE], "resource[15] suffix-only graphic changed")

    rebuilt = status.literal_only_compress(bytes(d54))
    gate(status.lzss_decompress(rebuilt[4:]) == bytes(d54), "D54 rebuilt compression round-trip failed")
    gate(LIST_ATLAS_ALLOC + len(rebuilt) <= len(source), "D54 clone allocation exceeds ROM")
    gate(source[LIST_ATLAS_ALLOC : LIST_ATLAS_ALLOC + len(rebuilt)] == bytes(len(rebuilt)), "D54 clone allocation is not zero-filled")

    candidate = bytearray(source)
    candidate[LIST_ATLAS_ALLOC : LIST_ATLAS_ALLOC + len(rebuilt)] = rebuilt
    struct.pack_into("<I", candidate, D54_TABLE, LIST_ATLAS_ADDRESS)

    gate(struct.unpack_from("<I", candidate, D54_TABLE)[0] == LIST_ATLAS_ADDRESS, "D54 pointer redirect failed")
    gate(candidate[status_offset : status_offset + status_body_len + 4] == source[status_offset : status_offset + status_body_len + 4], "tested status atlas changed unexpectedly")

    # Only the 4-byte D54 table[0] pointer in the original half plus the new
    # private clone allocation may differ from the tested input candidate.
    allowed_original = set(range(D54_TABLE, D54_TABLE + 4))
    unexpected_original = [
        i for i in range(0x01000000)
        if candidate[i] != source[i] and i not in allowed_original
    ]
    gate(not unexpected_original, f"unexpected original-half changes: {unexpected_original[:8]}")
    private_diffs = [i for i in range(0x01000000, len(source)) if candidate[i] != source[i]]
    gate(private_diffs, "no private D54 clone bytes written")
    gate(min(private_diffs) >= LIST_ATLAS_ALLOC and max(private_diffs) < LIST_ATLAS_ALLOC + len(rebuilt), "private changes escaped D54 clone allocation")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(candidate)
    build_preview(bytes(d54), source, args.preview)

    diff_offsets = [i for i, (a, b) in enumerate(zip(candidate, source)) if a != b]
    manifest = {
        "schema_version": 1,
        "kind": "ggen_advance_status_badges_hold_full_list_followup_20260830",
        "result": "PASS",
        "source": {
            "path": str(args.input.relative_to(ROOT)),
            "sha256": sha256(source),
            "size": len(source),
        },
        "output": {
            "path": str(args.out.relative_to(ROOT)),
            "sha256": sha256(candidate),
            "size": len(candidate),
        },
        "remaining_consumer": {
            "family": "D54 battle/list UI family",
            "resource_table_file_offset": f"0x{D54_TABLE:08X}",
            "resource_table_address_before": f"0x{ROM_BASE + D54_TABLE:08X}",
            "original_atlas_address": f"0x{D54_ORIGINAL_ATLAS_ADDRESS:08X}",
            "original_atlas_file_offset": f"0x{D54_ORIGINAL_ATLAS_OFFSET:08X}",
            "original_compressed_body_length": d54_body_len,
            "decoded_bytes": len(d54),
            "decoded_tiles": len(d54) // 32,
            "decoded_sha256_before": sha256(before_d54),
            "decoded_sha256_after": sha256(d54),
            "target_resources": list(TARGET_RESOURCES),
            "protected_resource_15": True,
        },
        "copy_mapping": tile_reports,
        "relocation": {
            "file_offset": f"0x{LIST_ATLAS_ALLOC:08X}",
            "gba_address": f"0x{LIST_ATLAS_ADDRESS:08X}",
            "rebuilt_resource_bytes": len(rebuilt),
            "rebuilt_compressed_body_length": len(rebuilt) - 4,
            "zero_filled_before_write": True,
            "round_trip_verified": True,
        },
        "verification": {
            "result": "PASS",
            "input_status_followup_hash_verified": True,
            "status_atlas_preserved_byte_exact": True,
            "d54_source_matches_clean_japanese": True,
            "clean_d54_tiles_match_clean_status_clones": True,
            "korean_payloads_copied_from_tested_status_followup": True,
            "changed_d54_tiles": [f"0x{x:03X}" for x in changed_tiles],
            "changed_d54_resources": changed_resources,
            "resource_15_unchanged": True,
            "all_other_d54_tiles_unchanged": True,
            "all_d54_tilemaps_unchanged": True,
            "palette_modified": False,
            "original_half_changes_restricted_to_d54_table0_pointer": True,
            "private_changes_restricted_to_d54_clone": True,
        },
        "changed_bytes_vs_input": len(diff_offsets),
        "preview": str(args.preview.relative_to(ROOT)),
        "measurement_checkpoints": [
            "left unit-list rows that still showed original 持 should now use the same `지` glyph as the tested status/detail screen",
            "verify rows with the small right-side suffix/N variant remain aligned and that only the 持 component changes",
            "right detail panel `지`, `방패`, `만`, and existing `간` must remain identical to the previous tested candidate",
            "switch through enough list rows to cover both D54 resource[14] and resource[16] variants",
        ],
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "result": "PASS",
        "out": str(args.out),
        "sha256": sha256(candidate),
        "manifest": str(args.manifest),
        "preview": str(args.preview),
        "changed_d54_tiles": [f"0x{x:03X}" for x in changed_tiles],
        "changed_d54_resources": changed_resources,
        "changed_bytes_vs_input": len(diff_offsets),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
