#!/usr/bin/env python3
"""Apply bitmap-closed ID-command lines to the sheet and current-main ROM.

Charmap promotions are already in the 8x16 supplement.  This writes Korean
for leftover=1 ID-command barks that fully decode, plus a few closed 8x16
UI labels.  Unit-name soup and broken collocations stay pending.
Original JP bytes stay in place; U32 owners redirect into the expansion cave
after the 20260907 readable-batch cursor.
"""
from __future__ import annotations

import json
import shutil
import struct
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "analysis"))

import build_ggen_advance_ko_poc as fontops  # noqa: E402
import build_ggen_advance_unified_rom_poc as unified  # noqa: E402
import patch_ggen_advance_pending_readable_batch_20260907 as prev  # noqa: E402
from analyze_ggen_advance_pending_decode import CORRECTED_LOW_KANA, RESERVED  # noqa: E402
from ggen_advance_painted_glyph_identity import (  # noqa: E402
    FONT8_RELOCATED,
    load_galmuri8,
    packed_8x16,
    paint_8x16,
    recover_unique_8x16_slots,
    slot_raw,
)
from ggen_advance_project_paths import (  # noqa: E402
    MAIN_TIP_MANIFEST,
    MAIN_TIP_ROM,
    ORIGINAL_ROM,
    TRANSLATION_MERGED_JSON,
    advance_relative,
)
from ggen_advance_text_codec import (  # noqa: E402
    DICT_12X12_BASE,
    DICT_12X12_END,
    DICT_8X16_BASE,
    DICT_8X16_END,
    load_dictionary,
)
from merge_ggen_advance_translation_overlays import digest  # noqa: E402
from patch_ggen_advance_intermission_text_consumers_20260904 import (  # noqa: E402
    ROM_BASE,
    gate,
    payload_at,
    sha256,
    u32,
)

import _tmp_classify_pending_readable_20260907 as decode  # noqa: E402

