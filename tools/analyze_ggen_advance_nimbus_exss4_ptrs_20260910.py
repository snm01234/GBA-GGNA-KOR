#!/usr/bin/env python3
"""Find leftover original pointers to Nimbus scenario streams and ID-bark copies."""
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
OUT = ROOT / "analysis" / "ggen_advance_nimbus_exss4_ptrs_20260910.json"
NEEDLES = {
    "0020AC28": bytes.fromhex("F07BD942F127070700"),
    "0020AC44": bytes.fromhex("E39043542DF00441F0C40500"),
    "0020AF34": bytes.fromhex("A442F12703F1370700"),
    "0020AD30": None,
}


def find_all(data: bytes, needle: bytes, limit: int = 40) -> list[int]:
    hits = []
    start = 0
    while True:
        pos = data.find(needle, start)
        if pos < 0:
            break
        hits.append(pos)
        start = pos + 1
        if len(hits) >= limit:
            break
    return hits


def ptr_hits(data: bytes, dest: int, limit: int = 40) -> list[int]:
    return find_all(data, struct.pack("<I", dest), limit)


def decode_at(data: bytes, offset: int, dictionary, mapping) -> str:
    tokens, _raw = read_tokens(data, offset)
    slots = expand_to_slots(tokens, dictionary)
    return "".join(mapping.get(slot, f"<{slot:04X}>") for slot in slots)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    japan = ORIGINAL_ROM.read_bytes()
    live = MAIN_TIP_ROM.read_bytes()
    dictionary = load_dictionary(japan, DICT_12X12_BASE, DICT_12X12_END)
    mapping = load_map(MAP12)
    mapping.update(CORRECTED_LOW_KANA)
    mapping[0x03C7] = "女"
    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))

    targets = [
        0x0020AC28,
        0x0020AC44,
        0x0020AF34,
        0x0020AA30,
        0x0020AD30,
        0x0020A994,
        0x00215790,
        0x0020AFD8,
    ]
    report_targets = []
    for off in targets:
        dest = ROM_BASE + off
        jp_ptrs = ptr_hits(japan, dest)
        live_ptrs = ptr_hits(live, dest)
        live_high = [p for p in live_ptrs if p >= 0x01000000]
        report_targets.append(
            {
                "offset": f"0x{off:08X}",
                "jp_ptr_count": len(jp_ptrs),
                "jp_ptrs": [f"0x{p:08X}" for p in jp_ptrs[:12]],
                "live_orig_ptr_count": len(live_ptrs),
                "live_orig_ptrs": [f"0x{p:08X}" for p in live_ptrs[:12]],
                "live_orig_in_expansion": [f"0x{p:08X}" for p in live_high[:12]],
            }
        )
        print(f"0x{off:08X} jp_ptrs={len(jp_ptrs)} live_orig_ptrs={len(live_ptrs)} { [hex(p) for p in live_ptrs[:8]] }")

    # ID bark nimbus streams
    idbark = json.loads((ROOT / "integrated/translation/ggen_advance_id_command_battle_barks.json").read_text(encoding="utf-8"))
    nimbus = []
    for row in idbark["records"]:
        if row.get("character_name") != "ニムバス":
            continue
        text = row.get("source_text") or ""
        nimbus.append(
            {
                "record_id": row["record_id"],
                "jp": text,
                "ko": row.get("translation_ko"),
                "status": row.get("translation_status"),
                "command_index": row.get("command_index"),
                "offset": row.get("target_file_offset"),
            }
        )
        if any(n in text for n in ("ニムバス", "敗北", "やる", "だが", "選ばれ", "くく")):
            print("IDBARK", row["record_id"], text, "=>", row.get("translation_ko"))

    cutin = json.loads((ROOT / "integrated/translation/ggen_advance_battle_cutin_quotes.json").read_text(encoding="utf-8"))
    cutin_hits = []
    for row in cutin["records"]:
        blob = str(row.get("source_text") or "") + str(row.get("translation_ko") or "")
        if any(n in blob for n in ("ニムバス", "敗北", "やるではない", "だがっ", "くくく", "女", "벽")):
            cutin_hits.append(row)
            print("CUTIN", row["record_id"], row.get("source_text"), "=>", row.get("translation_ko"))

    # Byte search for 選ばれしジオン
    needle = bytes.fromhex("E39043542DF00441")
    jp_bytes = find_all(japan, needle)
    live_bytes = find_all(live, needle)
    print("選ばれしジオン bytes jp", [hex(p) for p in jp_bytes], "live", [hex(p) for p in live_bytes])

    # だがっ！ as F0 34 37 05 (だがっ！) vs F0 34 37 05 05 (だがっ！！)
    for label, raw in (
        ("だがっ！", bytes.fromhex("F0343705")),
        ("だがっ！！", bytes.fromhex("F034370505")),
        ("くくく……やる", bytes.fromhex("2828280707")),
    ):
        print(label, "jp", [hex(p) for p in find_all(japan, raw)[:12]], "live", [hex(p) for p in find_all(live, raw)[:12]])

    report = {
        "targets": report_targets,
        "nimbus_idbark_count": len(nimbus),
        "nimbus_idbark_sample": nimbus[:40],
        "cutin_hits": cutin_hits,
        "selbare_jp": [f"0x{p:08X}" for p in jp_bytes],
        "selbare_live": [f"0x{p:08X}" for p in live_bytes],
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("idbark nimbus", len(nimbus))


if __name__ == "__main__":
    main()
