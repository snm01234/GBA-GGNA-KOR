#!/usr/bin/env python3
"""Read 0x0801EC0C blit/text trace records from one or more savestates.

Each record is 0x20 bytes: count, r0, r1, r2, r3, stack0, stack1, stack2.
Reports executed sites by default and flags plaque-relevant destinations:
BG2 screenblock 29 (0x0600E800), charblock 2, and the measured 所有数 rectangle.
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
import build_ggen_advance_owned_count_ec0c_trace_candidate_20260904 as trace
from ggen_advance_project_paths import MAIN_TIP_ROM

ROM_BASE = 0x08000000
EWRAM_BASE = 0x02000000
SCREENBLOCK29 = 0x0600E800
CHARBLOCK2 = 0x06008000
PLAQUE_TILE = {"x0": 21, "y0": 8, "x1": 30, "y1": 12}
PLAQUE_PX = {"x0": 168, "y0": 64, "x1": 240, "y1": 96}


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def preview_bytes(data: bytes, max_len: int = 48) -> dict[str, Any]:
    raw = data[:max_len]
    stop = raw.find(b"\x00")
    prefix = raw if stop < 0 else raw[: stop + 1]
    printable = "".join(chr(b) if 0x20 <= b <= 0x7E else "." for b in prefix)
    return {
        "hex": prefix.hex(" ").upper(),
        "ascii": printable,
        "nul_terminated_within_preview": stop >= 0,
    }


def pointer_preview(pointer: int, rom: bytes, ewram: bytes) -> dict[str, Any] | None:
    if ROM_BASE <= pointer < ROM_BASE + len(rom):
        off = pointer - ROM_BASE
        w, h = rom[off], rom[off + 1]
        extra = {}
        if 1 <= w <= 64 and 1 <= h <= 32:
            extra = {"maybe_map_wh": [w, h]}
        return {"space": "ROM", "offset": f"0x{off:08X}", **preview_bytes(rom[off:off + 48]), **extra}
    if EWRAM_BASE <= pointer < EWRAM_BASE + len(ewram):
        off = pointer - EWRAM_BASE
        return {"space": "EWRAM", "offset": f"0x{off:08X}", **preview_bytes(ewram[off:off + 48])}
    if 0x06000000 <= pointer < 0x06018000:
        return {"space": "VRAM", "address": f"0x{pointer:08X}"}
    return {"space": "other", "address": f"0x{pointer:08X}"}


def plaque_relevant(kind: str, r0: int, r1: int, r2: int) -> list[str]:
    flags = []
    if SCREENBLOCK29 <= r0 < SCREENBLOCK29 + 0x800:
        flags.append("dest_screenblock29")
    if CHARBLOCK2 <= r0 < CHARBLOCK2 + 0x4000:
        flags.append("dest_charblock2")
    if kind.startswith("blit") and PLAQUE_TILE["y0"] <= (r2 & 0xFF) < PLAQUE_TILE["y1"]:
        flags.append("blit_y_in_plaque_tiles")
    if kind.startswith("text") and PLAQUE_PX["y0"] <= (r2 & 0xFFFF) < PLAQUE_PX["y1"]:
        flags.append("text_y_in_plaque_px")
    if kind.startswith("text") and PLAQUE_PX["x0"] <= (r1 & 0xFFFF) < PLAQUE_PX["x1"]:
        flags.append("text_x_in_plaque_px")
    if kind.startswith("blit") and PLAQUE_TILE["x0"] <= (r1 & 0xFF) < PLAQUE_TILE["x1"]:
        flags.append("blit_x_in_plaque_tiles")
    return flags


def parse_rows(ewram: bytes, rom: bytes, calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for spec in calls:
        address = int(spec["record"], 16)
        off = address - EWRAM_BASE
        values = struct.unpack_from("<8I", ewram, off)
        count, r0, r1, r2, r3, stack0, stack1, stack2 = values
        row = {
            "index": spec["index"],
            "name": spec["name"],
            "kind": spec["kind"],
            "callsite": spec["callsite"],
            "count": count,
            "r0": f"0x{r0:08X}",
            "r1": f"0x{r1:08X}",
            "r2": f"0x{r2:08X}",
            "r3": f"0x{r3:08X}",
            "stack0": f"0x{stack0:08X}",
            "stack1": f"0x{stack1:08X}",
            "stack2": f"0x{stack2:08X}",
        }
        if count:
            row["r0_preview"] = pointer_preview(r0, rom, ewram)
            row["r3_preview"] = pointer_preview(r3, rom, ewram)
            row["plaque_flags"] = plaque_relevant(spec["kind"], r0, r1, r2)
        rows.append(row)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("states", nargs="+", type=Path)
    ap.add_argument("--rom", type=Path, default=trace.OUT_ROM)
    ap.add_argument("--manifest", type=Path, default=trace.MANIFEST)
    ap.add_argument("--all", action="store_true", help="include zero-count calls")
    args = ap.parse_args()

    rom = args.rom.read_bytes()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    calls = manifest["calls"]
    reports = []
    prev = None
    for path in args.states:
        state, _chunks = statefmt.parse_png_state(path)
        ewram = state[0x21000:0x61000]
        rows = parse_rows(ewram, rom, calls)
        executed = [row for row in rows if row["count"] or args.all]
        plaque = [row for row in rows if row.get("plaque_flags")]
        delta = []
        if prev is not None:
            for old, new in zip(prev, rows):
                if new["count"] != old["count"]:
                    delta.append({
                        "name": new["name"],
                        "from": old["count"],
                        "to": new["count"],
                        "plaque_flags": new.get("plaque_flags", []),
                    })
        reports.append({
            "path": str(path),
            "executed": executed,
            "plaque_relevant": plaque,
            "delta_from_previous": delta,
            "executed_count": sum(1 for row in rows if row["count"]),
        })
        prev = rows

    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps({"result": "PASS", "states": reports}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
