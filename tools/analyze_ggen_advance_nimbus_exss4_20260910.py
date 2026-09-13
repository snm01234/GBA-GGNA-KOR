#!/usr/bin/env python3
"""Audit Nimbus/Yuu 女→벽 errors and Extra-session battle quotes still drawing JP."""
from __future__ import annotations

import json
import struct
import sys
from collections import defaultdict
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
CORR = ROOT / "analysis" / "ggen_advance_12x12_runtime_measurement_corrections_20260829.json"
OUT = ROOT / "analysis" / "ggen_advance_nimbus_exss4_audit_20260910.json"
MAIN_DIRECTORY = 0x0021D5B4
MAIN_SLOTS = 22
MAIN_STRIDE_WORDS = 23
WALL_KO = ("벽",)
TARGET_ROWS = {128, 129, 130, 131, 132}
NIMBUS_SPEAKER = "0x005F"
YUU_SPEAKER = "0x007F"
DOAN_MARKERS = ("ドアン", "도안")
SHOT_NEEDLES = (
    "だがっ",
    "やるではないか",
    "敗北",
    "ニムバス・シュターゼン",
    "選ばれ",
    "くくく",
)


def lookup_hits(rom: bytes, orig_addr: int, expected_end: int) -> list[tuple[int, int, int]]:
    key = struct.pack("<I", orig_addr)
    hits: list[tuple[int, int, int]] = []
    cursor = 0
    while True:
        pos = rom.find(key, cursor)
        if pos < 0:
            break
        if pos + 12 <= len(rom):
            orig, neu, orig_end = struct.unpack_from("<III", rom, pos)
            if orig == orig_addr and orig_end == expected_end and 0x09000000 <= neu < 0x0A000000:
                hits.append((pos, neu, orig_end))
        cursor = pos + 1
    return hits


def decode_hex(raw_hex: str, dictionary, mapping: dict[int, str]) -> tuple[str, list[str]]:
    hex_text = str(raw_hex or "").replace(" ", "")
    if hex_text in {"", "00"}:
        return "", []
    try:
        data = bytes.fromhex(hex_text)
    except ValueError:
        return "", ["bad_hex"]
    if not data.endswith(b"\x00"):
        data += b"\x00"
    try:
        tokens, _raw = read_tokens(data, 0)
    except Exception:
        return "", ["parse_fail"]
    slots = expand_to_slots(tokens, dictionary)
    missing = []
    chars = []
    for slot in slots:
        char = mapping.get(slot)
        if char is None:
            missing.append(f"0x{slot:04X}")
            chars.append(f"<{slot:04X}>")
        else:
            chars.append(char)
    return "".join(chars), missing


def load_mapping() -> dict[int, str]:
    mapping = load_map(MAP12)
    mapping.update(CORRECTED_LOW_KANA)
    mapping[0x03C7] = "女"
    mapping[0x060D] = "壁"
    return mapping


def visible_ko(row: dict) -> str:
    return str(row.get("translation_ko") or "").replace("\\n", "\n")


def visible_jp(row: dict) -> str:
    return str(row.get("source_text") or "").replace("\\n", "\n")


