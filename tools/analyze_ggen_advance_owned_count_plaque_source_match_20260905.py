#!/usr/bin/env python3
"""Match live BG2 所有数 plaque tiles against sprite-resource source tiles.

This closes the possibility that a resource is only used as a source package
whose graphics are copied into BG char memory rather than remaining visible OBJ.
"""
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_develop_menu_buttons_state_20260901 as dev
import analyze_ggen_advance_jp_ko_ss1_n_tile_owned_count_20260903 as owned
import analyze_ggen_advance_owned_count_resource_bind_20260905 as bind
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
from ggen_advance_project_paths import ADVANCE_ROOT, ORIGINAL_ROM, advance_relative

JP_STATE = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Japan).ss1"
OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_owned_count_plaque_source_match_20260905.json"
TARGET_RESOURCE = 0x08C4654C
TARGET_ANIMATION = 8


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def source_tiles_for_animation(rom: bytes, resource: int, animation: int) -> dict[str, Any] | None:
    try:
        header = dev.parse_resource_header(rom, resource)
        _graphics_rel, records = dev.sprite.animation_records(rom, resource)
        parsed, ids = dev.parse_animation(records, animation)
    except (SystemExit, ValueError, IndexError):
        return None
    graphics = header["graphics"]
    raw = {sid: bytes(graphics[sid * 32:(sid + 1) * 32]) for sid in sorted(set(ids)) if sid < header["source_tiles"]}
    return {
        "resource": f"0x{resource:08X}",
        "animation": animation,
        "source_ids": ids,
        "unique_source_ids": sorted(raw),
        "tiles": raw,
        "object_count": len(parsed["objects"]),
    }


def plaque_payloads(state: bytes) -> tuple[dict[str, Any], dict[int, bytes]]:
    plaque = owned.plaque_scan(state)
    if not plaque.get("found"):
        raise SystemExit("gate failed: live BG2 plaque not found")
    tiles: dict[int, bytes] = {}
    for row in plaque["map"]:
        for cell in row:
            tid = int(cell["tile"])
            tiles[tid] = owned.bg_tile_bytes(state, 2, tid)
    return plaque, tiles


def compare(src: dict[str, Any], plaque: dict[int, bytes]) -> dict[str, Any]:
    reverse: dict[bytes, list[int]] = {}
    for tid, raw in plaque.items():
        reverse.setdefault(raw, []).append(tid)
    matches = []
    for sid, raw in src["tiles"].items():
        if raw in reverse:
            matches.append({"source_id": sid, "plaque_tile_ids": reverse[raw], "sha256": sha256(raw)})
    occurrence_hits = sum(1 for sid in src["source_ids"] if sid in {m["source_id"] for m in matches})
    return {
        "resource": src["resource"],
        "animation": src["animation"],
        "object_count": src["object_count"],
        "source_occurrences": len(src["source_ids"]),
        "unique_source_tiles": len(src["unique_source_ids"]),
        "exact_unique_tile_matches": len(matches),
        "exact_source_occurrence_matches": occurrence_hits,
        "matches": matches,
    }


def main() -> int:
    rom = ORIGINAL_ROM.read_bytes()
    state, _ = statefmt.parse_png_state(JP_STATE)
    plaque, live_tiles = plaque_payloads(state)
    slots = bind.sprite_slots(state)

    cases: list[tuple[int, int, str]] = [(TARGET_RESOURCE, TARGET_ANIMATION, "priority_target")]
    for slot in slots:
        resource = int(slot["resource"], 16)
        animation = int(slot["animation"])
        key = (resource, animation)
        if all((r, a) != key for r, a, _label in cases):
            cases.append((resource, animation, f"live_slot_{slot['slot']}"))

    rows = []
    failures = []
    for resource, animation, label in cases:
        src = source_tiles_for_animation(rom, resource, animation)
        if src is None:
            failures.append({"label": label, "resource": f"0x{resource:08X}", "animation": animation})
            continue
        row = compare(src, live_tiles)
        row["label"] = label
        rows.append(row)
    rows.sort(key=lambda row: (row["exact_source_occurrence_matches"], row["exact_unique_tile_matches"]), reverse=True)

    target = next(row for row in rows if row["resource"] == f"0x{TARGET_RESOURCE:08X}" and row["animation"] == TARGET_ANIMATION)
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_owned_count_plaque_source_match_20260905",
        "result": "PASS",
        "source": {"rom": advance_relative(ORIGINAL_ROM), "state": advance_relative(JP_STATE)},
        "plaque": plaque,
        "plaque_unique_tile_count": len(live_tiles),
        "priority_target": target,
        "live_resource_animation_matches": rows,
        "parse_failures": failures,
        "conclusion": (
            "Priority target has no exact raw-tile provenance into the live BG2 plaque."
            if target["exact_unique_tile_matches"] == 0 else
            "Priority target shares exact raw tile payloads with the live BG2 plaque and remains a possible indirect source."
        ),
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "out": advance_relative(OUT),
        "plaque": {k: plaque[k] for k in ("bg2cnt", "screen_vram", "x0", "y0", "width", "height", "unique_tiles")},
        "priority_target": target,
        "top_live_matches": rows[:20],
        "parse_failures": failures,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
