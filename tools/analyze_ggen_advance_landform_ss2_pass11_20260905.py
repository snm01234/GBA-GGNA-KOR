#!/usr/bin/env python3
"""Find a terrain-slot table containing 海=0x01C1 and bound LANDFORM sheet size."""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

from ggen_advance_project_paths import ADVANCE_ROOT, ORIGINAL_ROM, TRANSLATION_MERGED_JSON

CHARMAP12 = ADVANCE_ROOT / "analysis" / "ggen_advance_12x12_identified_charmap_20260828.json"
OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_landform_ss2_pass11_20260905.json"
GFX = 0x000E3154
ROM_BASE = 0x08000000


def u16(data, off):
    return struct.unpack_from("<H", data, off)[0]


def u32(data, off):
    return struct.unpack_from("<I", data, off)[0]


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    japan = ORIGINAL_ROM.read_bytes()
    cm = {int(k, 16): v for k, v in json.loads(CHARMAP12.read_text(encoding="utf-8"))["verified_charmap"].items()}
    rev = {}
    for slot, char in cm.items():
        rev.setdefault(char, slot)
    wanted = ["海", "砂", "森", "林", "街", "山", "空", "宙", "地", "上", "漠", "市", "宇宙", "地上", "砂漠", "森林", "市街", "山岳", "月", "面"]
    slots = {ch: hex(rev[ch]) for ch in wanted if ch in rev}
    sea = 0x01C1
    tables = []
    # Search aligned u16 arrays that contain 海 and at least two other terrain slots nearby.
    terrain_slots = {rev[ch] for ch in ("海", "砂", "森", "街", "山", "空", "宙", "地") if ch in rev}
    for off in range(0, 0x01000000 - 32, 2):
        if u16(japan, off) != sea:
            continue
        window = [u16(japan, off + i * 2) for i in range(-8, 12)]
        hits = [cm.get(value) for value in window if value in terrain_slots or cm.get(value) in {"海", "砂", "森", "林", "街", "山", "空", "宙", "地", "上", "漠", "市", "月"}]
        named = [(i - 8, hex(window[i]), cm.get(window[i])) for i in range(len(window)) if cm.get(window[i])]
        if len([1 for _, _, ch in named if ch]) >= 3:
            tables.append({"offset": hex(off), "named": named[:16]})
        if len(tables) >= 40:
            break

    # Bound sheet: consecutive 32-byte tiles until padding/other header
    used = 0
    for tile in range(200):
        raw = japan[GFX + tile * 32 : GFX + tile * 32 + 32]
        if raw == b"\x00" * 32:
            break
        used = tile + 1

    # Search merged records whose raw is a single 12x12 leftover that decodes to those kanji
    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    singles = []
    for row in merged["records"]:
        source = str(row.get("source_text") or "")
        raw = str(row.get("raw_hex") or "").replace(" ", "").upper()
        if source in {"海", "砂", "森", "街", "山", "空"} or raw in {"E0E100"}:
            singles.append(
                {
                    "record_id": row["record_id"],
                    "source_text": source,
                    "translation_ko": row.get("translation_ko"),
                    "status": row.get("translation_status"),
                    "raw_hex": row.get("raw_hex"),
                    "semantic_category": row.get("semantic_category"),
                    "owner_ids": row.get("owner_ids"),
                }
            )

    report = {
        "slots": slots,
        "tables": tables[:20],
        "sheet_used_tiles": used,
        "sheet_bytes": used * 32,
        "sheet_end": hex(GFX + used * 32),
        "single_records": singles,
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("slots", slots)
    print("tables", json.dumps(tables[:12], ensure_ascii=False, indent=2))
    print("sheet", used, report["sheet_end"])
    print("singles", json.dumps(singles, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
