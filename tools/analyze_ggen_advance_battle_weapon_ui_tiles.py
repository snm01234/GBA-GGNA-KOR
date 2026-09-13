#!/usr/bin/env python3
"""Analyze the battle-screen weapon UI graphics family.

The unit-status weapon rows and the battle weapon selector look similar but do
not consume the same atlas.  This read-only analyzer proves the second resource
family, its renderer/table references, and the lack of byte-identical copies of
the status mini-badge tiles inside the battle atlas.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

from ggen_advance_project_paths import ADVANCE_ROOT
import build_ggen_advance_status_ui_tile_overlay_poc as status

ROM_BASE = 0x08000000
EXPECTED_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"
JP_ROM = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Japan).gba"
DEFAULT_OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_battle_weapon_ui_tiles_20260829.json"

BATTLE_ATLAS_RESOURCE = 0x000D45DC
BATTLE_RESOURCE_TABLE = 0x000D54E4
BATTLE_ATLAS_DECODED = 6080
BATTLE_BASE_MAP = 0x000D4F4C
TABLE_LITERAL_OFFSETS = (0x0001D10C, 0x0001D468, 0x0001D574)
TABLE_ADDRESS = ROM_BASE + BATTLE_RESOURCE_TABLE

EXPECTED_RESOURCES = {
    0: (0x000D45DC, 107, 9),
    2: (0x000D4F4C, 30, 20),
    3: (0x000D5400, 4, 2),
    4: (0x000D5414, 4, 2),
    5: (0x000D5428, 4, 2),
    6: (0x000D543C, 4, 2),
    7: (0x000D5450, 4, 2),
    8: (0x000D5464, 4, 2),
    9: (0x000D5478, 2, 2),
    10: (0x000D5484, 2, 2),
    11: (0x000D5490, 2, 2),
    12: (0x000D549C, 2, 2),
    13: (0x000D54A8, 2, 2),
    14: (0x000D54B4, 3, 2),
    15: (0x000D54C4, 3, 2),
    16: (0x000D54D4, 3, 2),
}

STATUS_PROBE_TILES = (
    0x163, 0x16A,  # 実
    0x164, 0x16B,  # 攻
    0x165, 0x16C,  # 命
    0x166, 0x16D,  # 弾
    0x168, 0x16E,  # 射
    0x1ED, 0x1EE,  # 近
    0x1EB, 0x1EC,  # 単
    0x169, 0x16F,  # 全
    0x1E7, 0x1E8, 0x1E9, 0x1EA,  # 間 16x16
)


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def resource_map(data: bytes, index: int) -> dict[str, object] | None:
    ptr = u32(data, BATTLE_RESOURCE_TABLE + index * 4)
    if ptr == 0:
        return None
    gate(ROM_BASE <= ptr < ROM_BASE + len(data), f"battle resource[{index}] pointer outside ROM")
    off = ptr - ROM_BASE
    width, height = data[off], data[off + 1]
    count = width * height
    gate(width > 0 and height > 0 and count <= 4096, f"battle resource[{index}] invalid dimensions")
    gate(off + 4 + count * 2 <= len(data), f"battle resource[{index}] map overruns ROM")
    cells = struct.unpack_from(f"<{count}H", data, off + 4)
    return {
        "index": index,
        "file_offset": f"0x{off:08X}",
        "address": f"0x{ptr:08X}",
        "width": width,
        "height": height,
        "tile_ids": [cell & 0x03FF for cell in cells],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rom", type=Path, default=JP_ROM)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    data = args.rom.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    gate(digest == EXPECTED_SHA256, f"unexpected Japanese ROM hash: {digest}")

    header = u32(data, BATTLE_ATLAS_RESOURCE)
    gate(header & 0x80000000, "battle atlas is not compressed")
    compressed_length = header & 0xFFFF
    battle_atlas = status.lzss_decompress(
        data[BATTLE_ATLAS_RESOURCE + 4 : BATTLE_ATLAS_RESOURCE + 4 + compressed_length]
    )
    gate(len(battle_atlas) == BATTLE_ATLAS_DECODED, f"battle atlas decoded size drift: {len(battle_atlas)}")
    gate(len(battle_atlas) % 32 == 0, "battle atlas is not 4bpp tile aligned")

    status_header = u32(data, status.ATLAS_RESOURCE)
    status_atlas = status.lzss_decompress(
        data[status.ATLAS_RESOURCE + 4 : status.ATLAS_RESOURCE + 4 + (status_header & 0xFFFF)]
    )
    gate(len(status_atlas) == status.ATLAS_EXPECTED_DECODED, "status atlas decoded size drift")

    resources: dict[str, object] = {}
    for index, (expected_off, expected_w, expected_h) in EXPECTED_RESOURCES.items():
        row = resource_map(data, index)
        gate(row is not None, f"battle resource[{index}] missing")
        gate(int(str(row["file_offset"]), 16) == expected_off, f"battle resource[{index}] offset drift")
        gate((row["width"], row["height"]) == (expected_w, expected_h), f"battle resource[{index}] dimension drift")
        # Atlas resource[0] is compressed data, not a conventional tilemap;
        # keep the header dimensions only as the original resource-table proof.
        resources[str(index)] = {
            key: value for key, value in row.items() if key != "tile_ids"
        } | ({"tile_ids": [f"0x{x:03X}" for x in row["tile_ids"]]} if index != 0 else {})

    gate(u32(data, BATTLE_RESOURCE_TABLE + 4) == 0, "battle resource[1] should be NULL")
    gate(u32(data, BATTLE_RESOURCE_TABLE + 17 * 4) == 0, "battle resource[17] should be NULL")
    for literal in TABLE_LITERAL_OFFSETS:
        gate(u32(data, literal) == TABLE_ADDRESS, f"battle table literal drift at 0x{literal:08X}")

    exact_status_tile_matches: dict[str, list[str]] = {}
    for tile_id in STATUS_PROBE_TILES:
        raw = status_atlas[tile_id * 32 : tile_id * 32 + 32]
        hits = [
            f"0x{candidate:03X}"
            for candidate in range(len(battle_atlas) // 32)
            if battle_atlas[candidate * 32 : candidate * 32 + 32] == raw
        ]
        if hits:
            exact_status_tile_matches[f"0x{tile_id:03X}"] = hits
    gate(not exact_status_tile_matches, f"unexpected byte-identical status tiles in battle atlas: {exact_status_tile_matches}")

    base = resource_map(data, 2)
    assert base is not None
    width = int(base["width"])
    cells = list(base["tile_ids"])
    weapon_rows = []
    for top in (6, 8, 10, 12):
        weapon_rows.append({
            "top_tile_y": top,
            "bottom_tile_y": top + 1,
            "top_tiles": [f"0x{x:03X}" for x in cells[top * width : (top + 1) * width]],
            "bottom_tiles": [f"0x{x:03X}" for x in cells[(top + 1) * width : (top + 2) * width]],
        })

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_battle_weapon_ui_tiles",
        "result": "PASS",
        "source": {"path": args.rom.name, "sha256": digest, "size": len(data)},
        "conclusion": {
            "status_and_battle_use_same_raw_tiles": False,
            "status_resource_table": f"0x{status.RESOURCE_TABLE:08X}",
            "status_atlas_resource": f"0x{status.ATLAS_RESOURCE:08X}",
            "battle_resource_table": f"0x{BATTLE_RESOURCE_TABLE:08X}",
            "battle_atlas_resource": f"0x{BATTLE_ATLAS_RESOURCE:08X}",
            "reason_battle_screen_stayed_japanese": "v8 redirected only the status atlas at 0x000E0518; battle rendering consumes the independent D54 family",
        },
        "battle_atlas": {
            "file_offset": f"0x{BATTLE_ATLAS_RESOURCE:08X}",
            "address": f"0x{ROM_BASE + BATTLE_ATLAS_RESOURCE:08X}",
            "compressed_body_length": compressed_length,
            "decoded_size": len(battle_atlas),
            "tile_count": len(battle_atlas) // 32,
            "tile_format": "GBA 4bpp 8x8",
        },
        "resource_table": {
            "file_offset": f"0x{BATTLE_RESOURCE_TABLE:08X}",
            "address": f"0x{TABLE_ADDRESS:08X}",
            "literal_file_offsets": [f"0x{x:08X}" for x in TABLE_LITERAL_OFFSETS],
            "resources": resources,
        },
        "runtime": {
            "main_renderer": "0x0801D09C",
            "base_map_draw": "resource[2] -> 0x0800269C",
            "dynamic_draw_helper_calls": ["0x08002310", "0x08002108", "0x0800269C"],
            "dynamic_resource_selection_region": "0x0801D2C0-0x0801D35A",
            "weapon_row_tile_pairs": weapon_rows,
        },
        "status_probe": {
            "tile_ids": [f"0x{x:03X}" for x in STATUS_PROBE_TILES],
            "byte_identical_matches_in_battle_atlas": exact_status_tile_matches,
            "result": "NONE",
        },
        "next_patch_scope": {
            "status_v9": "Galmuri9 small badges + 間->간 stays in E0518/DC848 family",
            "battle_followup": "identify the D54 equivalents by consumer/index and repaint the independent battle atlas without changing its dimensions or palette",
            "safety": "do not copy status tile IDs into D54; the IDs and palette layouts are unrelated",
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "out": str(args.out),
        "battle_atlas_decoded": len(battle_atlas),
        "battle_tile_count": len(battle_atlas) // 32,
        "exact_status_tile_matches": len(exact_status_tile_matches),
        "separate_battle_asset_family": True,
    }, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
