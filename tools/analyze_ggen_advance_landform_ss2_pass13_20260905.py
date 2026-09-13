#!/usr/bin/env python3
"""Find consecutive 12x12 pointer tables that include 海, and IWRAM slot 0x01C1."""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
from ggen_advance_project_paths import ADVANCE_ROOT, ORIGINAL_ROM, TRANSLATION_MERGED_JSON
from ggen_advance_text_codec import (
    DICT_12X12_BASE,
    DICT_12X12_END,
    expand_to_slots,
    load_dictionary,
    read_tokens,
)

STATE = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).ss2"
CHARMAP12 = ADVANCE_ROOT / "analysis" / "ggen_advance_12x12_identified_charmap_20260828.json"
OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_landform_ss2_pass13_20260905.json"
ROM_BASE = 0x08000000


def u16(data, off):
    return struct.unpack_from("<H", data, off)[0]


def u32(data, off):
    return struct.unpack_from("<I", data, off)[0]


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    japan = ORIGINAL_ROM.read_bytes()
    state, _ = statefmt.parse_png_state(STATE)
    iwram = state[statefmt.STATE_IWRAM : statefmt.STATE_IWRAM + 0x8000]
    ewram = state[0x21000:0x61000]
    charmap = {int(k, 16): v for k, v in json.loads(CHARMAP12.read_text(encoding="utf-8"))["verified_charmap"].items()}
    dict12 = load_dictionary(japan, DICT_12X12_BASE, DICT_12X12_END)

    def decode_ptr(ptr):
        if not (ROM_BASE <= ptr < ROM_BASE + 0x01000000):
            return None
        off = ptr - ROM_BASE
        try:
            tokens, raw = read_tokens(japan, off, limit=48)
            if not (1 <= len(raw) <= 24):
                return None
            slots = expand_to_slots(tokens, dict12)
            if not (1 <= len(slots) <= 6):
                return None
            text = "".join(charmap.get(s, f"<{s:04X}>") for s in slots)
            if "<" in text and text.count("<") == len(slots):
                return None
            return {"text": text, "raw": raw.hex(), "offset": hex(off)}
        except Exception:
            return None

    tables = []
    off = 0
    while off < 0x01000000 - 16:
        decoded = decode_ptr(u32(japan, off))
        if not decoded:
            off += 4
            continue
        group = [decoded]
        n = 1
        while n < 64:
            nxt = decode_ptr(u32(japan, off + n * 4))
            if not nxt:
                break
            group.append(nxt)
            n += 1
        texts = [row["text"] for row in group]
        if n >= 6 and any("海" in t or t in {"海", "砂", "森", "街", "山", "空", "宇宙", "地上"} for t in texts):
            tables.append({"table": hex(off), "count": n, "texts": texts})
        off += 4 if n == 1 else n * 4

    slot_hits = {
        "iwram": [hex(h) for h in range(0, len(iwram) - 1, 2) if u16(iwram, h) == 0x01C1][:20],
        "ewram": [hex(h) for h in range(0, len(ewram) - 1, 2) if u16(ewram, h) == 0x01C1][:20],
    }
    token_hits = {
        "iwram": [hex(h) for h in range(0, len(iwram) - 1) if iwram[h : h + 2] == b"\xe0\xe1"][:20],
        "ewram": [hex(h) for h in range(0, len(ewram) - 1) if ewram[h : h + 2] == b"\xe0\xe1"][:20],
    }

    report = {"tables": tables, "slot_hits": slot_hits, "token_hits": token_hits}
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("tables", json.dumps(tables, ensure_ascii=False, indent=2)[:4000])
    print("slot", slot_hits)
    print("token", token_hits)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
