#!/usr/bin/env python3
"""Find screenshot Nimbus lines in map-script bank and live scenario payloads."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from analyze_ggen_advance_pending_decode import CORRECTED_LOW_KANA, load_map
from ggen_advance_project_paths import MAIN_TIP_ROM, ORIGINAL_ROM, TRANSLATION_MERGED_JSON
from ggen_advance_text_codec import (
    DICT_12X12_BASE,
    DICT_12X12_END,
    expand_to_slots,
    load_dictionary,
    read_tokens,
)
from patch_ggen_advance_intermission_text_consumers_20260904 import u32

ROM_BASE = 0x08000000
BANK_START = 0x00F00000
BANK_END = 0x00FC0000
MAP12 = ROOT / "analysis" / "ggen_advance_12x12_identified_charmap_20260828.json"
OUT = ROOT / "analysis" / "ggen_advance_nimbus_exss4_mapbank_20260910.json"


def decode_at(data: bytes, offset: int, dictionary, mapping) -> tuple[str, bytes]:
    tokens, raw = read_tokens(data, offset)
    slots = expand_to_slots(tokens, dictionary)
    text = "".join(mapping.get(slot, f"<{slot:04X}>") for slot in slots)
    return text, raw


def parse_scenario_container(data: bytes, offset: int, dictionary, mapping) -> list[str]:
    texts = []
    cursor = offset
    if data[cursor : cursor + 2] == b"\x00\x05":
        cursor += 6
    while cursor < len(data):
        if data[cursor] == 0:
            break
        text, raw = decode_at(data, cursor, dictionary, mapping)
        texts.append(text)
        cursor += len(raw)
        if cursor < len(data) and data[cursor] == 0x03:
            cursor += 1
            continue
        break
    return texts


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    japan = ORIGINAL_ROM.read_bytes()
    live = MAIN_TIP_ROM.read_bytes()
    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    dictionary = load_dictionary(japan, DICT_12X12_BASE, DICT_12X12_END)
    mapping = load_map(MAP12)
    mapping.update(CORRECTED_LOW_KANA)
    mapping[0x03C7] = "女"

    live_containers = {}
    for owner in (0x00220418, 0x0022041C, 0x00220484, 0x00220450):
        ptr = u32(live, owner)
        texts = parse_scenario_container(live, ptr - ROM_BASE, dictionary, mapping)
        live_containers[f"OWNER-U32-{owner:08X}"] = {"ptr": f"0x{ptr:08X}", "texts": texts}

    known = {}
    for row in merged["records"]:
        if row.get("source_scope") != "scenario_map_script":
            continue
        known[int(row["target_file_offset"], 16)] = row["record_id"]

    needles = ("敗北などない", "やるではないか", "選ばれしジオン", "だがっ", "くくく", "私はニムバス", "ニムバス・シュターゼン")
    found = []
    off = BANK_START
    while off < BANK_END:
        if japan[off] != 0x18:
            off += 1
            continue
        try:
            text, raw = decode_at(japan, off + 1, dictionary, mapping)
        except Exception:
            off += 1
            continue
        if not any(n in text for n in needles) and "ニムバス" not in text and "ドアン" not in text:
            off += 1
            continue
        chained = [text]
        cursor = off + 1 + len(raw)
        while cursor < BANK_END and japan[cursor] != 0x18 and japan[cursor] not in (0x08, 0x17):
            if japan[cursor] == 0:
                cursor += 1
                continue
            try:
                more, more_raw = decode_at(japan, cursor, dictionary, mapping)
            except Exception:
                break
            if not more:
                break
            chained.append(more)
            cursor += len(more_raw)
        blob = "\n".join(chained)
        found.append(
            {
                "opcode": f"0x{off:08X}",
                "stream": f"0x{off + 1:08X}",
                "in_sheet": known.get(off + 1),
                "texts": chained,
                "blob": blob,
            }
        )
        off += 1

    # Also scan scenario bank for 敗北などない / やるではないか near nimbus
    scenario_found = []
    for off in range(0x001F4000, 0x0021D000):
        if japan[off : off + 2] != b"\x00\x05" or japan[off + 3 : off + 5] != b"\x00\x06":
            continue
        speaker = japan[off + 2]
        try:
            texts = parse_scenario_container(japan, off, dictionary, mapping)
        except Exception:
            continue
        blob = "\n".join(texts)
        if any(n in blob for n in ("敗北などない", "やるではないか", "選ばれしジオンの", "だがっ", "くくく……やる", "私はニムバス・シュターゼン")):
            scenario_found.append({"offset": f"0x{off:08X}", "speaker": f"0x{speaker:02X}", "texts": texts})

    report = {
        "live_containers": live_containers,
        "map_bank_hits": found,
        "scenario_bank_hits": scenario_found,
        "map_not_in_sheet": [row for row in found if not row["in_sheet"]],
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("live containers")
    for key, val in live_containers.items():
        print(key, val)
    print("map hits", len(found), "not in sheet", len(report["map_not_in_sheet"]))
    for row in found:
        flag = "SHEET" if row["in_sheet"] else "MISSING"
        print(flag, row["stream"], row["blob"].replace("\n", " / "))
    print("scenario hits", len(scenario_found))
    for row in scenario_found:
        print(row["offset"], row["speaker"], " / ".join(row["texts"]))


if __name__ == "__main__":
    main()
