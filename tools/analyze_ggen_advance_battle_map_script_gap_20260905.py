#!/usr/bin/env python3
"""Audit whether reported Japanese battle lines are missing from sheets or from live apply."""
from __future__ import annotations

import json
import struct
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from ggen_advance_project_paths import MAIN_TIP_ROM, ORIGINAL_ROM, TRANSLATION_MERGED_JSON
from patch_ggen_advance_map_script_inline_poc import (
    DRAW_CA8,
    MAX_DIALOGUE_CELLS,
    ORIGINAL_DRAW_CA8,
    ORIGINAL_PARSER_ENTRY,
    ORIGINAL_PARSER_EXIT,
    PARSER_ENTRY,
    PARSER_EXIT,
    encode_map_korean_line,
    load_identified_12x12,
)

ROM_BASE = 0x08000000
OUT = ROOT / "analysis" / "ggen_advance_battle_map_script_gap_20260905.json"

TARGETS = {
    "kira_feelings": "思いだけでも……",
    "kira_power": "力だけでもダメだけど……",
    "kira_still": "それでも！",
    "kira_world": "守りたい世界があるんだっ！",
    "amuro_nu": "νガンダムはダテじゃない！",
}

TARGET_RECORD_IDS = {
    "GGA-MAPSCRIPT-00F54687",
    "GGA-MAPSCRIPT-00F546AC",
    "GGA-MAPSCRIPT-00F546CF",
    "GGA-MAPSCRIPT-00F546F4",
    "GGA-MAPSCRIPT-00F5477B",
    "GGA-MAPSCRIPT-00FB3076",
    "GGA-IDBARK-00223F9C",
    "GGA-IDBARK-00223FA6",
    "GGA-IDBARK-00223520",
}


def parse_hex(value: str) -> int:
    return int(value, 16)


def read_u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def trampoline_target(data: bytes, offset: int) -> int | None:
    # ldr rX, [pc, #0]; bx rX; .word dest|1
    if data[offset + 1] != 0x48 and data[offset + 1] != 0x4B and (data[offset] & 0xF8) != 0x00:
        pass
    half0, half1, word = struct.unpack_from("<HHI", data, offset)
    if (half0 & 0xF800) != 0x4800:
        return None
    if (half1 & 0xFF87) != 0x4700:
        return None
    return word & ~1


def load_lookup(rom: bytes, table_addr: int, count: int) -> dict[int, tuple[int, int]]:
    table_off = table_addr - ROM_BASE
    lookup: dict[int, tuple[int, int]] = {}
    for i in range(count):
        orig, neu, end = struct.unpack_from("<III", rom, table_off + i * 12)
        lookup[orig] = (neu, end)
    return lookup


def find_hook_table(rom: bytes) -> dict[str, int] | None:
    entry = trampoline_target(rom, PARSER_ENTRY)
    if entry is None:
        return None
    off = entry - ROM_BASE
    # Hook blob is small; scan for aligned words that look like table/count.
    # After code, words: table, count, cont118c, contca0
    for rel in range(0, 0xC0, 2):
        pos = off + rel
        if pos + 16 > len(rom) or pos & 3:
            continue
        table, count, cont118c, contca0 = struct.unpack_from("<IIII", rom, pos)
        if count < 1000 or count > 40000:
            continue
        if (cont118c & ~1) != (ROM_BASE + 0x11AE):
            continue
        if (contca0 & ~1) != (ROM_BASE + DRAW_CA8 + 8):
            continue
        if not (ROM_BASE + 0x01000000 <= table < ROM_BASE + 0x02000000):
            continue
        return {
            "entry_thumb": entry,
            "table_address": table,
            "count": count,
            "cont118c": cont118c,
            "contca0": contca0,
            "word_offset": pos,
        }
    return None


def decode_source(row: dict) -> str:
    return str(row.get("source_text") or "").replace("\\n", "\n")