def main() -> None:
    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    records = merged["records"]
    japan = ORIGINAL_ROM.read_bytes()
    live = MAIN_TIP_ROM.read_bytes()
    dictionary = load_dictionary(japan, DICT_12X12_BASE, DICT_12X12_END)
    mapping = load_mapping()
    by_id = {row["record_id"]: row for row in records}

    wall_hits = []
    for row in records:
        ko = visible_ko(row)
        jp = visible_jp(row)
        if "벽" not in ko:
            continue
        if any(word in ko for word in ("완벽", "암벽", "절벽", "외벽", "새벽", "승벽")):
            continue
        segs = list(row.get("segments") or [])
        redone = []
        for seg in segs:
            text, missing = decode_hex(str(seg.get("raw_hex") or ""), dictionary, mapping)
            if str(seg.get("source_text") or ""):
                redone.append({"old": seg.get("source_text"), "new": text, "missing": missing})
        wall_hits.append(
            {
                "record_id": row["record_id"],
                "scope": row.get("source_scope"),
                "jp": jp,
                "ko": ko,
                "status": row.get("translation_status"),
                "speaker_id": row.get("speaker_id"),
                "directory_row": row.get("directory_row"),
                "decode": redone,
            }
        )

    extra_rows = []
    for row in records:
        if row.get("source_scope") != "scenario_main":
            continue
        drow = row.get("directory_row")
        speaker = None
        for control in row.get("control_signature") or []:
            if int(str(control.get("code") or "0"), 16) == 0x05:
                speaker = f"0x{int(control.get('argument') or 0):02X}"
                break
        jp = visible_jp(row)
        interesting = (
            drow in TARGET_ROWS
            or speaker in {NIMBUS_SPEAKER, YUU_SPEAKER}
            or any(mark in jp for mark in ("ニムバス", "ドアン", "ユウ"))
            or any(needle in jp for needle in SHOT_NEEDLES)
            or "壁" in visible_ko(row)
        )
        if not interesting:
            continue
        owners = [oid for oid in row.get("owner_ids") or [] if str(oid).startswith("OWNER-U32-")]
        pointer_info = []
        for oid in owners:
            off = int(oid.removeprefix("OWNER-U32-"), 16)
            ptr = u32(live, off)
            pointer_info.append(
                {
                    "owner": oid,
                    "live_ptr": f"0x{ptr:08X}",
                    "relocated": ptr >= 0x09000000,
                    "points_at_original": ptr == ROM_BASE + int(row["target_file_offset"], 16),
                }
            )
        segs = []
        for seg in row.get("segments") or []:
            text, missing = decode_hex(str(seg.get("raw_hex") or ""), dictionary, mapping)
            if str(seg.get("source_text") or "") or text:
                segs.append(
                    {
                        "sheet": seg.get("source_text"),
                        "decoded": text,
                        "missing": missing,
                        "ko_seg": None,
                    }
                )
        extra_rows.append(
            {
                "record_id": row["record_id"],
                "directory_row": drow,
                "directory_slot": row.get("directory_slot"),
                "speaker": speaker,
                "jp_sheet": jp,
                "ko": visible_ko(row),
                "status": row.get("translation_status"),
                "decode_status": row.get("source_decode_status"),
                "unresolved": row.get("source_unresolved_slots"),
                "decoded_now": segs,
                "pointers": pointer_info,
            }
        )

    map_hits = []
    for row in records:
        if row.get("source_scope") != "scenario_map_script":
            continue
        jp = visible_jp(row)
        ko = visible_ko(row)
        speaker = row.get("speaker_id")
        if not (
            speaker in {NIMBUS_SPEAKER, YUU_SPEAKER}
            or any(mark in jp for mark in ("ニムバス", "カジマ", "ドアン", "女"))
            or "벽" in ko
            or any(needle in jp for needle in SHOT_NEEDLES)
            or (0x00F64000 <= int(row["target_file_offset"], 16) <= 0x00F65000)
            or (0x00FBFD00 <= int(row["target_file_offset"], 16) <= 0x00FBFF00)
        ):
            continue
        orig_addr = ROM_BASE + int(row["target_file_offset"], 16)
        raw = bytes.fromhex(str(row.get("raw_hex") or "").replace(" ", ""))
        lookups = lookup_hits(live, orig_addr, orig_addr + len(raw)) if raw else []
        segs = []
        for seg in row.get("segments") or []:
            text, missing = decode_hex(str(seg.get("raw_hex") or ""), dictionary, mapping)
            segs.append({"sheet": seg.get("source_text"), "decoded": text, "missing": missing})
        map_hits.append(
            {
                "record_id": row["record_id"],
                "offset": row.get("target_file_offset"),
                "speaker": speaker,
                "jp": jp,
                "ko": ko,
                "status": row.get("translation_status"),
                "lookup_count": len(lookups),
                "lookup_relocated": [f"0x{neu:08X}" for _pos, neu, _end in lookups],
                "decoded_now": segs,
            }
        )

    shot_matches = []
    for row in records:
        blob = visible_jp(row) + "\n" + visible_ko(row)
        if any(needle in blob for needle in SHOT_NEEDLES) or "님버스 슈타젠" in visible_ko(row):
            shot_matches.append(
                {
                    "record_id": row["record_id"],
                    "scope": row.get("source_scope"),
                    "speaker": row.get("speaker_id"),
                    "directory_row": row.get("directory_row"),
                    "jp": visible_jp(row),
                    "ko": visible_ko(row),
                    "status": row.get("translation_status"),
                    "decode_status": row.get("source_decode_status"),
                }
            )

    report = {
        "wall_ko_hits": wall_hits,
        "scenario_nimbus_yuu_doan": extra_rows,
        "map_nimbus_yuu_doan": map_hits,
        "screenshot_needles": shot_matches,
        "counts": {
            "wall": len(wall_hits),
            "scenario": len(extra_rows),
            "map": len(map_hits),
            "shots": len(shot_matches),
            "scenario_still_original": sum(
                1
                for row in extra_rows
                if row["pointers"] and all(item["points_at_original"] for item in row["pointers"])
            ),
            "map_missing_lookup": sum(1 for row in map_hits if row["lookup_count"] == 0),
        },
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["counts"], ensure_ascii=False, indent=2))
    print("wall")
    for row in wall_hits:
        print(row["record_id"], row["jp"][:40], "=>", row["ko"].replace("\n", " / "))
    print("scenario still original")
    for row in extra_rows:
        if row["pointers"] and all(item["points_at_original"] for item in row["pointers"]):
            decoded = " / ".join(seg["decoded"] for seg in row["decoded_now"] if seg["decoded"])
            print(row["record_id"], "row", row["directory_row"], decoded or row["jp_sheet"][:60], "ko=", row["ko"].replace("\n", " / ")[:40])


if __name__ == "__main__":
    main()
