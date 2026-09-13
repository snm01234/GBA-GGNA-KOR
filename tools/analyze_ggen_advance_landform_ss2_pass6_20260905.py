#!/usr/bin/env python3
"""Match LANDFORM 回避 to UI atlases and recover the 海 name table."""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

import analyze_ggen_advance_fixed_word_semantics_20260830 as sem
import analyze_ggen_advance_intermission_cycle_states_20260830 as bg
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
from analyze_ggen_advance_action_graphics_scan_20260830 import lzss_decompress
from ggen_advance_project_paths import ADVANCE_ROOT, MAIN_TIP_ROM, ORIGINAL_ROM, TRANSLATION_MERGED_JSON
from ggen_advance_text_codec import read_tokens, expand_to_slots, load_dictionary, DICT_12X12_BASE, DICT_12X12_END

STATE = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).ss2"
OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_landform_ss2_pass6_20260905.json"
CHARMAP12 = ADVANCE_ROOT / "analysis" / "ggen_advance_12x12_identified_charmap_20260828.json"
ROM_BASE = 0x08000000
FAMILIES = sem.FAMILIES
SEA_TOKEN = bytes.fromhex("E0 E1 00")


def u32(data, off):
    return struct.unpack_from("<I", data, off)[0]


def decode_atlas(rom, table):
    ptr = u32(rom, table)
    off = ptr - ROM_BASE
    header = u32(rom, off)
    if header & 0x80000000:
        return lzss_decompress(rom[off + 4 : off + 4 + (header & 0xFFFF)])
    return None


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    japan = ORIGINAL_ROM.read_bytes()
    rom = MAIN_TIP_ROM.read_bytes()
    state, _ = statefmt.parse_png_state(STATE)
    vram = state[statefmt.STATE_VRAM : statefmt.STATE_IWRAM]
    evade = [bytes(vram[tid * 32 : tid * 32 + 32]) for tid in (806, 807, 808, 809, 822, 823, 824, 825)]
    family_hits = {}
    for name, spec in FAMILIES.items():
        atlas = decode_atlas(japan, spec["table"])
        if atlas is None:
            family_hits[name] = {"atlas": None}
            continue
        lookup = {}
        for tile in range(len(atlas) // 32):
            lookup.setdefault(bytes(atlas[tile * 32 : tile * 32 + 32]), []).append(tile)
        matched = []
        for index, raw in enumerate(evade):
            matched.append({"live_index": index, "atlas_tiles": lookup.get(raw, [])})
        family_hits[name] = {
            "atlas_tiles": len(atlas) // 32,
            "matched": matched,
            "hit_count": sum(1 for row in matched if row["atlas_tiles"]),
        }
        # 4x2 maps scoring 回避 tile set
        maps = []
        for idx in range(spec["max_entries"]):
            parsed = sem.parse_map(japan, u32(japan, spec["table"] + idx * 4))
            if not parsed or parsed["width"] != 4 or parsed["height"] != 2:
                continue
            tiles = [c & 0x3FF for c in parsed["cells"]]
            maps.append({"index": idx, "tiles": [hex(t) for t in tiles]})
        family_hits[name]["maps_4x2"] = maps

    charmap = {int(k, 16): v for k, v in json.loads(CHARMAP12.read_text(encoding="utf-8"))["verified_charmap"].items()}
    dict12 = load_dictionary(japan, DICT_12X12_BASE, DICT_12X12_END)

    def decode_payload(raw):
        try:
            tokens, _ = read_tokens(raw + b"\x00" if not raw.endswith(b"\x00") else raw, 0)
            slots = expand_to_slots(tokens, dict12)
        except Exception as exc:
            return {"error": str(exc)}
        text = "".join(charmap.get(slot, f"<{slot:04X}>") for slot in slots)
        return {"text": text, "slots": [hex(s) for s in slots]}

    table_rows = []
    start = 0
    while True:
        pos = japan.find(SEA_TOKEN, start)
        if pos < 0:
            break
        # collect neighbouring C-strings in a 0x80 window
        window = japan[max(0, pos - 64) : pos + 64]
        neighbors = []
        cursor = 0
        abs_base = max(0, pos - 64)
        while cursor < len(window):
            end = window.find(0, cursor)
            if end < 0:
                break
            raw = window[cursor : end + 1]
            if 2 <= len(raw) <= 24:
                decoded = decode_payload(raw)
                neighbors.append({"offset": hex(abs_base + cursor), "raw": raw.hex(), **decoded})
            cursor = end + 1
        table_rows.append({"hit": hex(pos), "neighbors": neighbors})
        start = pos + 1
        if len(table_rows) >= 24:
            break

    # pointer table: consecutive u32s pointing at short 12x12 names
    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    cats_pending = {}
    for row in merged["records"]:
        if row.get("translation_status") != "pending":
            continue
        cat = str(row.get("semantic_category") or "")
        cats_pending.setdefault(cat, 0)
        cats_pending[cat] += 1

    report = {
        "family_hits": family_hits,
        "sea_neighborhoods": table_rows[:8],
        "pending_by_category": dict(sorted(cats_pending.items(), key=lambda kv: -kv[1])[:30]),
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("family", {k: v.get("hit_count") for k, v in family_hits.items()})
    for name, spec in family_hits.items():
        if spec.get("hit_count"):
            print(name, spec["matched"])
    print("sea neighborhoods", len(table_rows))
    if table_rows:
        print(json.dumps(table_rows[0], ensure_ascii=False, indent=2)[:2000])
    print("pending cats", report["pending_by_category"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
