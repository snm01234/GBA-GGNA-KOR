"""Koreanize ss1 ジオン学徒兵 (ジオン学럼兵) without touching 지온해병.

GGA-TEXT-0017CECD is ジオン+学(0x01C0)+slot 0x0782(원문 徒, 현재 럼)+兵.
Slot 0x0782 stays 럼 for other consumers. Encode 지온학도병 onto existing
8x16 Hangul and retarget OWNER-U32-001AACB0.
"""
from __future__ import annotations

import json
import struct
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import build_ggen_advance_ko_poc as fontops  # noqa: E402
import build_ggen_advance_unified_rom_poc as unified  # noqa: E402
import patch_ggen_advance_apsaras_zentetsu_20260908 as aps  # noqa: E402
import patch_ggen_profile_followup2_20260912 as f2  # noqa: E402
from ggen_advance_painted_glyph_identity import FONT8_RELOCATED, slot_raw  # noqa: E402
from ggen_advance_project_paths import (  # noqa: E402
    MAIN_TIP_MANIFEST,
    MAIN_TIP_ROM,
    ORIGINAL_ROM,
    TRANSLATION_MERGED_JSON,
    advance_relative,
)
from ggen_advance_text_codec import DICT_8X16_BASE, DICT_8X16_END, load_dictionary
from merge_ggen_advance_translation_overlays import digest  # noqa: E402
from patch_ggen_advance_apsaras_zentetsu_20260908 import hangul_chars  # noqa: E402
from patch_ggen_advance_intermission_text_consumers_20260904 import gate, sha256  # noqa: E402
from patch_ggen_advance_kimi_jane_to_neo_20260904 import (  # noqa: E402
    owner_offsets,
    update_payload_hash,
    update_translation_manifest,
)

