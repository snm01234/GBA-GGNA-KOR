#!/usr/bin/env python3
"""Read-only source mapping for the green intermission submenu OBJ rows."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt

ROM = ROOT / "SD Gundam GGeneration Advance (Korean).gba"
STATES = [ROOT / f"SD Gundam GGeneration Advance (Korean).ss{i}" for i in (1, 2, 3)]
OUT = ROOT / "analysis" / "ggen_advance_intermission_submenu_states_20260830.json"
PACKAGE = 0x00C512B8
ATLAS_START = 0x00C533C8
ATLAS_END = 0x00C54A48
LABELS = {
    1: ["작전", "색적", "진격", "세이브", "로드"],
    2: ["배속", "보급", "일람", "세이브", "로드"],
    3: ["개조", "분해", "설계도", "세이브", "로드"],
}


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def row_objects(state: bytes) -> list[list[dict]]:
    oam = state[statefmt.STATE_OAM:statefmt.STATE_VRAM]
    entries = [statefmt.parse_oam_entry(oam, i) for i in range(128)]
    groups = []
    for y in (50, 67, 84, 101, 118):
        rows = [e for e in entries if e["index"] >= 22 and e["x"] >= 150 and e["y"] == y]
        rows.sort(key=lambda e: e["x"])
        gate(rows, f"submenu row y={y} missing")
        groups.append(rows)
    return groups


def object_tiles(entry: dict) -> list[int]:
    cols, rows = entry["width"] // 8, entry["height"] // 8
    return [entry["tile"] + y * cols + x for y in range(rows) for x in range(cols)]


def ordered_row_tiles(entries: list[dict]) -> list[int]:
    x0 = min(entry["x"] for entry in entries)
    positions = {}
    for entry in entries:
        cols, rows = entry["width"] // 8, entry["height"] // 8
        for y in range(rows):
            for x in range(cols):
                positions[((entry["x"] - x0) // 8 + x, y)] = entry["tile"] + y * cols + x
    return [positions[(x, y)] for y in range(2) for x in range((max(entry["x"] + entry["width"] for entry in entries) - x0) // 8)]


def map_windows(rom: bytes, atlas: bytes, raws: list[bytes]) -> list[dict]:
    hits = []
    for off in range(PACKAGE, ATLAS_START - len(raws) * 2 + 1, 2):
        ids = [int.from_bytes(rom[off + i * 2:off + i * 2 + 2], "little") for i in range(len(raws))]
        if any(tile >= 180 for tile in ids):
            continue
        if all(atlas[tile * 32:(tile + 1) * 32] == raw for tile, raw in zip(ids, raws)):
            hits.append({"file_offset": f"0x{off:08X}", "source_tiles": [f"0x{x:03X}" for x in ids]})
    return hits


def main() -> int:
    rom = ROM.read_bytes()
    atlas = rom[ATLAS_START:ATLAS_END]
    gate(len(atlas) == 180 * 32, "C512B8 atlas size drift")
    states = [statefmt.parse_png_state(path)[0] for path in STATES]
    reports = []
    for number, state in enumerate(states, 1):
        obj = state[statefmt.STATE_VRAM + statefmt.OBJ_VRAM:statefmt.STATE_IWRAM]
        rows_report = []
        for row_index, entries in enumerate(row_objects(state)):
            items = []
            source_union = set()
            for entry in entries:
                for tile in object_tiles(entry):
                    raw = bytes(obj[tile * 32:(tile + 1) * 32])
                    hits = [source for source in range(180) if atlas[source * 32:(source + 1) * 32] == raw]
                    source_union.update(hits)
                    items.append({"obj_tile": f"0x{tile:03X}", "source_tiles": [f"0x{x:03X}" for x in hits],
                                  "nonblank": len(set(raw)) > 1})
            x0 = min(e["x"] for e in entries)
            x1 = max(e["x"] + e["width"] for e in entries)
            ordered_tiles = ordered_row_tiles(entries)
            resource_tiles = [tile for entry in entries for tile in object_tiles(entry)]
            resource_raws = [bytes(obj[tile * 32:(tile + 1) * 32]) for tile in resource_tiles]
            windows = map_windows(rom, atlas, resource_raws)
            rows_report.append({"row": row_index, "target": LABELS[number][row_index], "screen_x": x0,
                                "screen_y": entries[0]["y"], "width": x1 - x0, "height": 16,
                                "palette_bank": entries[0]["palette_bank"],
                                "oam_indices": [e["index"] for e in entries],
                                "obj_tiles": items, "ordered_obj_tiles": [f"0x{x:03X}" for x in ordered_tiles],
                                "resource_obj_tiles": [f"0x{x:03X}" for x in resource_tiles],
                                "source_union": [f"0x{x:03X}" for x in sorted(source_union)],
                                "tilemap_windows": windows})
        reports.append({"state": number, "rows": rows_report})

    report = {"schema_version": 1, "kind": "ggen_advance_intermission_submenu_states_20260830", "result": "PASS",
              "rom": {"path": ROM.name, "sha256": hashlib.sha256(rom).hexdigest()},
              "package": {"pointer": "0x08C512B8", "file_offset": f"0x{PACKAGE:08X}",
                          "raw_atlas": [f"0x{ATLAS_START:08X}", f"0x{ATLAS_END:08X}"], "tiles": 180},
              "states": reports, "scope": "read-only; no ROM bytes modified"}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "out": str(OUT),
                      "rows": [[{"target": row["target"], "width": row["width"],
                                 "palette": row["palette_bank"], "sources": len(row["source_union"])}
                                for row in state["rows"]] for state in reports]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
