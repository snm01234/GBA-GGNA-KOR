#!/usr/bin/env python3
"""Close the remaining unit-list `持` consumer after the status-family follow-up.

The 2026-08-30 runtime check proved that the status family at 0x080E0518 is
fixed, while the left unit list still renders the original `持`.  This analyzer
checks the other known UI atlases for byte-exact clones of the four source
status tiles that carry the standalone/combined `持` badges.

Result: the D54 family (table 0x080D54E4, atlas 0x080D45DC) contains exact
clones in tiles 0x0B8/0x0B9 and 0x0BC/0x0BD.  Those tiles are private to
resource[14] and resource[16], respectively.  This is the remaining consumer
seen in the list rows.
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
from analyze_ggen_advance_fixed_word_semantics_20260830 import (  # noqa: E402
    FAMILIES,
    ROM_BASE,
    parse_map,
    stitch,
    u32,
)

JP_ROM = ROOT / "SD Gundam GGeneration Advance (Japan).gba"
FOLLOWUP_ROM = ROOT / "outputs" / "20260830_ggen_advance_status_badges" / "ggen_advance_status_badges_hold_full_followup_candidate_20260830.gba"
DEFAULT_OUT = ROOT / "analysis" / "ggen_advance_unit_list_hold_consumer_20260830.json"
EXPECTED_JP_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"
EXPECTED_FOLLOWUP_SHA256 = "de69dbc5f20a83784a1edc39760e3a4a5cb73210b584964fcb0c2070b6ca0ad1"

STATUS_TABLE = 0x000E0518
D54_TABLE = 0x000D54E4
D54_ATLAS_RESOURCE = 0x000D45DC
D54_EXPECTED_DECODED = 6080
D54_RESOURCE_COUNT = 17
D54_EXPECTED_SHA256 = "e7dcb1b0e4ab59cbafab5cffb0fd3720256019979c01cb2522f77e618f61976b"

# Clean-JP status -> clean-JP D54 byte-exact clone mapping.
HOLD_TILE_CLONES = {
    0x09B: 0x0B8,
    0x09C: 0x0B9,
    0x09F: 0x0BC,
    0x0A0: 0x0BD,
}
TARGET_D54_RESOURCES = (14, 16)
D54_TABLE_LITERAL_REFS = (0x0801D10C, 0x0801D468, 0x0801D574)
D54_MAIN_RENDERER = 0x0801D09C


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def decode_atlas_at(data: bytes, atlas_offset: int, expected_size: int | None = None) -> tuple[bytes, int]:
    header = struct.unpack_from("<I", data, atlas_offset)[0]
    gate(header & 0x80000000, f"atlas at 0x{atlas_offset:08X} is not custom LZSS")
    body_len = header & 0xFFFF
    atlas = status.lzss_decompress(data[atlas_offset + 4 : atlas_offset + 4 + body_len])
    if expected_size is not None:
        gate(len(atlas) == expected_size, f"atlas size drift at 0x{atlas_offset:08X}: {len(atlas)}")
    return atlas, body_len


def tile_bytes(atlas: bytes, tile_id: int) -> bytes:
    return atlas[tile_id * 32 : tile_id * 32 + 32]


def parse_all_resources(data: bytes, table: int, count: int) -> list[dict[str, Any]]:
    rows = []
    for idx in range(1, count):
        obj = parse_map(data, u32(data, table + idx * 4))
        if obj is None:
            continue
        rows.append({"index": idx, **obj})
    return rows


def family_atlas(data: bytes, family_name: str) -> tuple[bytes, int, int]:
    table = int(FAMILIES[family_name]["table"])
    ptr = u32(data, table)
    gate(ROM_BASE <= ptr < ROM_BASE + len(data), f"invalid {family_name} atlas pointer")
    off = ptr - ROM_BASE
    atlas, body_len = decode_atlas_at(data, off)
    return atlas, off, body_len


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--jp", type=Path, default=JP_ROM)
    ap.add_argument("--followup", type=Path, default=FOLLOWUP_ROM)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    jp = args.jp.read_bytes()
    followup = args.followup.read_bytes()
    gate(sha256(jp) == EXPECTED_JP_SHA256, "Japanese ROM hash drift")
    gate(sha256(followup) == EXPECTED_FOLLOWUP_SHA256, "status follow-up candidate hash drift")

    # Clean status atlas source.
    jp_status_ptr = u32(jp, STATUS_TABLE)
    gate(jp_status_ptr == 0x080DC848, f"clean status pointer drift: 0x{jp_status_ptr:08X}")
    jp_status, _ = decode_atlas_at(jp, jp_status_ptr - ROM_BASE, status.ATLAS_EXPECTED_DECODED)

    # D54 remains original in both canonical and the status follow-up candidate.
    jp_d54_ptr = u32(jp, D54_TABLE)
    followup_d54_ptr = u32(followup, D54_TABLE)
    gate(jp_d54_ptr == 0x080D45DC, f"clean D54 pointer drift: 0x{jp_d54_ptr:08X}")
    gate(followup_d54_ptr == jp_d54_ptr, f"status follow-up unexpectedly redirects D54: 0x{followup_d54_ptr:08X}")
    jp_d54, d54_body_len = decode_atlas_at(jp, D54_ATLAS_RESOURCE, D54_EXPECTED_DECODED)
    followup_d54, _ = decode_atlas_at(followup, D54_ATLAS_RESOURCE, D54_EXPECTED_DECODED)
    gate(jp_d54 == followup_d54, "D54 atlas already changed before this follow-up")
    gate(sha256(jp_d54) == D54_EXPECTED_SHA256, f"D54 decoded hash drift: {sha256(jp_d54)}")

    clone_rows = []
    for status_id, d54_id in HOLD_TILE_CLONES.items():
        source = tile_bytes(jp_status, status_id)
        clone = tile_bytes(jp_d54, d54_id)
        gate(source == clone, f"status tile 0x{status_id:03X} != D54 clone 0x{d54_id:03X}")
        clone_rows.append({
            "status_source_tile": f"0x{status_id:03X}",
            "d54_clone_tile": f"0x{d54_id:03X}",
            "sha256": sha256(source),
            "byte_exact": True,
        })

    resources = parse_all_resources(jp, D54_TABLE, D54_RESOURCE_COUNT)
    refs: dict[int, list[dict[str, int]]] = {tile_id: [] for tile_id in HOLD_TILE_CLONES.values()}
    for row in resources:
        w = int(row["width"])
        for pos, cell in enumerate(row["cells"]):
            tile_id = int(cell) & 0x03FF
            if tile_id in refs:
                refs[tile_id].append({
                    "resource_index": int(row["index"]),
                    "cell_index": pos,
                    "tile_x": pos % w,
                    "tile_y": pos // w,
                })

    expected_refs = {
        0x0B8: [{"resource_index": 14, "cell_index": 1, "tile_x": 1, "tile_y": 0}],
        0x0B9: [{"resource_index": 14, "cell_index": 4, "tile_x": 1, "tile_y": 1}],
        0x0BC: [{"resource_index": 16, "cell_index": 1, "tile_x": 1, "tile_y": 0}],
        0x0BD: [{"resource_index": 16, "cell_index": 4, "tile_x": 1, "tile_y": 1}],
    }
    gate(refs == expected_refs, f"D54 hold tile ownership drift: {refs}")

    resource_reports = []
    for idx in (14, 15, 16):
        row = next(r for r in resources if r["index"] == idx)
        resource_reports.append({
            "resource_index": idx,
            "file_offset": f"0x{int(row['offset']):08X}",
            "size_tiles": [int(row["width"]), int(row["height"])],
            "tile_ids": [f"0x{int(cell)&0x03FF:03X}" for cell in row["cells"]],
            "contains_hold_clone": any((int(cell) & 0x03FF) in refs for cell in row["cells"]),
            "stitched_sha256": sha256(bytes(v for scan in stitch(jp_d54, row) for v in scan)),
        })

    # Search the four original hold-tile payloads in every previously catalogued UI atlas.
    known_family_hits: dict[str, dict[str, list[str]]] = {}
    for family_name in FAMILIES:
        atlas, _, _ = family_atlas(jp, family_name)
        family_result: dict[str, list[str]] = {}
        for status_id in HOLD_TILE_CLONES:
            payload = tile_bytes(jp_status, status_id)
            hits = [tile_id for tile_id in range(len(atlas) // 32) if tile_bytes(atlas, tile_id) == payload]
            family_result[f"0x{status_id:03X}"] = [f"0x{x:03X}" for x in hits]
        known_family_hits[family_name] = family_result

    # The only non-status exact clones must be the D54 targets above.
    gate(known_family_hits["unit_list_candidate"]["0x09B"] == ["0x0B8"], "unexpected D54 0x09B clone set")
    gate(known_family_hits["unit_list_candidate"]["0x09C"] == ["0x0B9"], "unexpected D54 0x09C clone set")
    gate(known_family_hits["unit_list_candidate"]["0x09F"] == ["0x0BC"], "unexpected D54 0x09F clone set")
    gate(known_family_hits["unit_list_candidate"]["0x0A0"] == ["0x0BD"], "unexpected D54 0x0A0 clone set")
    for family_name in ("map_action", "list_badges_candidate", "deployment_candidate"):
        gate(all(not hits for hits in known_family_hits[family_name].values()), f"unexpected hold clone in {family_name}")

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_unit_list_hold_consumer_20260830",
        "result": "PASS",
        "source": {
            "jp": {"path": str(args.jp.relative_to(ROOT)), "sha256": sha256(jp)},
            "status_followup": {"path": str(args.followup.relative_to(ROOT)), "sha256": sha256(followup)},
        },
        "finding": {
            "remaining_family": "D54 battle/list UI family",
            "resource_table_file_offset": f"0x{D54_TABLE:08X}",
            "resource_table_gba_address": f"0x{ROM_BASE + D54_TABLE:08X}",
            "atlas_file_offset": f"0x{D54_ATLAS_RESOURCE:08X}",
            "atlas_gba_address": f"0x{ROM_BASE + D54_ATLAS_RESOURCE:08X}",
            "decoded_bytes": len(jp_d54),
            "decoded_tiles": len(jp_d54) // 32,
            "compressed_body_length": d54_body_len,
            "decoded_sha256": sha256(jp_d54),
            "renderer": f"0x{D54_MAIN_RENDERER:08X}",
            "table_literal_refs": [f"0x{x:08X}" for x in D54_TABLE_LITERAL_REFS],
        },
        "clone_proof": clone_rows,
        "target_resources": resource_reports,
        "tile_ownership": {f"0x{tile_id:03X}": rows for tile_id, rows in refs.items()},
        "known_family_exact_clone_scan": known_family_hits,
        "implementation_policy": {
            "copy_from_already_approved_status_followup_tiles": {
                "0x0B8": "active status 0x09B",
                "0x0B9": "active status 0x09C",
                "0x0BC": "active status 0x09F",
                "0x0BD": "active status 0x0A0",
            },
            "reason": "clean-JP payloads are byte-exact clones, so copying the already-tested Korean replacements preserves the same frame/palette geometry without re-rasterization",
            "private_to_resources_14_16": True,
            "resource_15_suffix_only_preserved": True,
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "out": str(args.out),
        "remaining_family": report["finding"]["remaining_family"],
        "target_resources": list(TARGET_D54_RESOURCES),
        "tile_mapping": {f"0x{k:03X}": f"0x{v:03X}" for k, v in HOLD_TILE_CLONES.items()},
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