BATCH_ID = "zeon-student-soldier-20260912"
IDENTITY_KEY = "zeon_student_soldier_20260912_sha256"
BATCH_KEY = "zeon_student_soldier_20260912"
OUT = ROOT / "outputs" / "20260912_zeon_student_soldier"
WORK = OUT / "ggen_zeon_student_soldier_20260912.gba"
SNAPSHOT = ROOT / "analysis" / "ggen_advance_translation_merged_20260912_zeon_student_soldier.json"
CAVE_START = 0x01135360
CAVE_END = 0x01230000
NAME_RECORD = "GGA-TEXT-0017CECD"
NAME_KO = "지온학도병"
NAME_SOURCE = "ジオン<01C0><0782><00C8>"
NAME_RAW = "f004e0e0e6a2c800"
MARINE_RECORD = "GGA-TEXT-0017CEEB"
MARINE_KO = "지온해병"
MARINE_OWNER = 0x001AAE90
MARINE_PTR = 0x09135330
STOLEN_SLOT = 0x0782
NOTES = (
    "ss1 ジオン学徒兵(표시 ジオン学럼兵)→지온학도병. "
    "지온해병(海兵)과 별개. 슬롯 0x0782는 럼으로 유지하고 페이로드만 한글 재배치."
)


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def patch_merged_row(row: dict[str, Any], ko: str) -> None:
    row["translation_ko"] = ko
    row["translation_status"] = "translated"
    row["translation_source"] = "user_verified"
    row["review_status"] = "user_verified"
    row["review_count"] = int(row.get("review_count") or 0) + 1
    row["reviewed_at"] = "2026-09-12"
    row["translator_notes"] = NOTES
    row["qa_status"] = "static_consumer_verified"
    row["overlay_batch_id"] = BATCH_ID
    row["pointer_recalc_required"] = True
    update_payload_hash(row)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    parent = MAIN_TIP_ROM.read_bytes()
    japan = ORIGINAL_ROM.read_bytes()
    manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(parent) == str(manifest.get("sha256") or ""), "main TIP sha mismatch")
    gate(all(b == 0 for b in parent[CAVE_START:CAVE_END]), "student-soldier cave is not empty")
    gate(u32(parent, MARINE_OWNER) == MARINE_PTR, "지온해병 pointer drift")

    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    by_id = {str(row["record_id"]): row for row in merged["records"]}
    name_row = by_id[NAME_RECORD]
    marine_row = by_id[MARINE_RECORD]
    gate(str(name_row.get("source_text") or "") == NAME_SOURCE, "학도병 source drift")
    gate(str(name_row.get("translation_ko") or "") in {"", NAME_KO}, "학도병 translation drift")
    gate(bytes.fromhex(str(name_row.get("raw_hex") or "").replace(" ", "")).hex() == NAME_RAW, "학도병 raw drift")
    gate(str(marine_row.get("translation_ko") or "") == MARINE_KO, "지온해병 sheet drift")

    live8, _live12 = unified.collect_live_slots(japan, merged["records"])
    verified8 = unified.load_verified_charmap(unified.CHARMAP_8X16_PATH)
    stolen_before = slot_raw(parent, FONT8_RELOCATED, STOLEN_SLOT, fontops.FONT_8X16_STRIDE)
    hangul8 = set(hangul_chars(NAME_KO))

    candidate = bytearray(parent)
    allowed: set[int] = set()
    painted: list[dict[str, str]] = []
    occupied8: set[int] = set()
    recovered8 = f2.recover_hangul(
        candidate, japan, hangul8, mode=8, live=live8, occupied=occupied8, allowed=allowed, painted=painted
    )
    gate(not painted, f"unexpected hangul paint {painted}")

    encoded, missing = unified.encode_korean_text(
        NAME_KO, recovered8, verified_charmap=verified8, strict_punctuation=True
    )
    gate(encoded is not None and not missing, f"encode 학도병 failed {missing}")
    gate(len(encoded) > 8, "학도병 encoded into original 8-byte JP slot")
    owners = owner_offsets(name_row)
    gate(owners == (0x001AACB0,), f"학도병 owners {owners}")
    old_payload = f2.payload_at(parent, u32(parent, owners[0]))
    gate(old_payload.hex() == NAME_RAW, f"학도병 live raw {old_payload.hex()}")
    cave_cursor, old_addresses, new_addr = aps.patch_owned_payload(
        name_row, old_payload, encoded, parent, candidate, allowed, cave_cursor := CAVE_START, require_nul=True
    )
    patch_merged_row(name_row, NAME_KO)

    dict8 = load_dictionary(bytes(candidate), DICT_8X16_BASE, DICT_8X16_END)
    map8 = f2.slot_to_char_map(verified8, recovered8, f2.hangul_slot_map(candidate, mode=8))
    name_live = f2.decode_text(candidate, u32(candidate, owners[0]), dict8, map8)
    gate(name_live == NAME_KO, f"학도병 live {name_live!r}")
    marine_live = f2.decode_text(candidate, u32(candidate, MARINE_OWNER), dict8, map8)
    gate(marine_live == MARINE_KO, f"지온해병 live {marine_live!r}")
    gate(u32(candidate, MARINE_OWNER) == MARINE_PTR, "지온해병 pointer rewritten")
    gate(
        slot_raw(candidate, FONT8_RELOCATED, STOLEN_SLOT, fontops.FONT_8X16_STRIDE) == stolen_before,
        "slot 0x0782 rewritten",
    )
    leftover = []
    for row in merged["records"]:
        if row.get("semantic_category") not in {"character_name", "character_name_alternate", "unit_name", "unit_name_alternate"}:
            continue
        for owner in owner_offsets(row):
            live = f2.decode_text(candidate, u32(candidate, owner), dict8, map8)
            if "学럼" in live or "ジオン学" in live:
                leftover.append((str(row["record_id"]), hex(owner), live))
    gate(not leftover, f"학도병 leftover {leftover}")

    changed = {i for i, (old, new) in enumerate(zip(parent, candidate)) if old != new}
    gate(changed <= allowed, f"unrelated writes {len(changed - allowed)}")
    gate(cave_cursor <= CAVE_END, "cave overflow")

    parent_identity = str(merged.get("identity", {}).get("translation_overlay_identity_sha256") or "")
    new_identity = digest({"parent": parent_identity, "batch_id": BATCH_ID, "records": [NAME_RECORD]})
    identity = merged.setdefault("identity", {})
    identity["parent_translation_overlay_identity_sha256"] = parent_identity
    identity[IDENTITY_KEY] = new_identity
    identity["translation_overlay_identity_sha256"] = new_identity
    summary = merged.setdefault("summary", {})
    summary["merged_translation_status_counts"] = dict(
        sorted(Counter(str(row.get("translation_status") or "") for row in merged["records"]).items())
    )
    summary["translation_overlay_identity_sha256"] = new_identity
    merged[BATCH_KEY] = {
        "batch_id": BATCH_ID,
        "changed_records": [NAME_RECORD],
        "evidence": [
            {
                "record_id": NAME_RECORD,
                "path": "u32_8x16",
                "before": NAME_SOURCE,
                "after": NAME_KO,
                "old_active_addresses": old_addresses,
                "new_address": new_addr,
            }
        ],
    }
    payload_json = json.dumps(merged, ensure_ascii=False, indent=2) + "\n"
    SNAPSHOT.write_text(payload_json, encoding="utf-8")
    TRANSLATION_MERGED_JSON.write_text(payload_json, encoding="utf-8")
    update_translation_manifest(merged, SNAPSHOT)
    WORK.write_bytes(bytes(candidate))
    sav_src = MAIN_TIP_ROM.with_suffix(".sav")
    if sav_src.exists():
        WORK.with_suffix(".sav").write_bytes(sav_src.read_bytes())
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_zeon_student_soldier_20260912",
        "batch_id": BATCH_ID,
        "parent_sha256": sha256(parent),
        "output": {"path": advance_relative(WORK), "size": len(candidate), "sha256": sha256(bytes(candidate))},
        "painted": painted,
        "cave": {"start": hex(CAVE_START), "end": hex(cave_cursor), "capacity_end": hex(CAVE_END)},
        "changed_bytes": len(changed),
        "proofs": {"student_soldier": name_live, "marine": marine_live, "new_address": new_addr},
        "verification": {
            "result": "PASS",
            "zeon_student_soldier_ko": True,
            "zeon_marine_preserved": True,
            "slot_0782_preserved": True,
            "no_new_hangul_paint": True,
            "unrelated_bytes_preserved": True,
        },
    }
    (OUT / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("output", "painted", "cave", "proofs", "verification")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
