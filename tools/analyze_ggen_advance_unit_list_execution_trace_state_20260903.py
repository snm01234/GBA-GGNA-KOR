#!/usr/bin/env python3
"""Read execution-trace counters from one or more mGBA/BizHawk .ss1 states.

The matching diagnostic ROM stores counters in EWRAM 0x0203D800..0x0203D9FF.
This analyzer reports lifecycle/transfer calls and normal/focus callback indices.
When multiple states are supplied, it also reports per-step deltas.
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
import build_ggen_advance_unit_list_execution_trace_candidate_20260903 as trace


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def state_counter(ewram: bytes, address: int) -> int:
    off = address - 0x02000000
    if off < 0 or off + 4 > len(ewram):
        raise SystemExit(f"counter outside EWRAM: 0x{address:08X}")
    return u32(ewram, off)


def load_one(path: Path) -> dict[str, Any]:
    state, chunks = statefmt.parse_png_state(path)
    ewram = state[0x21000:0x61000]
    direct = []
    for index, (name, site, target) in enumerate(trace.DIRECT_CALLS):
        address = trace.DIRECT_BASE + index * 4
        count = state_counter(ewram, address)
        direct.append({
            "index": index,
            "name": name,
            "callsite": f"0x{site:08X}",
            "original_target": f"0x{target:08X}",
            "counter_address": f"0x{address:08X}",
            "count": count,
        })

    callbacks: dict[str, list[dict[str, Any]]] = {"normal": [], "focus": []}
    for table_name, base, table_file in (
        ("normal", trace.NORMAL_BASE, trace.NORMAL_TABLE_FILE),
        ("focus", trace.FOCUS_BASE, trace.FOCUS_TABLE_FILE),
    ):
        for index in range(trace.CALLBACK_COUNT):
            address = base + index * 4
            count = state_counter(ewram, address)
            callbacks[table_name].append({
                "index": index,
                "counter_address": f"0x{address:08X}",
                "table_file": f"0x{table_file + index * 4:08X}",
                "count": count,
            })

    return {
        "path": str(path),
        "png_chunks": len(chunks),
        "direct": direct,
        "callbacks": callbacks,
        "nonzero": {
            "direct": [row for row in direct if row["count"]],
            "normal": [row for row in callbacks["normal"] if row["count"]],
            "focus": [row for row in callbacks["focus"] if row["count"]],
        },
    }


def delta_rows(previous: list[dict[str, Any]], current: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    out = []
    for a, b in zip(previous, current):
        delta = int(b["count"]) - int(a["count"])
        if delta:
            row = {key: b[key], "before": a["count"], "after": b["count"], "delta": delta}
            if "name" in b:
                row["name"] = b["name"]
            out.append(row)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("states", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    rows = [load_one(path) for path in args.states]
    deltas = []
    for previous, current in zip(rows, rows[1:]):
        deltas.append({
            "from": previous["path"],
            "to": current["path"],
            "direct": delta_rows(previous["direct"], current["direct"], "index"),
            "normal": delta_rows(previous["callbacks"]["normal"], current["callbacks"]["normal"], "index"),
            "focus": delta_rows(previous["callbacks"]["focus"], current["callbacks"]["focus"], "index"),
        })

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_unit_list_execution_trace_state_20260903",
        "result": "PASS",
        "trace_base": f"0x{trace.TRACE_BASE:08X}",
        "states": rows,
        "deltas": deltas,
        "interpretation_hints": {
            "all_zero": "The diagnostic screen path was not entered after a cold boot, or the state was captured from a different ROM.",
            "lifecycle_D3CA_to_D830": "Confirms the 0x0806D830 owner that contains the generic unit-list renderer.",
            "supply_anim8_D7A0_to_63CAC": "Confirms the same controller path that creates the user-approved 0x092D0000 bottom panel.",
            "unit_list_D86C_to_77818": "Confirms execution of the generic normal/focus list compositor from the D6xx controller.",
            "normal_focus_delta": "Move selection between rows and compare states; changed callback indices identify which normal/focus callback family actually renders the selected row.",
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
