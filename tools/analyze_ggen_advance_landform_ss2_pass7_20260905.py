#!/usr/bin/env python3
"""Dump selector/status pending labels and inspect ROM around live 回避 tiles."""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

from ggen_advance_project_paths import ADVANCE_ROOT, ORIGINAL_ROM, TRANSLATION_MERGED_JSON
from ggen_advance_text_codec import read_tokens, expand_to_slots, load_dictionary, DICT_12X12_BASE, DICT_12X12_END, DICT_8X16_BASE, DICT_8X16_END

OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_landform_ss2_pass7_20260905.json"
CHARMAP12 = ADVANCE_ROOT / "analysis" / "ggen_advance_12x12_identified_charmap_20260828.json"
CHARMAP8 = ADVANCE_ROOT / "analysis" / "ggen_advance_8x16_charmap_supplement_20260828.json"
ROM_BASE = 0x08000000
CATS = {
    "ui_menu_or_status_text",
    "map_system_selector_static_label",
    "map_system_selector_help",
    "map_system_function_help",
    "scroll_list_label",
}


def u16(data, off):
    return struct.unpack_from("<H", data, off)[0]


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    japan = ORIGINAL_ROM.read_bytes()
    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    rows = []
    for row in merged["records"]:
        cat = str(row.get("semantic_category") or "")
        if cat not in CATS and not (cat == "ui_menu_or_status_text"):
            continue
        if cat not in CATS:
            continue
        rows.append(
            {
                "record_id": row["record_id"],
                "semantic_category": cat,
                "source_text": row.get("source_text"),
                "translation_ko": row.get("translation_ko"),
                "translation_status": row.get("translation_status"),
                "raw_hex": row.get("raw_hex"),
                "owner_ids": row.get("owner_ids"),
                "target_file_offset": row.get("target_file_offset"),
                "unresolved": row.get("source_unresolved_slots"),
            }
        )
    # Also all translated/pending ui_menu and selector regardless
    extra = []
    for row in merged["records"]:
        cat = str(row.get("semantic_category") or "")
        if cat not in {"ui_menu_or_status_text", "map_system_selector_static_label", "map_system_selector_help"}:
            continue
        extra.append(
            {
                "record_id": row["record_id"],
                "semantic_category": cat,
                "source_text": row.get("source_text"),
                "translation_ko": row.get("translation_ko"),
                "translation_status": row.get("translation_status"),
                "raw_hex": row.get("raw_hex"),
                "owner_ids": row.get("owner_ids"),
            }
        )

    # Probe 16x7 maps near 0xE3000
    maps = []
    for off in range(0x000E2000, 0x000E5000):
        if japan[off] == 16 and japan[off + 1] == 7:
            count = 16 * 7
            cells = list(struct.unpack_from(f"<{count}H", japan, off + 4))
            maps.append({"offset": hex(off), "first8": [hex(c) for c in cells[:8]], "unique": len(set(c & 0x3FF for c in cells))})

    # Bytes around 0xE3800
    snippet = japan[0xE3700:0xE3900]
    header_guess = []
    for off in range(0xE3000, 0xE3834, 2):
        if japan[off : off + 2] == b"\x02\x00":
            header_guess.append({"offset": hex(off), "words": [hex(u16(japan, off + i)) for i in range(0, 16, 2)]})

    report = {
        "selector_family": extra,
        "maps_16x7_near_e3": maps,
        "kind2_like_headers": header_guess[:20],
        "around_e3800_hex": snippet[:64].hex(),
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("selector count", len(extra))
    print(json.dumps(extra, ensure_ascii=False, indent=2))
    print("maps16x7", maps)
    print("headers", header_guess[:12])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
