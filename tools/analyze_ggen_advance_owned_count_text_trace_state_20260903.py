#!/usr/bin/env python3
"""Read 所有数 12x12 text-call trace records from diagnostic savestates.

The matching ROM records one 0x18-byte row per instrumented callsite:
count, r1(x), r2(y), r3(text/format pointer), stack0 and stack1.  This analyzer
reports only executed sites by default and previews pointer bytes from ROM or
EWRAM so the actual source format/string can be identified without guessing.
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
import build_ggen_advance_owned_count_text_trace_candidate_20260903 as trace

ROM = ROOT / "SD Gundam GGeneration Advance (Korean).gba"
ROM_BASE = 0x08000000
EWRAM_BASE = 0x02000000


def u32(data: bytes, off: int) -> int:
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
        return {"space": "ROM", "offset": f"0x{off:08X}", **preview_bytes(rom[off : off + 48])}
    if EWRAM_BASE <= pointer < EWRAM_BASE + len(ewram):
        off = pointer - EWRAM_BASE
        return {"space": "EWRAM", "offset": f"0x{off:08X}", **preview_bytes(ewram[off : off + 48])}
    return None


def load_state(path: Path, rom: bytes) -> dict[str, Any]:
    state, chunks = statefmt.parse_png_state(path)
    ewram = state[0x21000:0x61000]
    rows = []
    for index, (name, site, target) in enumerate(trace.CALLS):
        address = trace.TRACE_BASE + index * trace.RECORD_SIZE
        off = address - EWRAM_BASE
        values = struct.unpack_from("<6I", ewram, off)
        count, r1, r2, r3, stack0, stack1 = values
        row = {
            "index": index,
            "name": name,
            "renderer": trace.TARGET_NAMES[target],
            "callsite": f"0x{site:08X}",
            "record": f"0x{address:08X}",
            "count": count,
            "r1_x": r1,
            "r2_y": r2,
            "r3_text_or_format": f"0x{r3:08X}",
            "stack0": f"0x{stack0:08X}",
            "stack1": f"0x{stack1:08X}",
        }
        if count:
            row["r3_preview"] = pointer_preview(r3, rom, ewram)
            row["stack0_preview"] = pointer_preview(stack0, rom, ewram)
            row["stack1_preview"] = pointer_preview(stack1, rom, ewram)
        rows.append(row)
    nonzero = [row for row in rows if row["count"]]
    # Strong candidates are calls whose runtime origin is close to the measured
    # Japanese glyph origin x=177/y=74.  Coordinates may be panel-relative or
    # alignment-adjusted, so keep a generous 32px Manhattan window.
    nearby = []
    for row in nonzero:
        x, y = int(row["r1_x"]), int(row["r2_y"])
        distance = abs(x - 177) + abs(y - 74)
        if distance <= 32:
            nearby.append({**row, "distance_to_measured_origin": distance})
    nearby.sort(key=lambda row: (row["distance_to_measured_origin"], -int(row["count"]), row["index"]))
    return {
        "path": str(path),
        "png_chunks": len(chunks),
        "rows": rows,
        "nonzero": nonzero,
        "near_measured_owned_count": nearby,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("states", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    rom = ROM.read_bytes()
    states = [load_state(path, rom) for path in args.states]
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_owned_count_text_trace_state_20260903",
        "result": "PASS",
        "trace_base": f"0x{trace.TRACE_BASE:08X}",
        "record_size": trace.RECORD_SIZE,
        "measured_owned_count": {
            "text": "所有数",
            "glyph_origin": [177, 74],
            "glyph_extent": [177, 74, 212, 85],
            "interior_dice_vs_native_12x12": 0.9931506849315068,
        },
        "states": states,
        "interpretation": {
            "all_zero": "The instrumented renderer families were not entered after fresh boot, or the state belongs to another ROM.",
            "nearby": "Executed calls near x=177/y=74 are the first candidates for the 所有数 producer. Inspect r3/stack pointer previews to distinguish format strings, native text, and numeric varargs.",
            "next": "Once one callsite/source pointer is proven, patch that source/producer rather than writing final BG2 VRAM."
        },
    }
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