def main() -> None:
    rom = MAIN_TIP_ROM.read_bytes()
    japan = ORIGINAL_ROM.read_bytes()
    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    records = merged["records"] if isinstance(merged, dict) else merged
    identified = load_identified_12x12()

    hook_sites = {
        "parser_entry_is_original": rom[PARSER_ENTRY : PARSER_ENTRY + 8] == ORIGINAL_PARSER_ENTRY,
        "parser_exit_is_original": rom[PARSER_EXIT : PARSER_EXIT + 8] == ORIGINAL_PARSER_EXIT,
        "draw_ca8_is_original": rom[DRAW_CA8 : DRAW_CA8 + 8] == ORIGINAL_DRAW_CA8,
        "parser_entry_bytes": rom[PARSER_ENTRY : PARSER_ENTRY + 8].hex(" "),
        "parser_exit_bytes": rom[PARSER_EXIT : PARSER_EXIT + 8].hex(" "),
        "draw_ca8_bytes": rom[DRAW_CA8 : DRAW_CA8 + 8].hex(" "),
        "parser_entry_target": None if trampoline_target(rom, PARSER_ENTRY) is None else f"0x{trampoline_target(rom, PARSER_ENTRY):08X}",
        "parser_exit_target": None if trampoline_target(rom, PARSER_EXIT) is None else f"0x{trampoline_target(rom, PARSER_EXIT):08X}",
        "draw_ca8_target": None if trampoline_target(rom, DRAW_CA8) is None else f"0x{trampoline_target(rom, DRAW_CA8):08X}",
    }

    hook_meta = find_hook_table(rom)
    lookup: dict[int, tuple[int, int]] = {}
    if hook_meta:
        lookup = load_lookup(rom, hook_meta["table_address"], hook_meta["count"])

    target_rows = []
    map_ready = 0
    map_missing_lookup = []
    map_overlong = []
    map_encode_fail = []
    idbark_hits = []
    battle_event_hits = []
    other_hits = []

    hangul_slots = {}  # not reconstructing apply-charmap; length/lookup only

    for row in records:
        rid = str(row.get("record_id") or "")
        src = decode_source(row)
        scope = row.get("source_scope")
        matched = [name for name, needle in TARGETS.items() if needle in src.replace("\n", "\\n") or needle in src]
        if rid in TARGET_RECORD_IDS or matched:
            segs = []
            cursor = parse_hex(str(row.get("target_file_offset") or "0"))
            translations = list(row.get("translation_segments") or [])
            segments = list(row.get("segments") or [])
            for i, segment in enumerate(segments):
                raw = bytes.fromhex(str(segment.get("raw_hex") or "").replace(" ", ""))
                orig = ROM_BASE + cursor
                live = rom[cursor : cursor + len(raw)] if 0 <= cursor < len(rom) else b""
                japan_bytes = japan[cursor : cursor + len(raw)] if 0 <= cursor < len(japan) else b""
                ko = translations[i] if i < len(translations) else ""
                segs.append(
                    {
                        "index": i,
                        "source_text": segment.get("source_text"),
                        "translation": ko,
                        "orig_address": f"0x{orig:08X}",
                        "in_lookup": orig in lookup,
                        "lookup_dest": None if orig not in lookup else f"0x{lookup[orig][0]:08X}",
                        "live_matches_sheet_raw": live == raw,
                        "live_matches_japan": live == japan_bytes,
                        "len_cells": len(ko),
                        "overlong": len(ko) > MAX_DIALOGUE_CELLS,
                    }
                )
                cursor += len(raw)
            opcode = str(row.get("opcode_18_file_offset") or "")
            opcode_addr = (ROM_BASE + parse_hex(opcode)) if opcode else None
            target_rows.append(
                {
                    "record_id": rid,
                    "source_scope": scope,
                    "translation_status": row.get("translation_status"),
                    "translation_policy": row.get("translation_policy"),
                    "translation_ko": row.get("translation_ko"),
                    "source_text": row.get("source_text"),
                    "matched_needles": matched,
                    "speaker_id": row.get("speaker_id") or row.get("character_name_ko") or row.get("character_name"),
                    "opcode_18": opcode,
                    "opcode_in_lookup": None if opcode_addr is None else opcode_addr in lookup,
                    "segments": segs,
                }
            )

        if any(needle in src for needle in TARGETS.values()):
            bucket = {
                "record_id": rid,
                "source_scope": scope,
                "translation_status": row.get("translation_status"),
                "translation_ko": row.get("translation_ko"),
                "source_text": row.get("source_text"),
            }
            if scope == "id_command_battle_bark":
                idbark_hits.append(bucket)
            elif scope == "battle_event_dialogue":
                battle_event_hits.append(bucket)
            elif scope != "scenario_map_script":
                other_hits.append(bucket)

        if scope == "scenario_map_script" and row.get("scope_status") == "included":
            if row.get("translation_status") == "translated" and row.get("translation_policy") == "translate":
                map_ready += 1
                translations = list(row.get("translation_segments") or [])
                segments = list(row.get("segments") or [])
                cursor = parse_hex(str(row["target_file_offset"]))
                missing_here = []
                for i, segment in enumerate(segments):
                    raw = bytes.fromhex(str(segment.get("raw_hex") or "").replace(" ", ""))
                    orig = ROM_BASE + cursor
                    if orig not in lookup:
                        missing_here.append(f"0x{orig:08X}")
                    ko = translations[i] if i < len(translations) else ""
                    if len(ko) > MAX_DIALOGUE_CELLS:
                        map_overlong.append(
                            {
                                "record_id": rid,
                                "segment": i,
                                "len": len(ko),
                                "text": ko,
                            }
                        )
                    encoded, failed = encode_map_korean_line(ko, hangul_slots, identified)
                    if failed and "ν" not in failed:
                        # hangul_slots empty: Hangul will fail; only track identified-missing JP/special
                        special_fail = [ch for ch in failed if not ("가" <= ch <= "힣")]
                        if special_fail:
                            map_encode_fail.append({"record_id": rid, "failed": special_fail, "text": ko})
                    elif failed == [] and encoded is None:
                        pass
                    cursor += len(raw)
                if missing_here:
                    map_missing_lookup.append({"record_id": rid, "missing": missing_here})

    # Raw byte copies of the reported JP streams anywhere in ROM.
    patterns = {
        "kira_feelings_seg": bytes.fromhex("B4 1F 35 29 F0 17 07 07 00"),
        "kira_power_full": bytes.fromhex("DE 35 29 F0 17 76 8F 35 F0 A0 07 07 00"),
        "kira_still_seg": bytes.fromhex("F0 47 F0 17 05 00"),
        "kira_world_seg": bytes.fromhex("BA 52 34 1F F0 57 26 F0 31 58 35 37 05 00"),
        "amuro_nu_seg": bytes.fromhex("E0 63 F0 00 F0 02 42 F0 77 2E 4C 3D 1F 05 00"),
    }
    copies = {}
    for name, pat in patterns.items():
        hits = []
        start = 0
        while True:
            pos = rom.find(pat, start)
            if pos < 0:
                break
            hits.append(f"0x{pos:08X}")
            start = pos + 1
            if len(hits) >= 40:
                hits.append("truncated")
                break
        copies[name] = hits

    slot_01c2 = identified.get("界")
    slot_0143 = identified.get("ν")

    report = {
        "main_tip": str(MAIN_TIP_ROM),
        "main_size": len(rom),
        "hook_sites": hook_sites,
        "hook_table": None
        if hook_meta is None
        else {
            "entry_thumb": f"0x{hook_meta['entry_thumb']:08X}",
            "table_address": f"0x{hook_meta['table_address']:08X}",
            "count": hook_meta["count"],
        },
        "lookup_has_targets": {
            "0x08F54687": 0x08F54687 in lookup,
            "0x08F546AC": 0x08F546AC in lookup,
            "0x08F5477B": 0x08F5477B in lookup,
            "0x08F54686": 0x08F54686 in lookup,
            "0x08F546AB": 0x08F546AB in lookup,
            "0x08F5477A": 0x08F5477A in lookup,
            "0x08223F9C": 0x08223F9C in lookup,
            "0x08223520": 0x08223520 in lookup,
        },
        "target_rows": target_rows,
        "id_command_battle_bark_hits": idbark_hits,
        "battle_event_dialogue_hits": battle_event_hits,
        "other_scope_hits": other_hits,
        "map_script_ready_rows": map_ready,
        "map_script_ready_missing_from_live_lookup": len(map_missing_lookup),
        "map_script_missing_sample": map_missing_lookup[:20],
        "map_script_overlong": map_overlong[:20],
        "map_script_overlong_count": len(map_overlong),
        "raw_byte_copies_in_main_tip": copies,
        "identified_slots": {
            "界": None if slot_01c2 is None else f"0x{slot_01c2:04X}",
            "ν": None if slot_0143 is None else f"0x{slot_0143:04X}",
        },
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("hook_sites", "hook_table", "lookup_has_targets", "map_script_ready_rows", "map_script_ready_missing_from_live_lookup", "map_script_overlong_count")}, ensure_ascii=False, indent=2))
    print("target_rows", len(target_rows))
    print("idbark", len(idbark_hits), "battle_event", len(battle_event_hits), "other", len(other_hits))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