BATCH_ID = "bitmap-idcmd-20260907"
KO_MAP = ROOT / "analysis" / "ggen_advance_8x16_bitmap_idcmd_ko_20260907.json"
SNAPSHOT = ROOT / "analysis" / "ggen_advance_translation_merged_20260907_bitmap_idcmd.json"
OUT_DIR = ROOT / "outputs" / "20260907_ggen_advance_bitmap_idcmd"
OUTPUT = OUT_DIR / "ggen_advance_bitmap_idcmd_candidate_20260907.gba"
OUT_SAV = OUT_DIR / "ggen_advance_bitmap_idcmd_candidate_20260907.sav"
MAIN_SAV = ROOT / "SD Gundam GGeneration Advance (Korean).sav"
REPORT = ROOT / "analysis" / "ggen_advance_bitmap_idcmd_candidate_20260907.json"
MANIFEST = OUT_DIR / "manifest.json"
CAVE_START = 0x012B08F0
CAVE_END = 0x012C0000
EXTRA_CATS = {
    "series_title",
    "map_system_selector_static_label",
    "unit_defense_ability",
}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    prev.BATCH_ID = BATCH_ID
    maps = json.loads(KO_MAP.read_text(encoding="utf-8"))
    idcmd_map = maps["idcmd_jp_to_ko"]
    extra_map = maps["extra_jp_to_ko"]
    original = ORIGINAL_ROM.read_bytes()
    current = MAIN_TIP_ROM.read_bytes()
    main_manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(len(current) == 32 * 1024 * 1024, "main TIP size drift")
    gate(sha256(current) == main_manifest.get("sha256"), "main TIP/manifest hash drift")
    gate(all(value == 0 for value in current[CAVE_START:CAVE_END]), "bitmap-idcmd cave is not zero-filled")
    gate(MAIN_SAV.exists(), "current main SAV missing")

    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    dict8 = load_dictionary(original, DICT_8X16_BASE, DICT_8X16_END)
    dict12 = load_dictionary(original, DICT_12X12_BASE, DICT_12X12_END)
    map8 = decode.load_identified_slot_to_char(decode.CHARMAP_8X16_PATH)
    map12 = decode.load_identified_slot_to_char(decode.CHARMAP_12X12_PATH)
    map12.update(CORRECTED_LOW_KANA)
    jp8 = prev.load_char_to_slot(decode.CHARMAP_8X16_PATH)
    font8 = load_galmuri8()
    live8, _live12 = unified.collect_live_slots(original, merged["records"])

    jobs: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for row in merged["records"]:
        if row.get("translation_status") != "pending":
            continue
        if row.get("translation_policy") != "translate":
            continue
        category = str(row.get("semantic_category") or "")
        decoded, missing, font = decode.decode_row(row, dict8, dict12, map8, map12)
        text_missing = [slot for slot in missing if slot not in RESERVED]
        if font != "8x16" or text_missing:
            continue
        if category == "id_command_name":
            korean = idcmd_map.get(decoded)
            if korean is None:
                skipped.append({"record_id": row["record_id"], "reason": "held broken collocation or unmapped", "decoded": decoded})
                continue
            jobs.append({"row": row, "source": decoded, "korean": korean, "notes": "8x16 비트맵 leftover=1 ID커맨드"})
            continue
        if category in EXTRA_CATS:
            korean = extra_map.get(decoded)
            if korean is None:
                skipped.append({"record_id": row["record_id"], "reason": "extra label unmapped", "decoded": decoded})
                continue
            jobs.append({"row": row, "source": decoded, "korean": korean, "notes": f"8x16 비트맵 폐쇄 라벨 {category}"})
            continue

    hangul8 = set().union(*(prev.hangul_chars(job["korean"]) for job in jobs))
    candidate = bytearray(current)
    allowed: set[int] = set()
    occupied8: set[int] = set()
    slots8: dict[str, int] = {}
    painted = []

    for char in sorted(hangul8):
        slot = prev.try_recover(recover_unique_8x16_slots, candidate, font8, char)
        if slot is None:
            slot = prev.choose_free_8x16(candidate, original, live8, occupied8)
            start = paint_8x16(candidate, slot, char, font8)
            allowed.update(range(start, start + fontops.FONT_8X16_STRIDE))
            painted.append({"font": "8x16", "char": char, "slot": f"0x{slot:04X}"})
            live8.add(slot)
        occupied8.add(slot)
        slots8[char] = slot

    encode8_map = dict(jp8)
    encode8_map.update(slots8)

    cursor = CAVE_START
    written: dict[str, int] = {}
    rom_jobs = 0
    sheet_only = 0
    changed_ids: list[str] = []

    for job in jobs:
        row = job["row"]
        korean = job["korean"]
        source = job["source"]
        owners = prev.owner_offsets(row)
        prev.mark_row(row, source, korean, job["notes"])
        changed_ids.append(row["record_id"])
        if not owners:
            skipped.append({"record_id": row["record_id"], "reason": "no owners after mark"})
            sheet_only += 1
            continue
        orig_raw = bytes.fromhex(str(row["raw_hex"]).replace(" ", ""))
        current_payloads = [payload_at(current, u32(current, owner)) for owner in owners]
        already_relocated = any(payload != orig_raw for payload in current_payloads)
        if already_relocated:
            sheet_only += 1
            continue
        payload = prev.encode_text(korean, slots8, encode8_map)
        key = payload.hex()
        if key in written:
            pointer = ROM_BASE + written[key]
        else:
            start = prev.align16(cursor)
            end = start + len(payload)
            gate(end <= CAVE_END, "bitmap-idcmd cave overflow")
            candidate[start:end] = payload
            allowed.update(range(start, end))
            written[key] = start
            cursor = end
            pointer = ROM_BASE + start
        for owner in owners:
            struct.pack_into("<I", candidate, owner, pointer)
            allowed.update(range(owner, owner + 4))
        rom_jobs += 1

    changed = [index for index, (before, after) in enumerate(zip(current, candidate)) if before != after]
    gate(set(changed) <= allowed, f"unexpected ROM byte change x{len(set(changed) - allowed)}")

    parent_identity = str(merged.get("identity", {}).get("translation_overlay_identity_sha256") or "")
    new_identity = digest({"parent": parent_identity, "batch_id": BATCH_ID, "records": changed_ids})
    identity = merged.setdefault("identity", {})
    identity["parent_translation_overlay_identity_sha256"] = parent_identity
    identity["bitmap_idcmd_batch_identity_sha256"] = new_identity
    identity["translation_overlay_identity_sha256"] = new_identity
    counts = dict(sorted(Counter(str(row.get("translation_status") or "") for row in merged["records"]).items()))
    summary = merged.setdefault("summary", {})
    summary["merged_translation_status_counts"] = counts
    summary["translation_overlay_identity_sha256"] = new_identity
    merged["bitmap_idcmd_batch_20260907"] = {
        "batch_id": BATCH_ID,
        "changed_records": len(changed_ids),
        "rom_redirected": rom_jobs,
        "sheet_only": sheet_only,
        "skipped": len(skipped),
        "promoted_slots": 53,
    }

    payload_json = json.dumps(merged, ensure_ascii=False, indent=2) + "\n"
    SNAPSHOT.write_text(payload_json, encoding="utf-8")
    TRANSLATION_MERGED_JSON.write_text(payload_json, encoding="utf-8")
    prev.update_translation_manifest(merged, SNAPSHOT)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(bytes(candidate))
    shutil.copy2(MAIN_SAV, OUT_SAV)
    report = {
        "result": "PASS",
        "batch_id": BATCH_ID,
        "changed_records": len(changed_ids),
        "rom_redirected": rom_jobs,
        "sheet_only": sheet_only,
        "skipped": len(skipped),
        "painted_glyphs": painted,
        "cave": {"start": hex(CAVE_START), "end": hex(cursor), "capacity_end": hex(CAVE_END)},
        "unique_payloads": len(written),
        "parent": {"path": advance_relative(MAIN_TIP_ROM), "sha256": sha256(current)},
        "output": {"path": advance_relative(OUTPUT), "sha256": sha256(candidate), "size": len(candidate)},
        "translation_source": {"path": advance_relative(TRANSLATION_MERGED_JSON), "sha256": sha256(payload_json.encode("utf-8"))},
        "verification": {
            "result": "PASS",
            "only_cave_owners_and_new_glyphs_changed": True,
            "held_broken_collocation": maps["policy"]["held_decoded_but_wrong_collocation"],
            "runtime_emulator": "not run; static ROM verification only",
        },
        "skipped_samples": skipped[:20],
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    MANIFEST.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("result", "changed_records", "rom_redirected", "sheet_only", "skipped", "painted_glyphs", "cave", "output")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
