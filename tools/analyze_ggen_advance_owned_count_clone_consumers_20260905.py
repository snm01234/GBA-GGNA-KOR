#!/usr/bin/env python3
"""Disassemble the three current-main 0x092D0000 clone consumer regions."""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path
from typing import Any

from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from ggen_advance_project_paths import ADVANCE_ROOT, MAIN_TIP_ROM, advance_relative

ROM_BASE = 0x08000000
CLONE = 0x092D0000
OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_owned_count_clone_consumers_20260905.json"
REGIONS = {
    "D570": (0x0806D480, 0x0806D5C0),
    "D81C": (0x0806D760, 0x0806D890),
    "EC9C": (0x0806EBD0, 0x0806ECE0),
    "helper_63CAC": (0x08063C60, 0x08063D30),
}


def u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def thumb_bl_target(data: bytes, address: int) -> int | None:
    off = address - ROM_BASE
    if off < 0 or off + 4 > len(data):
        return None
    h1, h2 = struct.unpack_from("<HH", data, off)
    if (h1 & 0xF800) != 0xF000 or (h2 & 0xF800) != 0xF800:
        return None
    disp = ((h1 & 0x07FF) << 12) | ((h2 & 0x07FF) << 1)
    if disp & (1 << 22):
        disp -= 1 << 23
    return (address + 4 + disp) & 0xFFFFFFFF


def disasm_region(data: bytes, start: int, end: int) -> list[dict[str, Any]]:
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    md.detail = False
    code = data[start - ROM_BASE:end - ROM_BASE]
    rows = []
    for ins in md.disasm(code, start):
        row: dict[str, Any] = {
            "address": f"0x{ins.address:08X}",
            "bytes": bytes(ins.bytes).hex(),
            "mnemonic": ins.mnemonic,
            "op_str": ins.op_str,
        }
        target = thumb_bl_target(data, ins.address)
        if target is not None:
            row["bl_target"] = f"0x{target:08X}"
        # Resolve simple Thumb PC-relative LDR literal when Capstone reports [pc,#imm].
        if ins.mnemonic == "ldr" and "pc" in ins.op_str and "#" in ins.op_str:
            try:
                imm_text = ins.op_str.split("#", 1)[1].split("]", 1)[0]
                imm = int(imm_text, 0)
                lit = ((ins.address + 4) & ~3) + imm
                if ROM_BASE <= lit <= ROM_BASE + len(data) - 4:
                    val = u32(data, lit - ROM_BASE)
                    row["literal_address"] = f"0x{lit:08X}"
                    row["literal_value"] = f"0x{val:08X}"
            except Exception:
                pass
        rows.append(row)
    return rows


def main() -> int:
    data = MAIN_TIP_ROM.read_bytes()
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_owned_count_clone_consumers_20260905",
        "result": "PASS",
        "source": advance_relative(MAIN_TIP_ROM),
        "clone": f"0x{CLONE:08X}",
        "regions": {},
    }
    for name, (start, end) in REGIONS.items():
        rows = disasm_region(data, start, end)
        clone_loads = [row for row in rows if row.get("literal_value") == f"0x{CLONE:08X}"]
        calls = [row for row in rows if "bl_target" in row]
        report["regions"][name] = {
            "range": [f"0x{start:08X}", f"0x{end:08X}"],
            "clone_loads": clone_loads,
            "calls": calls,
            "instructions": rows,
        }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "out": advance_relative(OUT),
        "summary": {
            name: {"clone_loads": row["clone_loads"], "calls": row["calls"]}
            for name, row in report["regions"].items()
        },
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
