#!/usr/bin/env python3
"""Re-encode the search-ground label against the active font-slot map."""
from __future__ import annotations

import hashlib
import json
import struct
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

from ggen_advance_project_paths import MAIN_TIP_MANIFEST, MAIN_TIP_ROM, TRANSLATION_MERGED_JSON, advance_relative  # noqa: E402
from merge_ggen_advance_translation_overlays import digest, translation_payload_digest  # noqa: E402
from patch_ggen_advance_intermission_text_consumers_20260904 import (  # noqa: E402
    DRAW_WRAPPER,
    ROM_BASE,
    SEARCH_LOCATION_CALL,
    bl_target,
    encode_literal,
    gate,
    load_apply_tokens,
    payload_at,
    sha256,
    u32,
)

RECORD_ID = "GGA-TEXT-001BF052"
SOURCE = "索敵地上"
KOREAN = "색적 지상"
PAYLOAD_OFFSET = 0x01290070
PAYLOAD_ADDRESS = ROM_BASE + PAYLOAD_OFFSET
BATCH_ID = "search-ground-consumer-20260904"
SNAPSHOT = ROOT / "analysis" / "ggen_advance_translation_merged_20260904_search_ground.json"
OUTPUT = ROOT / "outputs" / "20260904_ggen_advance_search_ground_consumer" / "ggen_advance_search_ground_consumer_candidate_20260904.gba"
REPORT = ROOT / "analysis" / "ggen_advance_search_ground_consumer_20260904.json"
CHARMAP = ROOT / "analysis" / "ggen_advance_korean_apply_charmap_20260844.json"


def main() -> int:
    current = MAIN_TIP_ROM.read_bytes()
    manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(len(current) == 32 * 1024 * 1024 and sha256(current) == manifest["sha256"], "main TIP/manifest drift")
    gate(bl_target(current, SEARCH_LOCATION_CALL) == DRAW_WRAPPER, "current-search label draw consumer drift")

    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    row = next((item for item in merged["records"] if item.get("record_id") == RECORD_ID), None)
    gate(row is not None, "search-ground translation record missing")
    gate(row.get("translation_status") == "translated" and row.get("translation_ko") == KOREAN, "search-ground translation drift")
    gate("jp=索敵地上" in str(row.get("translator_notes") or ""), "decoded-source evidence missing")
    owners = [int(value.removeprefix("OWNER-U32-"), 16) for value in row.get("owner_ids", [])]
    gate(len(owners) == 12, "search-ground owner count drift")
    old_pointers = [u32(current, owner) for owner in owners]
    gate(len(set(old_pointers)) == 1, "search-ground owners do not converge")

    payload = encode_literal(KOREAN, load_apply_tokens(CHARMAP))
    old_payload = payload_at(current, old_pointers[0])
    gate(old_payload != payload, "search-ground payload already matches current charmap")
    gate(all(value == 0 for value in current[PAYLOAD_OFFSET : PAYLOAD_OFFSET + len(payload)]), "target allocation is not zero-filled")

    candidate = bytearray(current)
    candidate[PAYLOAD_OFFSET : PAYLOAD_OFFSET + len(payload)] = payload
    for owner in owners:
        struct.pack_into("<I", candidate, owner, PAYLOAD_ADDRESS)
    gate(all(u32(candidate, owner) == PAYLOAD_ADDRESS for owner in owners), "owner redirect failed")
    gate(payload_at(candidate, PAYLOAD_ADDRESS) == payload, "payload write failed")
    allowed = set(range(PAYLOAD_OFFSET, PAYLOAD_OFFSET + len(payload)))
    for owner in owners:
        allowed.update(range(owner, owner + 4))
    changed = [index for index, (before, after) in enumerate(zip(current, candidate)) if before != after]
    gate(set(changed) <= allowed, "unexpected byte change")

    before_source = row.get("source_text")
    row["source_text"] = SOURCE
    row["source_decode_status"] = "complete"
    row["source_unresolved_slots"] = []
    row["review_status"] = "user_verified"
    row["review_count"] = int(row.get("review_count") or 0) + 1
    row["reviewed_at"] = "2026-09-04"
    row["translator_notes"] = "첨부 화면과 current-search record +0x10 소비 경로로 索敵地上을 확정; 현행 글꼴 슬롯로 색적 지상 재인코딩"
    row["qa_status"] = "static_consumer_verified"
    row["overlay_batch_id"] = BATCH_ID
    patch = {
        "record_id": row["record_id"], "batch_id": BATCH_ID, "translation_ko": row["translation_ko"],
        "translation_segments": row.get("translation_segments"), "translation_status": row["translation_status"],
        "translation_source": row.get("translation_source") or "", "source_model": row.get("source_model") or "",
        "prompt_version": row.get("prompt_version") or "", "review_status": row["review_status"],
        "review_count": row["review_count"], "reviewed_at": row["reviewed_at"],
        "translator_notes": row["translator_notes"], "qa_status": row["qa_status"],
    }
    row["translation_payload_sha256"] = translation_payload_digest(patch)
    parent_identity = str(merged.get("identity", {}).get("translation_overlay_identity_sha256") or "")
    new_identity = digest({"parent": parent_identity, "batch_id": BATCH_ID, "records": [{"record_id": RECORD_ID, "payload": row["translation_payload_sha256"]}]})
    merged["identity"]["parent_translation_overlay_identity_sha256"] = parent_identity
    merged["identity"]["search_ground_consumer_identity_sha256"] = new_identity
    merged["identity"]["translation_overlay_identity_sha256"] = new_identity
    counts = dict(sorted(Counter(str(item.get("translation_status") or "") for item in merged["records"]).items()))
    merged["summary"]["merged_translation_status_counts"] = counts
    merged["summary"]["translation_overlay_identity_sha256"] = new_identity
    merged["search_ground_consumer"] = {"batch_id": BATCH_ID, "changed_records": 1, "identity_sha256": new_identity, "static_consumer_report": advance_relative(REPORT)}

    SNAPSHOT.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(candidate)
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_search_ground_consumer_candidate_20260904",
        "source": {"main_tip": advance_relative(MAIN_TIP_ROM), "main_tip_sha256": sha256(current), "translation_source": advance_relative(TRANSLATION_MERGED_JSON)},
        "static_consumer": {"record": RECORD_ID, "record_field": "current-search record +0x10", "call": "0x0801C63E", "draw": "0x08000CA0", "owner_offsets": [f"0x{owner:08X}" for owner in owners]},
        "translation_change": {"source_before": before_source, "source_text": SOURCE, "translation_ko": KOREAN, "translation_snapshot": advance_relative(SNAPSHOT)},
        "patch": {"old_address": f"0x{old_pointers[0]:08X}", "new_address": f"0x{PAYLOAD_ADDRESS:08X}", "old_payload_hex": old_payload.hex(" ").upper(), "payload_hex": payload.hex(" ").upper(), "changed_bytes": len(changed)},
        "output": {"path": advance_relative(OUTPUT), "size": len(candidate), "sha256": sha256(candidate)},
        "verification": {"result": "PASS", "static_consumer_verified": True, "all_12_owners_redirected": True, "payload_matches_current_charmap": True, "only_owner_and_zero_cave_mutated": True, "main_tip_not_modified": sha256(MAIN_TIP_ROM.read_bytes()) == sha256(current)},
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "candidate": advance_relative(OUTPUT), "sha256": sha256(candidate), "changed_bytes": len(changed)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
