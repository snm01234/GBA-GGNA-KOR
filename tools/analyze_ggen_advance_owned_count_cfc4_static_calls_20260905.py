#!/usr/bin/env python3
"""Static call-context audit for 0x0806CFC4 initial unit-list construction."""
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
START = 0x0806CFC4
END = 0x0806D2A0
OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_owned_count_cfc4_static_calls_20260905.json"
TARGETS = {0x08000CA0: "CA0", 0x08000D10: "D10", 0x0800269C: "BLIT269C"}


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


def disasm(data: bytes) -> list[dict[str, Any]]:
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    rows = []
    code = data[START - ROM_BASE:END - ROM_BASE]
    for ins in md.disasm(code, START):
        row: dict[str, Any] = {
            "address": ins.address,
            "address_hex": f"0x{ins.address:08X}",
            "bytes": bytes(ins.bytes).hex(),
            "mnemonic": ins.mnemonic,
            "op_str": ins.op_str,
        }
        target = thumb_bl_target(data, ins.address)
        if target is not None:
            row["bl_target"] = target
            row["bl_target_hex"] = f"0x{target:08X}"
        if ins.mnemonic == "ldr" and "pc" in ins.op_str and "#" in ins.op_str:
            try:
                imm = int(ins.op_str.split("#", 1)[1].split("]", 1)[0], 0)
                lit = ((ins.address + 4) & ~3) + imm
                if ROM_BASE <= lit <= ROM_BASE + len(data) - 4:
                    row["literal_address"] = f"0x{lit:08X}"
                    row["literal_value"] = f"0x{u32(data, lit - ROM_BASE):08X}"
            except Exception:
                pass
        rows.append(row)
    return rows


def main() -> int:
    data = MAIN_TIP_ROM.read_bytes()
    rows = disasm(data)
    calls = []
    for i, row in enumerate(rows):
        target = row.get("bl_target")
        if target not in TARGETS:
            continue
        context = rows[max(0, i - 18):i + 1]
        calls.append({
            "kind": TARGETS[target],
            "callsite": row["address_hex"],
            "target": row["bl_target_hex"],
            "context": [{k: v for k, v in c.items() if k not in ("address", "bl_target")} for c in context],
        })
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_owned_count_cfc4_static_calls_20260905",
        "result": "PASS",
        "source": advance_relative(MAIN_TIP_ROM),
        "range": [f"0x{START:08X}", f"0x{END:08X}"],
        "calls": calls,
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "out": advance_relative(OUT),
        "calls": [{"kind": c["kind"], "callsite": c["callsite"], "context": c["context"][-10:]} for c in calls],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
