#!/usr/bin/env python3
"""Characterize the untranslated 0x002284xx battle-quote pool next to the ID-bark table."""
from __future__ import annotations

import json
import struct
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from ggen_advance_project_paths import MAIN_TIP_ROM, ORIGINAL_ROM
from ggen_advance_text_codec import (
    DICT_12X12_BASE,
    DICT_12X12_END,
    expand_to_slots,
    load_dictionary,
    read_tokens_strict,
)

ROM_BASE = 0x08000000
TABLE_END = 0x00228184
SCAN_END = 0x0022C000
OUT = ROOT / "analysis" / "ggen_advance_post_idbark_quote_pool_20260905.json"

ANCHORS = [
    0x002284CE,
    0x002284D8,
    0x002284EE,
    0x002284F5,
    0x0022850E,
    0x00228518,
    0x0022852E,
    0x00228535,
    0x002285AE,
]


def u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def decode_stream(data: bytes, offset: int, dictionary, mapping) -> tuple[str, int, bytes]:
    tokens, raw = read_tokens_strict(data, offset)
    slots = expand_to_slots(tokens, dictionary)
    text = "".join(mapping.get(slot, f"<{slot:04X}>") for slot in slots)
    end = offset + len(raw)
    return text, end, raw


def load_map12() -> dict[int, str]:
    payload = json.loads((ROOT / "analysis" / "ggen_advance_12x12_identified_charmap_20260828.json").read_text(encoding="utf-8"))
    return {int(k, 16): v for k, v in payload["verified_charmap"].items() if v}


def find_pointers(rom: bytes, dest_file: int) -> list[int]:
    dest = ROM_BASE + dest_file
    needle = struct.pack("<I", dest)
    hits = []
    start = 0
    while True:
        pos = rom.find(needle, start)
        if pos < 0:
            break
        hits.append(pos)
        start = pos + 1
        if len(hits) >= 30:
            break
    return hits


def likely_container_starts(rom: bytes, dictionary, mapping) -> list[dict]:
    """Walk 0x00228184..SCAN_END decoding consecutive NUL streams with bark-like markers."""
    rows = []
    off = TABLE_END
    # skip padding 00/FF
    while off < SCAN_END and rom[off] in (0x00, 0xFF):
        off += 1
    start_payload = off
    while off < SCAN_END:
        if rom[off] == 0x00:
            off += 1
            continue
        try:
            text, end, raw = decode_stream(rom, off, dictionary, mapping)
        except Exception:
            off += 1
            continue
        marker = rom[end] if end < len(rom) else None
        rows.append(
            {
                "file_offset": f"0x{off:08X}",
                "gba": f"0x{ROM_BASE + off:08X}",
                "source_text": text,
                "raw_len": len(raw),
                "marker": None if marker is None else f"0x{marker:02X}",
            }
        )
        off = end + (1 if marker not in (None, 0x00) else 0)
        if len(rows) >= 250:
            break
        # stop if we hit a dense pointer table (many 08xxxxxx)
        if off + 16 < len(rom):
            ptrs = [u32(rom, off + i) for i in range(0, 16, 4)]
            if sum(0x08000000 <= p < 0x09000000 for p in ptrs) >= 3:
                break
    return start_payload, rows


def main() -> None:
    rom = MAIN_TIP_ROM.read_bytes()
    japan = ORIGINAL_ROM.read_bytes()
    dictionary = load_dictionary(japan, DICT_12X12_BASE, DICT_12X12_END)
    mapping = load_map12()

    start_payload, streams = likely_container_starts(japan, dictionary, mapping)

    pointer_hits = {}
    for anchor in ANCHORS:
        hits = find_pointers(rom, anchor)
        pointer_hits[f"0x{anchor:08X}"] = [f"0x{h:08X}" for h in hits]

    # Also search for any pointer into [TABLE_END, TABLE_END+0x800]
    region_owners: Counter[int] = Counter()
    owner_samples = []
    region_lo = ROM_BASE + TABLE_END
    region_hi = ROM_BASE + TABLE_END + 0x800
    for off in range(0, min(len(rom), 0x01000000) - 3):
        val = u32(rom, off)
        if region_lo <= val < region_hi:
            region_owners[off] += 1
            if len(owner_samples) < 80:
                owner_samples.append({"source": f"0x{off:08X}", "dest": f"0x{val:08X}"})

    # ID bark table still pointing at original 08223xxx vs 09?
    table_base = 0x00226984
    sample_table = []
    for i in (3, 20, 172, 181, 182, 525):
        src = table_base + i * 8
        ptr = u32(rom, src)
        meta = u32(rom, src + 4)
        sample_table.append(
            {
                "slot": i,
                "table_entry": f"0x{src:08X}",
                "pointer": f"0x{ptr:08X}",
                "metadata": f"0x{meta:08X}",
                "relocated": ptr >= 0x09000000,
            }
        )

    # Compare 0x002284CE block vs map-script / idbark
    dump = japan[0x00228480:0x00228640].hex(" ")

    report = {
        "id_bark_table_end": hex(TABLE_END),
        "payload_walk_start": hex(start_payload),
        "first_nonpad": hex(start_payload),
        "stream_count": len(streams),
        "streams_head": streams[:40],
        "streams_matching_report": [s for s in streams if any(x in s["source_text"] for x in ("思いだけでも", "守りたい世界", "ダテじゃない", "それでも"))],
        "anchor_pointers_in_main": pointer_hits,
        "region_pointer_count_in_original_16mib": len(owner_samples),
        "region_pointer_samples": owner_samples,
        "id_bark_table_samples": sample_table,
        "hex_dump_00228480_00228640": dump,
        "bytes_after_table_vs_japan": rom[TABLE_END:TABLE_END + 0x800] == japan[TABLE_END:TABLE_END + 0x800],
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("payload start", hex(start_payload), "streams", len(streams))
    print("matching", json.dumps(report["streams_matching_report"], ensure_ascii=False, indent=2))
    print("anchor pointers", json.dumps(pointer_hits, indent=2))
    print("region owners", len(owner_samples))
    print("idbark samples", json.dumps(sample_table, indent=2))
    print("pool unchanged vs japan", report["bytes_after_table_vs_japan"])


if __name__ == "__main__":
    main()
