#!/usr/bin/env python3
"""Decode the 37-entry in-battle quote table at 0x00228600."""
from __future__ import annotations

import json
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT / "tools"))
from extract_ggen_advance_id_command_battle_barks import load_slot_map, read_decoded_stream
from ggen_advance_project_paths import MAIN_TIP_ROM, ORIGINAL_ROM
from ggen_advance_text_codec import DICT_12X12_BASE, DICT_12X12_END, load_dictionary

ROM_BASE = 0x08000000
TABLE = 0x00228600
PAYLOAD_LO = 0x00228184
OUT = ROOT / "analysis" / "ggen_advance_post_idbark_quote_table_20260905.json"
MAP12 = ROOT / "analysis" / "ggen_advance_12x12_identified_charmap_20260828.json"
CORR = ROOT / "analysis" / "ggen_advance_12x12_runtime_measurement_corrections_20260829.json"


def u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def parse_blocks(data: bytes, start: int, boundary: int, dictionary, map12) -> dict:
    """Containers are one or more speaker blocks:

    00 05 speaker_lo 00 06 portrait [NUL stream (03 NUL stream)*] 03 00 (02 next-block | 01 end)
    """
    cursor = start
    blocks = []
    gate_prefix = data[cursor : cursor + 2]
    while cursor < boundary:
        if cursor + 6 > boundary:
            break
        if data[cursor : cursor + 2] != b"\x00\x05":
            break
        speaker = data[cursor + 2]
        if data[cursor + 3 : cursor + 5] != b"\x00\x06":
            break
        portrait = data[cursor + 5]
        cursor += 6
        streams = []
        while cursor < boundary:
            stream = read_decoded_stream(data, cursor, boundary, dictionary, map12)
            streams.append(
                {
                    "start_file_offset": stream["start_file_offset"],
                    "source_text": stream["source_text"],
                    "raw_hex": stream["raw_hex"],
                }
            )
            cursor += stream["raw_byte_length"]
            if cursor >= boundary or data[cursor] != 0x03:
                break
            cursor += 1
            if cursor + 1 < boundary and data[cursor] == 0x00 and data[cursor + 1] in (0x01, 0x02):
                break
        terminal = None
        if cursor + 1 < boundary and data[cursor] == 0x00:
            terminal = data[cursor + 1]
            cursor += 2
        blocks.append(
            {
                "speaker_id": f"0x{speaker:02X}",
                "portrait": f"0x{portrait:02X}",
                "streams": streams,
                "terminal": None if terminal is None else f"0x{terminal:02X}",
            }
        )
        if terminal == 0x01:
            break
        if terminal != 0x02:
            break
    return {
        "prefix_ok": gate_prefix == b"\x00\x05",
        "consumed_end": f"0x{cursor:08X}",
        "tail_hex": data[cursor:boundary].hex(" "),
        "blocks": blocks,
        "texts": [s["source_text"] for b in blocks for s in b["streams"]],
    }


def main() -> None:
    japan = ORIGINAL_ROM.read_bytes()
    main = MAIN_TIP_ROM.read_bytes()
    map12 = load_slot_map(MAP12, CORR)
    dictionary = load_dictionary(japan, DICT_12X12_BASE, DICT_12X12_END)
    ptrs = []
    off = TABLE
    while off + 4 <= len(japan):
        val = u32(japan, off)
        dest = val - ROM_BASE
        if not (PAYLOAD_LO <= dest < TABLE):
            break
        ptrs.append((off, dest, val))
        off += 4
    entries = []
    reported = []
    needles = ("思いだけでも", "ダメだけど", "それでも", "守りたい世界", "ダテじゃない")
    for i, (src, start, gba) in enumerate(ptrs):
        boundary = ptrs[i + 1][1] if i + 1 < len(ptrs) else TABLE
        parsed = parse_blocks(japan, start, boundary, dictionary, map12)
        row = {
            "index": i,
            "table_source": f"0x{src:08X}",
            "container_start": f"0x{start:08X}",
            "main_pointer": f"0x{u32(main, src):08X}",
            "relocated_on_main": u32(main, src) >= 0x09000000,
            **parsed,
        }
        entries.append(row)
        blob = "\n".join(parsed["texts"])
        if any(n in blob for n in needles):
            reported.append(row)

    unique_jp = []
    seen = set()
    for row in entries:
        for text in row["texts"]:
            if text not in seen:
                seen.add(text)
                unique_jp.append(text)

    refs = []
    needle = struct.pack("<I", ROM_BASE + TABLE)
    pos = 0
    while True:
        hit = main.find(needle, pos)
        if hit < 0:
            break
        refs.append(f"0x{hit:08X}")
        pos = hit + 1

    report = {
        "finding": (
            "ID-command 256x3 table ends at 0x00228184. Immediately after it is a "
            "separate 37-entry in-battle quote/cut-in table at 0x00228600 whose "
            "payloads (0x00228184-0x00228600) still point at original Japanese on "
            "main TIP. This family is not in id_command_battle_barks, "
            "battle_event_dialogue, or scenario_map_script apply paths."
        ),
        "table_file_offset": hex(TABLE),
        "table_end": hex(off),
        "sentinel_after_table": hex(u32(japan, off)),
        "entry_count": len(ptrs),
        "payload_range": [hex(PAYLOAD_LO), hex(TABLE)],
        "refs_to_table_base": refs,
        "all_main_pointers_original": all(not e["relocated_on_main"] for e in entries),
        "unique_source_texts": unique_jp,
        "unique_count": len(unique_jp),
        "reported_line_containers": reported,
        "entries": entries,
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("entries", len(ptrs), "unique", len(unique_jp), "reported", len(reported), "wrote", OUT)


if __name__ == "__main__":
    main()
