#!/usr/bin/env python3
"""Dump live payloads and search for screenshot Nimbus lines."""
from __future__ import annotations

import json
import struct
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
MAP12 = ROOT / "analysis" / "ggen_advance_12x12_identified_charmap_20260828.json"
OUT = ROOT / "analysis" / "ggen_advance_nimbus_exss4_live_20260910.json"


def decode_at(data: bytes, offset: int, dictionary, mapping) -> str:
    tokens, _raw = read_tokens(data, offset)
    slots = expand_to_slots(tokens, dictionary)
    return "".join(mapping.get(slot, f"<{slot:04X}>") for slot in slots)


def decode_hex(raw_hex: str, dictionary, mapping) -> str:
    hex_text = raw_hex.replace(" ", "")
    if hex_text in {"", "00"}:
        return ""
    data = bytes.fromhex(hex_text)
    if not data.endswith(b"\x00"):
        data += b"\x00"
    try:
        return decode_at(data, 0, dictionary, mapping)
    except Exception:
        return ""


def lookup_any(rom: bytes, orig_addr: int) -> list[tuple[int, int, int]]:
    key = struct.pack("<I", orig_addr)
    hits = []
    cursor = 0
    while True:
        pos = rom.find(key, cursor)
        if pos < 0:
            break
        if pos + 12 <= len(rom):
            orig, neu, orig_end = struct.unpack_from("<III", rom, pos)
            if orig == orig_addr and 0x08000000 <= orig_end <= 0x0A000000:
                hits.append((pos, neu, orig_end))
        cursor = pos + 1
        if len(hits) >= 8:
            break
    return hits


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    japan = ORIGINAL_ROM.read_bytes()
    live = MAIN_TIP_ROM.read_bytes()
    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    dictionary = load_dictionary(japan, DICT_12X12_BASE, DICT_12X12_END)
    mapping = load_map(MAP12)
    mapping.update(CORRECTED_LOW_KANA)
    mapping[0x03C7] = "女"
    mapping[0x060D] = "壁"

    live_samples = {}
    for addr in (0x09076ACF, 0x09076AFB, 0x09076EDA):
        off = addr - ROM_BASE
        texts = []
        cursor = off
        for _ in range(6):
            if live[cursor] == 0:
                break
            try:
                text = decode_at(live, cursor, dictionary, mapping)
                tokens, raw = read_tokens(live, cursor)
                texts.append({"addr": f"0x{ROM_BASE + cursor:08X}", "text": text, "raw": raw.hex(" ")})
                cursor += len(raw)
                if live[cursor] in (0x01, 0x02, 0x03):
                    cursor += 1
                    if live[cursor] == 0:
                        cursor += 1
            except Exception as exc:
                texts.append({"addr": f"0x{ROM_BASE + cursor:08X}", "error": str(exc)})
                break
        live_samples[f"0x{addr:08X}"] = texts

    needles = ("敗北", "やるではない", "だがっ", "選ばれしジオン", "私はニムバス", "くくく")
    hits = []
    for row in merged["records"]:
        segs = []
        for seg in row.get("segments") or []:
            decoded = decode_hex(str(seg.get("raw_hex") or ""), dictionary, mapping)
            if decoded:
                segs.append(decoded)
        decoded_all = "\n".join(segs)
        blob = decoded_all + "\n" + str(row.get("source_text") or "") + "\n" + str(row.get("translation_ko") or "")
        if not any(n in blob for n in needles):
            continue
        if not any(n in decoded_all for n in needles) and "ニムバス" not in decoded_all:
            continue
        hits.append(
            {
                "record_id": row["record_id"],
                "scope": row.get("source_scope"),
                "directory_row": row.get("directory_row"),
                "speaker": row.get("speaker_id"),
                "decoded": decoded_all,
                "ko": row.get("translation_ko"),
                "status": row.get("translation_status"),
            }
        )

    # Map lookup using opcode/target with any orig_end
    map_ids = [
        "GGA-MAPSCRIPT-00F64189",
        "GGA-MAPSCRIPT-00FB2261",
        "GGA-MAPSCRIPT-00FBFDD3",
        "GGA-MAPSCRIPT-00FBFDF2",
        "GGA-MAPSCRIPT-00F64462",
        "GGA-MAPSCRIPT-00F79FCF",
    ]
    by_id = {row["record_id"]: row for row in merged["records"]}
    map_lookups = {}
    for rid in map_ids:
        row = by_id[rid]
        orig = ROM_BASE + int(row["target_file_offset"], 16)
        opcode = row.get("opcode_18_file_offset")
        found = lookup_any(live, orig)
        if opcode:
            found += lookup_any(live, ROM_BASE + int(opcode, 16))
        map_lookups[rid] = [
            {"table": f"0x{pos:08X}", "neu": f"0x{neu:08X}", "end": f"0x{end:08X}"}
            for pos, neu, end in found
        ]

    # Search Japan ROM scenario bank for screenshot phrases via decode of consecutive streams
    bank_hits = []
    mapping[0x03C7] = "女"
    for off in range(0x001F0000, 0x00222000):
        if japan[off : off + 2] != b"\x00\x05":
            continue
        if japan[off + 3 : off + 5] != b"\x00\x06":
            continue
        speaker = japan[off + 2]
        if speaker not in (0x5F, 0x7F, 0x25, 0x43):
            continue
        cursor = off + 6
        texts = []
        try:
            for _ in range(4):
                text = decode_at(japan, cursor, dictionary, mapping)
                _tokens, raw = read_tokens(japan, cursor)
                texts.append(text)
                cursor += len(raw)
                if cursor < len(japan) and japan[cursor] == 0x03:
                    cursor += 1
                    continue
                break
        except Exception:
            continue
        blob = "\n".join(texts)
        if any(n in blob for n in ("敗北など", "やるではないか", "選ばれしジオン", "だがっ", "くくく")):
            bank_hits.append(
                {
                    "offset": f"0x{off:08X}",
                    "speaker": f"0x{speaker:02X}",
                    "texts": texts,
                }
            )

    report = {
        "live_samples": live_samples,
        "decoded_needles": hits,
        "map_lookups": map_lookups,
        "bank_hits": bank_hits,
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("live")
    for addr, texts in live_samples.items():
        print(addr, [t.get("text") for t in texts])
    print("needles", len(hits))
    for row in hits:
        if any(n in (row["decoded"] or "") for n in ("敗北", "やるではない", "選ばれしジオン", "だがっ", "くくく", "私はニムバス")):
            print(row["record_id"], row["scope"], row["decoded"].replace("\n", " / "), "=>", str(row["ko"] or "").replace("\n", " / ")[:40])
    print("bank", len(bank_hits))
    for row in bank_hits[:40]:
        print(row["offset"], row["speaker"], " / ".join(row["texts"]))
    print("lookups", json.dumps(map_lookups, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
