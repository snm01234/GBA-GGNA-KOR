#!/usr/bin/env python3
"""Patch the direct map-action help literals proven by the user's captures."""
from __future__ import annotations

import json
import struct
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from ggen_advance_project_paths import MAIN_TIP_MANIFEST, MAIN_TIP_ROM, ORIGINAL_ROM, TRANSLATION_MERGED_JSON, advance_relative  # noqa: E402
from merge_ggen_advance_translation_overlays import digest, translation_payload_digest  # noqa: E402
from patch_ggen_advance_intermission_text_consumers_20260904 import (  # noqa: E402
    DRAW_WRAPPER, ROM_BASE, bl_target, encode_literal, gate, load_apply_tokens, payload_at, sha256, u32,
)

BATCH_ID = "map-action-help-direct-consumers-20260904"
CHARMAP = ROOT / "analysis" / "ggen_advance_korean_apply_charmap_20260844.json"
SNAPSHOT = ROOT / "analysis" / "ggen_advance_translation_merged_20260904_map_action_help.json"
OUTPUT = ROOT / "outputs" / "20260904_ggen_advance_map_action_help" / "ggen_advance_map_action_help_candidate_20260904.gba"
REPORT = ROOT / "analysis" / "ggen_advance_map_action_help_consumers_20260904.json"

PATCHES = (
    {
        "name": "advance",
        "record_id": "GGA-TEXT-001BE7CE",
        "source": "次のセッションへ進みます",
        "translation": "다음 세션으로 진행합니다",
        "owner": 0x0006B008,
        "original_address": 0x081BE7CE,
        "call": 0x0006AFCE,
        "payload_offset": 0x012900A0,
    },
    {
        "name": "search",
        "record_id": "GGA-TEXT-001BE807",
        "source": "索敵を行います",
        "translation": "색적을 실시합니다",
        "owner": 0x0006B410,
        "original_address": 0x081BE807,
        "call": 0x0006B3DA,
        "payload_offset": 0x012900D0,
    },
)


def update_payload_hash(row: dict) -> None:
    patch = {
        "record_id": row["record_id"], "batch_id": row["overlay_batch_id"],
        "translation_ko": row.get("translation_ko") or "", "translation_segments": row.get("translation_segments"),
        "translation_status": row.get("translation_status") or "", "translation_source": row.get("translation_source") or "",
        "source_model": row.get("source_model") or "", "prompt_version": row.get("prompt_version") or "",
        "review_status": row.get("review_status") or "", "review_count": row.get("review_count") or 0,
        "reviewed_at": row.get("reviewed_at") or "", "translator_notes": row.get("translator_notes") or "",
        "qa_status": row.get("qa_status") or "",
    }
    row["translation_payload_sha256"] = translation_payload_digest(patch)


