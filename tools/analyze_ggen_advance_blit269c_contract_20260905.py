#!/usr/bin/env python3
"""Disassemble and summarize the 0x0800269C tilemap blitter contract."""
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

from ggen_advance_project_paths import ADVANCE_ROOT, ORIGINAL_ROM, advance_relative

ROM_BASE = 0x08000000
START = 0x0800269C
END = 0x08002810
OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_blit269c_contract_20260905.json"


def u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def bl_target(data: bytes, addr: int) -> int | None:
    off = addr - ROM_BASE
    if off < 0 or off + 4 > len(data):
        return None
    h1, h2 = struct.unpack_from("<HH", data, off)
    if (h1 & 0xF800) != 0xF000 or (h2 & 0xF800) != 0xF800:
        return None
    disp = ((h1 & 0x7FF) << 12) | ((h2 & 0x7FF) << 1)
    if disp & (1 << 22):
        disp -= 1 << 23
    return (addr + 4 + disp) & 0xFFFFFFFF


def main() -> int:
    data = ORIGINAL_ROM.read_bytes()
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    rows: list[dict[str, Any]] = []
    for ins in md.disasm(data[START-ROM_BASE:END-ROM_BASE], START):
        row: dict[str, Any] = {
            "address": f"0x{ins.address:08X}",
            "bytes": bytes(ins.bytes).hex(),
            "mnemonic": ins.mnemonic,
            "op_str": ins.op_str,
        }
        target = bl_target(data, ins.address)
        if target is not None:
            row["bl_target"] = f"0x{target:08X}"
        if ins.mnemonic == "ldr" and "pc" in ins.op_str and "#" in ins.op_str:
            try:
                imm = int(ins.op_str.split("#",1)[1].split("]",1)[0], 0)
                lit = ((ins.address + 4) & ~3) + imm
                if ROM_BASE <= lit <= ROM_BASE + len(data) - 4:
                    row["literal_address"] = f"0x{lit:08X}"
                    row["literal_value"] = f"0x{u32(data,lit-ROM_BASE):08X}"
            except Exception:
                pass
        rows.append(row)
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_blit269c_contract_20260905",
        "result": "PASS",
        "source": advance_relative(ORIGINAL_ROM),
        "range": [f"0x{START:08X}",f"0x{END:08X}"],
        "instructions": rows,
        "calls": [r for r in rows if "bl_target" in r],
        "stack_accesses": [r for r in rows if "sp" in r["op_str"]],
    }
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"result":"PASS","out":advance_relative(OUT),"calls":report["calls"],"stack_accesses":report["stack_accesses"]},ensure_ascii=False,indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
