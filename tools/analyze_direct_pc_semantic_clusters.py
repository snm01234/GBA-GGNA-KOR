#!/usr/bin/env python3
"""Promote high-confidence semantic clusters within the direct-PC literal family."""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

ROM_BASE = 0x08000000
EXPECTED_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"
EXPECTED_SIZE = 16 * 1024 * 1024


def u16(data: bytes, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def bl_target(data: bytes, off: int) -> int | None:
    hi, lo = struct.unpack_from("<HH", data, off)
    if hi & 0xF800 != 0xF000 or lo & 0xF800 != 0xF800:
        return None
    disp = ((hi & 0x7FF) << 12) | ((lo & 0x7FF) << 1)
    if disp & (1 << 22):
        disp -= 1 << 23
    return ROM_BASE + off + 4 + disp


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise SystemExit(f"gate failed: {msg}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("rom", type=Path)
    ap.add_argument("--direct-pc", type=Path, default=Path("legacy/analysis/direct_pc_literal_static_summary_20260826.json"))
    args = ap.parse_args()

    data = args.rom.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    check(len(data) == EXPECTED_SIZE, "ROM size drift")
    check(digest == EXPECTED_SHA256, f"ROM hash drift: {digest}")
    direct = json.loads(args.direct_pc.read_text(encoding="utf-8"))
    check(len(direct["targets"]) == 67, "direct-PC target count drift")

    target_calls: dict[int, list[int]] = {}
    for row in direct["targets"]:
        target = int(row["text_pointer_address"], 16)
        target_calls[target] = [int(x, 16) for x in row["call_sites"]]

    clusters: dict[str, set[int]] = {
        "unit_configuration_action_label": set(),
        "map_system_selector_static_label": set(),
        "map_system_selector_help": set(),
        "stage_battle_condition_static_label": set(),
        "id_command_fallback_text": set(),
        "generic_ui_symbol": set(),
    }
    for target, calls in target_calls.items():
        if any(0x0805F16A <= c <= 0x0805F25A for c in calls):
            clusters["unit_configuration_action_label"].add(target)
        if any(0x0806457E <= c <= 0x080645EE for c in calls):
            clusters["map_system_selector_static_label"].add(target)
        if any(0x080654FC <= c <= 0x08065562 for c in calls):
            clusters["map_system_selector_help"].add(target)
        if any(0x0806AF00 <= c <= 0x0806B500 or 0x08073300 <= c <= 0x08074400 for c in calls):
            clusters["stage_battle_condition_static_label"].add(target)
    clusters["id_command_fallback_text"] = {0x081BE746, 0x081BE7B4}
    clusters["generic_ui_symbol"] = {0x081BE755, 0x081BEA3C}

    expected_counts = {
        "unit_configuration_action_label": 18,
        "map_system_selector_static_label": 9,
        "map_system_selector_help": 8,
        "stage_battle_condition_static_label": 9,
        "id_command_fallback_text": 2,
        "generic_ui_symbol": 2,
    }
    check({k: len(v) for k, v in clusters.items()} == expected_counts, "semantic cluster count drift")

    # Unit configuration action menu: 18 visible action labels, 18-way dispatch, index 9 is proven AI type editor.
    check(bl_target(data, 0x0005F74E) == 0x0805F114, "configuration menu redraw call drift")
    check(u32(data, 0x0005F3E0) == 0x0805F5C8, "configuration switch index-9 drift")
    check(bl_target(data, 0x0005F5CA) == 0x08060410, "configuration index-9 AI editor drift")
    check(0x081BECF2 in clusters["unit_configuration_action_label"], "AI menu label missing from configuration cluster")

    # Map/system selector: fixed menu/static text and help text share the same module as FCE128 callback help.
    check(bl_target(data, 0x000643DE) == 0x08064D38, "map/system selector index mapping drift")
    check(u32(data, 0x000643F4) == 0x08D58D0C, "map/system callback registry drift")
    check(bl_target(data, 0x0006540E) == 0x08064D38, "map/system help index mapping drift")
    check(u32(data, 0x00065454) == 0x08FCE128, "FCE128 help table literal drift")

    # Stage-condition anchors already closed by dedicated analyzers.
    check(u32(data, 0x00073B70) == 0x08FCE2D8, "stage-condition table anchor drift")
    check(bl_target(data, 0x000736D2) == 0x08073A04, "stage-condition mode0 renderer drift")
    check(bl_target(data, 0x000736F6) == 0x08073D14, "stage-condition mode1 renderer drift")

    # ID-command fallback paths: inactive slot label and empty description fallback.
    check(bl_target(data, 0x0006D1E2) == 0x08000CA0, "ID-command empty-slot draw drift")
    check(bl_target(data, 0x0001FC86) == 0x08000CA0 and bl_target(data, 0x0003ABF6) == 0x08000CA0, "ID-command description fallback draw drift")

    # Common glyphs proven from font bitmap: horizontal dash and right-pointing chevron.
    check(target_calls[0x081BE755], "dash target lost all direct callsites")
    check(target_calls[0x081BEA3C], "chevron target lost all direct callsites")

    union = set().union(*clusters.values())
    check(len(union) == 46, f"promotion union drift: {len(union)}")
    previously_reviewed_overlap = union & {0x081BEB58, 0x081BE8C4}
    check(not previously_reviewed_overlap, f"unexpected overlap with already-promoted direct targets: {previously_reviewed_overlap}")
    remaining = set(target_calls) - union - {0x081BEB58, 0x081BE8C4}
    check(len(remaining) == 19, f"remaining direct-PC target count drift: {len(remaining)}")

    report = {
        "schema_version": 1,
        "rom_sha256": digest,
        "semantic_review_status": "reviewed for listed clusters",
        "clusters": {
            name: {
                "records": len(values),
                "targets": [f"0x{x:08X}" for x in sorted(values)],
            }
            for name, values in clusters.items()
        },
        "promotion": {
            "unique_records_promoted": len(union),
            "previously_promoted_direct_targets_excluded": ["0x081BEB58", "0x081BE8C4"],
            "direct_pc_records_remaining_partial": len(remaining),
            "remaining_targets": [f"0x{x:08X}" for x in sorted(remaining)],
        },
        "conclusion": "46 direct-PC identities belong to already-closed UI domains or font-proven common symbols. Only 19 direct-PC identities remain semantically partial."
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
