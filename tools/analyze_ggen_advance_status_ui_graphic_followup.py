#!/usr/bin/env python3
"""Audit the status UI atlas for additional fixed Japanese graphic labels.

The audit is intentionally read-only.  It proves the lower unit-status panel is
resource[40], inventories every referenced atlas tile, records the five measured
Japanese labels still visible after the first status-UI patch, and catches the
resource[64] collision that makes tile ids 0x1F3..0x1FA unavailable as scratch.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from collections import defaultdict
from pathlib import Path
from typing import Any

from ggen_advance_project_paths import ADVANCE_ROOT

ROM_BASE = 0x08000000
EXPECTED_SIZE = 16 * 1024 * 1024
EXPECTED_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"
DEFAULT_ROM = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Japan).gba"
DEFAULT_OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_status_ui_graphic_followup_20260829.json"
RESOURCE_TABLE = 0x000E0518
RESOURCE_COUNT = 69
ATLAS_TILE_COUNT = 16608 // 32
LOWER_PANEL_INDEX = 40
LOWER_PANEL_OFFSET = 0x000DFF9C
RESOURCE64_OFFSET = 0x000E04D8
ID_EFFECT_SHARED_RESOURCES = (16, 17, 18, 19)
ID_EFFECT_BODY_TOP = (0x0C3, 0x0C4, 0x0C5, 0x0C6)
ID_EFFECT_BODY_BOTTOM = (0x0CA, 0x0CB, 0x0CC, 0x0CD)
ID_EFFECT_SHARED_TAIL = (0x0C7, 0x0CE)
ID_EFFECT_SHARED_EDGE = (0x0C8, 0x0CF)
ID_EFFECT_RESOURCE40_TAIL = (0x173, 0x178)

LOWER_LABELS: dict[str, dict[str, Any]] = {
    "ID効果": {"ko": "ID효과", "x": 1, "y": 0, "w": 4, "h": 2},
    "攻撃": {"ko": "공격", "x": 0, "y": 2, "w": 4, "h": 2},
    "残り回数": {"ko": "남은횟수", "x": 18, "y": 2, "w": 7, "h": 2},
    "命中": {"ko": "명중", "x": 0, "y": 4, "w": 4, "h": 2},
    "回避": {"ko": "회피", "x": 0, "y": 6, "w": 4, "h": 2},
}


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def parse_map(data: bytes, index: int) -> dict[str, Any] | None:
    address = u32(data, RESOURCE_TABLE + index * 4)
    if not ROM_BASE <= address < ROM_BASE + EXPECTED_SIZE:
        return None
    offset = address - ROM_BASE
    if offset + 4 > len(data):
        return None
    width, height = data[offset], data[offset + 1]
    count = width * height
    if not width or not height or count > 1000 or offset + 4 + count * 2 > len(data):
        return None
    cells = list(struct.unpack_from(f"<{count}H", data, offset + 4))
    return {
        "index": index,
        "address": f"0x{address:08X}",
        "file_offset": f"0x{offset:08X}",
        "width": width,
        "height": height,
        "cells": cells,
    }


def region(tilemap: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    width = int(tilemap["width"])
    x0, y0, rw, rh = (int(spec[k]) for k in ("x", "y", "w", "h"))
    rows: list[list[str]] = []
    ids_flat: list[int] = []
    for y in range(y0, y0 + rh):
        row: list[str] = []
        for x in range(x0, x0 + rw):
            tile_id = int(tilemap["cells"][y * width + x]) & 0x03FF
            ids_flat.append(tile_id)
            row.append(f"0x{tile_id:03X}")
        rows.append(row)
    return {
        "ko_target": spec["ko"],
        "map_xy": [x0, y0],
        "size_tiles": [rw, rh],
        "size_pixels": [rw * 8, rh * 8],
        "tile_ids": rows,
        "tile_ids_flat": ids_flat,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    data = args.rom.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    gate(len(data) == EXPECTED_SIZE, f"unexpected ROM size: {len(data)}")
    gate(digest == EXPECTED_SHA256, f"unexpected Japanese ROM hash: {digest}")

    maps: list[dict[str, Any]] = []
    occurrences: dict[int, list[dict[str, int]]] = defaultdict(list)
    for index in range(RESOURCE_COUNT):
        row = parse_map(data, index)
        if row is None:
            continue
        maps.append(row)
        width = int(row["width"])
        for pos, cell in enumerate(row["cells"]):
            tile_id = int(cell) & 0x03FF
            occurrences[tile_id].append({"resource_index": index, "x": pos % width, "y": pos // width})

    used = set(occurrences)
    all_tiles = set(range(ATLAS_TILE_COUNT))
    gate(used == all_tiles, f"atlas tile-reference census drift: used={len(used)} total={len(all_tiles)}")

    lower = next((row for row in maps if row["index"] == LOWER_PANEL_INDEX), None)
    gate(lower is not None, "resource[40] missing")
    gate(lower["file_offset"] == f"0x{LOWER_PANEL_OFFSET:08X}", "resource[40] pointer drift")
    gate((lower["width"], lower["height"]) == (32, 8), "resource[40] is not 32x8")

    label_report: dict[str, Any] = {}
    for source, spec in LOWER_LABELS.items():
        info = region(lower, spec)
        unique_resource_indices = sorted({
            occ["resource_index"]
            for tile_id in info["tile_ids_flat"]
            for occ in occurrences[tile_id]
        })
        info["resource_indices_using_any_label_tile"] = unique_resource_indices
        info.pop("tile_ids_flat")
        label_report[source] = info

    id_resources = label_report["ID効果"]["resource_indices_using_any_label_tile"]
    gate(id_resources == [16, 17, 18, 19, 40], f"ID効果 sharing drift: {id_resources}")

    # The measured residual is not a 6x2 replacement target.  The Korean body
    # fits the shared 4x2 cells, while the last Japanese glyph spills one cell
    # farther right.  resource[40] uses 0x173/0x178 for that tail; resources
    # 16..19 use 0x0C7/0x0CE, followed by separate edge tiles 0x0C8/0x0CF.
    lower_cells = [int(v) & 0x03FF for v in lower["cells"]]
    lw = int(lower["width"])
    gate(tuple(lower_cells[1:5]) == ID_EFFECT_BODY_TOP, "resource40 ID effect top body drift")
    gate(tuple(lower_cells[lw + 1 : lw + 5]) == ID_EFFECT_BODY_BOTTOM, "resource40 ID effect bottom body drift")
    gate((lower_cells[5], lower_cells[lw + 5]) == ID_EFFECT_RESOURCE40_TAIL, "resource40 ID effect spill-tail drift")
    shared_tail_layout: dict[str, Any] = {}
    for index in ID_EFFECT_SHARED_RESOURCES:
        row = next((item for item in maps if item["index"] == index), None)
        gate(row is not None, f"resource[{index}] missing")
        cells = [int(v) & 0x03FF for v in row["cells"]]
        rw = int(row["width"])
        gate(tuple(cells[1:5]) == ID_EFFECT_BODY_TOP, f"resource[{index}] ID effect top body drift")
        gate(tuple(cells[rw + 1 : rw + 5]) == ID_EFFECT_BODY_BOTTOM, f"resource[{index}] ID effect bottom body drift")
        gate((cells[5], cells[rw + 5]) == ID_EFFECT_SHARED_TAIL, f"resource[{index}] ID effect shared tail drift")
        gate((cells[6], cells[rw + 6]) == ID_EFFECT_SHARED_EDGE, f"resource[{index}] ID effect edge drift")
        shared_tail_layout[str(index)] = {
            "body": [[f"0x{x:03X}" for x in ID_EFFECT_BODY_TOP], [f"0x{x:03X}" for x in ID_EFFECT_BODY_BOTTOM]],
            "spill_tail": [f"0x{x:03X}" for x in ID_EFFECT_SHARED_TAIL],
            "edge": [f"0x{x:03X}" for x in ID_EFFECT_SHARED_EDGE],
        }

    for source in ("攻撃", "残り回数", "命中", "回避"):
        gate(
            label_report[source]["resource_indices_using_any_label_tile"] == [40],
            f"{source} unexpectedly shares its tiles outside resource[40]",
        )

    resource64 = next((row for row in maps if row["index"] == 64), None)
    gate(resource64 is not None, "resource[64] missing")
    gate(resource64["file_offset"] == f"0x{RESOURCE64_OFFSET:08X}", "resource[64] pointer drift")
    gate((resource64["width"], resource64["height"]) == (4, 2), "resource[64] is not 4x2")
    resource64_ids = [int(cell) & 0x03FF for cell in resource64["cells"]]
    gate(resource64_ids == list(range(0x1F3, 0x1FB)), f"resource[64] tile ids drift: {resource64_ids}")

    word_chunks = [
        {
            "resource_index": row["index"],
            "file_offset": row["file_offset"],
            "size_tiles": [row["width"], row["height"]],
            "tile_id_min": f"0x{min(int(v) & 0x03FF for v in row['cells']):03X}",
            "tile_id_max": f"0x{max(int(v) & 0x03FF for v in row['cells']):03X}",
        }
        for row in maps
        if (row["width"], row["height"]) == (4, 2)
    ]

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_status_ui_graphic_followup",
        "result": "PASS",
        "source": {"path": args.rom.name, "size": len(data), "sha256": digest},
        "runtime_contract": {
            "resource_table_file_offset": f"0x{RESOURCE_TABLE:08X}",
            "lower_panel_resource_index": LOWER_PANEL_INDEX,
            "lower_panel_file_offset": f"0x{LOWER_PANEL_OFFSET:08X}",
            "lower_panel_renderer": "0x0806C934",
            "renderer_resource_offset": "+0xA0 (= index 40)",
            "tilemap_blitter": "0x0800277C",
        },
        "atlas_reference_census": {
            "atlas_tile_count": ATLAS_TILE_COUNT,
            "referenced_tile_count": len(used),
            "globally_unused_tile_count": len(all_tiles - used),
            "globally_unused_tile_ids": [],
            "conclusion": "all 519 decoded UI-atlas tiles are referenced by at least one resource",
        },
        "v3_collision_correction": {
            "incorrect_scratch_range": "0x1F3-0x1FA",
            "actual_owner_resource_index": 64,
            "actual_owner_file_offset": f"0x{RESOURCE64_OFFSET:08X}",
            "actual_owner_size_tiles": [4, 2],
            "tile_ids": [f"0x{x:03X}" for x in resource64_ids],
            "correct_policy": "restore original unit 移動 map and preserve resource[64]; exploit Korean 운동/이동 shared 동 tiles instead of allocating scratch ids",
        },
        "measured_lower_panel_labels": label_report,
        "id_effect_residual_structure": {
            "conclusion": "ID効果 main body is 4x2, but the final Japanese glyph spills into one extra cell; clear that spill cell without moving the Korean label or erasing the following panel edge",
            "resource40": {
                "body": [[f"0x{x:03X}" for x in ID_EFFECT_BODY_TOP], [f"0x{x:03X}" for x in ID_EFFECT_BODY_BOTTOM]],
                "spill_tail": [f"0x{x:03X}" for x in ID_EFFECT_RESOURCE40_TAIL],
                "policy": "restore 0x173/0x178 to native panel background",
            },
            "shared_resources_16_19": shared_tail_layout,
            "policy": "clear only glyph-bearing pixels in 0x0C7/0x0CE and preserve the panel-edge geometry plus 0x0C8/0x0CF byte-for-byte",
        },
        "similar_fixed_word_resources": {
            "four_by_two_chunks": word_chunks,
            "confirmed": {
                "resource_41": "汎用 -> 범용 (screen measured)",
                "resource_42": "宇宙 -> 우주 (glyph-shape match: 宇 0.821, 宙 0.956 using slot 0x04F2)",
                "resource_43": "地上 -> 지상 (glyph-shape match: 地 0.923, 上 0.725)",
                "resource_44": "万能 -> 만능 (glyph-shape match: 万 0.692, 能 0.981)",
                "resource_45": "水陸 -> 수륙 (glyph-shape match: 水 0.750, 陸 0.976)",
                "resource_46": "飛行 -> 비행 (glyph-shape match: 飛 0.903, 行 0.889)",
            },
            "pending_semantics": [47, 64, 65],
            "identification_method": "compare each 4x2 badge light-ink mask against the ROM's own identified 12x12 Japanese glyph bitmaps with +/-2px alignment search; unit-type selector 0x08005518 supplies resource_table[40+type]",
            "policy": "do not translate unmeasured chunks until their source meaning/runtime selector is proven",
        },
        "implementation_targets": {
            "ID効果": "ID효과 (8x16 condensed inside original 4x2 box)",
            "攻撃": "공격",
            "命中": "명중",
            "回避": "회피",
            "残り回数": "남은횟수",
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "out": str(args.out),
        "valid_resources": len(maps),
        "atlas_tiles": ATLAS_TILE_COUNT,
        "unused_tiles": 0,
        "lower_panel": f"0x{LOWER_PANEL_OFFSET:08X}",
        "labels": list(LOWER_LABELS),
        "resource64_collision_proven": True,
    }, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