def main() -> int:
    original = ORIGINAL_ROM.read_bytes()
    current = MAIN_TIP_ROM.read_bytes()
    main_manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(len(current) == 32 * 1024 * 1024 and sha256(current) == main_manifest["sha256"], "main TIP/manifest drift")
    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    by_id = {row["record_id"]: row for row in merged["records"]}
    tokens = load_apply_tokens(CHARMAP)
    candidate = bytearray(current)
    allowed: set[int] = set()
    evidence = []

    for patch in PATCHES:
        row = by_id[patch["record_id"]]
        gate(row.get("translation_status") == "pending" and not row.get("translation_ko"), f"{patch['name']} row state drift")
        gate(row.get("source_decode_status") == "partial", f"{patch['name']} source was not partial")
        gate(row.get("owner_ids") == [f"OWNER-U32-{patch['owner']:08X}"], f"{patch['name']} owner drift")
        gate(u32(original, patch["owner"]) == patch["original_address"], f"{patch['name']} original pointer drift")
        active_address = u32(current, patch["owner"])
        original_payload = bytes.fromhex(str(row["raw_hex"]).replace(" ", ""))
        gate(payload_at(current, active_address) == original_payload, f"{patch['name']} pending-preserve payload drift")
        gate(bl_target(original, patch["call"]) == DRAW_WRAPPER, f"{patch['name']} draw call drift")
        payload = encode_literal(patch["translation"], tokens)
        at = patch["payload_offset"]
        gate(all(value == 0 for value in current[at : at + len(payload)]), f"{patch['name']} allocation is not zero-filled")
        candidate[at : at + len(payload)] = payload
        struct.pack_into("<I", candidate, patch["owner"], ROM_BASE + at)
        gate(u32(candidate, patch["owner"]) == ROM_BASE + at, f"{patch['name']} redirect failed")
        gate(payload_at(candidate, ROM_BASE + at) == payload, f"{patch['name']} payload failed")
        allowed.update(range(at, at + len(payload)))
        allowed.update(range(patch["owner"], patch["owner"] + 4))

        before = {key: row.get(key) for key in ("source_text", "source_decode_status", "source_unresolved_slots", "translation_ko", "translation_status")}
        row["source_text"] = patch["source"]
        row["source_decode_status"] = "complete"
        row["source_unresolved_slots"] = []
        row["baseline_translation_ko"] = patch["translation"]
        row["baseline_translation_status"] = "translated"
        row["translation_ko"] = patch["translation"]
        row["translation_status"] = "translated"
        row["translation_source"] = "user_verified_runtime_screenshot"
        row["review_status"] = "user_verified"
        row["review_count"] = int(row.get("review_count") or 0) + 1
        row["reviewed_at"] = "2026-09-04"
        row["translator_notes"] = f"첨부 실측 화면과 direct literal owner 0x{patch['owner']:08X}, draw call 0x{ROM_BASE + patch['call']:08X}로 소비 경로 확정"
        row["qa_status"] = "static_consumer_verified"
        row["overlay_batch_id"] = BATCH_ID
        update_payload_hash(row)
        evidence.append({
            "name": patch["name"], "record_id": patch["record_id"], "before": before,
            "source_text": patch["source"], "translation_ko": patch["translation"],
            "owner_offset": f"0x{patch['owner']:08X}", "call": f"0x{ROM_BASE + patch['call']:08X}",
            "draw": f"0x{DRAW_WRAPPER:08X}", "old_active_address": f"0x{active_address:08X}",
            "old_active_payload_hex": original_payload.hex(" ").upper(), "new_address": f"0x{ROM_BASE + at:08X}",
            "payload_hex": payload.hex(" ").upper(),
        })

    changed = [index for index, (before, after) in enumerate(zip(current, candidate)) if before != after]
    gate(set(changed) <= allowed, "candidate changed bytes outside direct owners/payloads")
    parent = str(merged.get("identity", {}).get("translation_overlay_identity_sha256") or "")
    payload_rows = [{"record_id": item["record_id"], "payload": by_id[item["record_id"]]["translation_payload_sha256"]} for item in PATCHES]
    identity = digest({"parent": parent, "batch_id": BATCH_ID, "records": payload_rows})
    merged["identity"]["parent_translation_overlay_identity_sha256"] = parent
    merged["identity"]["map_action_help_direct_identity_sha256"] = identity
    merged["identity"]["translation_overlay_identity_sha256"] = identity
    counts = dict(sorted(Counter(str(row.get("translation_status") or "") for row in merged["records"]).items()))
    merged["summary"]["merged_translation_status_counts"] = counts
    merged["summary"]["translation_overlay_identity_sha256"] = identity
    merged["map_action_help_direct_consumers"] = {"batch_id": BATCH_ID, "changed_records": 2, "identity_sha256": identity, "static_consumer_report": advance_relative(REPORT)}

    SNAPSHOT.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(candidate)
    report = {
        "schema_version": 1, "kind": "ggen_advance_map_action_help_direct_consumers_candidate_20260904",
        "source": {"main_tip": advance_relative(MAIN_TIP_ROM), "main_tip_sha256": sha256(current), "translation_source": advance_relative(TRANSLATION_MERGED_JSON)},
        "root_cause": "The measured screen uses direct PC-relative string literals, not the FCE128 indexed help table.",
        "consumers": evidence,
        "output": {"path": advance_relative(OUTPUT), "size": len(candidate), "sha256": sha256(candidate)},
        "verification": {"result": "PASS", "direct_literal_consumers_verified": True, "both_payloads_match_current_charmap": True, "only_two_owners_and_zero_cave_mutated": True, "changed_bytes": len(changed), "main_tip_not_modified": sha256(MAIN_TIP_ROM.read_bytes()) == sha256(current)},
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "candidate": advance_relative(OUTPUT), "sha256": sha256(candidate), "changed_bytes": len(changed)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
