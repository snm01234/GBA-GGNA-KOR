#!/usr/bin/env python3
"""Extract map-script dialogue past the old 0x00FC0000 bank end (Exss leftover)."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from analyze_ggen_advance_pending_decode import CORRECTED_LOW_KANA, load_map
from extract_ggen_advance_map_script_dialogue import (
    BANK_END,
    PRINT_SETUP,
    SPEAKER_LOOKBACK,
    decode_slots,
    is_command_boundary,
)
from ggen_advance_project_paths import ORIGINAL_ROM, TRANSLATION_MERGED_JSON
from ggen_advance_text_codec import (
    DICT_12X12_BASE,
    DICT_12X12_END,
    expand_to_slots,
    load_dictionary,
    read_tokens,
)

ROM_BASE = 0x08000000
SCAN_START = 0x00FC0000
SCAN_END = 0x00FD0000
MAP12 = ROOT / "analysis" / "ggen_advance_12x12_identified_charmap_20260828.json"
OUT = ROOT / "analysis" / "ggen_advance_exss4_missing_map_script_20260910.json"


def speaker_near(data: bytes, pos: int) -> str | None:
    start = max(0, pos - SPEAKER_LOOKBACK)
    window = data[start:pos]
    for i in range(len(window) - 4, -1, -1):
        if window[i : i + 2] == b"\x17\xE6" and window[i + 2] == 0x08:
            return f"0x{window[i + 3]:02X}"
    return None


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    japan = ORIGINAL_ROM.read_bytes()
    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    dictionary = load_dictionary(japan, DICT_12X12_BASE, DICT_12X12_END)
    mapping = load_map(MAP12)
    mapping.update(CORRECTED_LOW_KANA)
    mapping[0x03C7] = "女"
    mapping[0x060D] = "壁"

    known = {
        int(row["target_file_offset"], 16)
        for row in merged["records"]
        if str(row.get("record_id") or "").startswith("GGA-MAPSCRIPT-")
    }

    rows = []
    off = SCAN_START
    while off < SCAN_END:
        if japan[off] != 0x18:
            off += 1
            continue
        if off + 1 >= SCAN_END:
            break
        try:
            tokens, raw = read_tokens(japan, off + 1)
            slots = expand_to_slots(tokens, dictionary)
            text, missing = decode_slots(slots, mapping)
        except Exception:
            off += 1
            continue
        if not text:
            off += 1
            continue
        chained = [{"offset": f"0x{off + 1:08X}", "text": text, "raw_hex": raw.hex(" "), "missing": [f"0x{s:04X}" for s in missing]}]
        cursor = off + 1 + len(raw)
        while cursor < SCAN_END and japan[cursor] == 0x00:
            nxt = cursor + 1
            if nxt >= SCAN_END or japan[nxt] in (0x18, 0x17, 0x08, 0x01):
                break
            try:
                tokens2, raw2 = read_tokens(japan, nxt)
                slots2 = expand_to_slots(tokens2, dictionary)
                text2, missing2 = decode_slots(slots2, mapping)
            except Exception:
                break
            if not text2:
                break
            chained.append(
                {
                    "offset": f"0x{nxt:08X}",
                    "text": text2,
                    "raw_hex": raw2.hex(" "),
                    "missing": [f"0x{s:04X}" for s in missing2],
                }
            )
            cursor = nxt + len(raw2)
        blob = "\n".join(item["text"] for item in chained)
        rows.append(
            {
                "opcode": f"0x{off:08X}",
                "first_stream": chained[0]["offset"],
                "in_old_bank": off < BANK_END,
                "already_in_sheet": int(chained[0]["offset"], 16) in known,
                "speaker_guess": speaker_near(japan, off),
                "lines": chained,
                "blob": blob,
            }
        )
        off += 1

    missing_rows = [row for row in rows if not row["already_in_sheet"]]
    interesting = [
        row
        for row in missing_rows
        if any(
            token in row["blob"]
            for token in ("ニムバス", "ドアン", "カジマ", "女", "だが", "敗北", "やる", "くくく", "選ばれ")
        )
    ]
    report = {
        "scan": {"start": hex(SCAN_START), "end": hex(SCAN_END), "old_bank_end": hex(BANK_END)},
        "counts": {
            "opcode_18": len(rows),
            "not_in_sheet": len(missing_rows),
            "nimbus_doan_yuu_like": len(interesting),
        },
        "interesting": interesting,
        "all_missing": missing_rows,
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("opcode18", len(rows), "missing", len(missing_rows), "interesting", len(interesting))
    for row in interesting:
        print(row["first_stream"], row.get("speaker_guess"), row["blob"].replace("\n", " / "))


if __name__ == "__main__":
    main()
