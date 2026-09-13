#!/usr/bin/env python3
"""Fix measured intermission 8x16 wording and parallel condition consumers."""
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

BATCH_ID = "intermission-8x16-parallel-conditions-20260904"
CHARMAP = ROOT / "analysis" / "ggen_advance_korean_apply_charmap_20260844.json"
SNAPSHOT = ROOT / "analysis" / "ggen_advance_translation_merged_20260904_intermission_8x16_conditions.json"
OUTPUT = ROOT / "outputs" / "20260904_ggen_advance_intermission_8x16_conditions" / "ggen_advance_intermission_8x16_conditions_candidate_20260904.gba"
REPORT = ROOT / "analysis" / "ggen_advance_intermission_8x16_conditions_20260904.json"

PATCHES = (
    {
        "name": "advance_direct",
        "record_id": "GGA-TEXT-001BE7CE",
        "source": "次のセッションへ進みます",
        "translation": "다음 작전으로 진행합니다",
        "owners": (0x0006B008,),
        "payload_offset": 0x01290100,
        "kind": "translated_reword",
    },
    {
        "name": "advance_fce128",
        "record_id": "GGA-TEXT-001BE836",
        "source": "次のセッションに進みます",
        "translation": "다음 작전으로 진행합니다",
        "owners": (0x00FCE130, 0x00FCE15C),
        "payload_offset": 0x01290100,
        "kind": "translated_reword",
    },
    {
        "name": "search_fce128",
        "record_id": "GGA-TEXT-001BE824",
        "source": "周辺地域の索敵を行います",
        "translation": "주변을 색적합니다",
        "owners": (0x00FCE12C,),
        "payload_offset": 0x01290140,
        "kind": "translated_reword",
    },
    {
        "name": "odessa_parallel_condition",
        "record_id": "GGA-TEXT-0018D50D",
        "source": "オデッサ",
        "translation": "오데사",
        "owners": (0x00FCE1B4,),
        "payload_offset": 0x01290170,
        "kind": "pending_promote",
    },
    {
        "name": "search_ground_parallel_condition",
        "record_id": "GGA-TEXT-0018D656",
        "source": "索敵地上",
        "translation": "색적 지상",
        "owners": (0x00FCE230, 0x00FCE258, 0x00FCE25C, 0x00FCE260, 0x00FCE264, 0x00FCE268, 0x00FCE26C, 0x00FCE270, 0x00FCE274, 0x00FCE278, 0x00FCE27C, 0x00FCE28C, 0x00FCE290),
        "payload_offset": 0x01290180,
        "kind": "pending_promote",
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
    gate(u32(original, 0x0006B170) == 0x08FCE1A0, "parallel condition table literal drift")
    gate(bl_target(original, 0x0006AFD2) == 0x0806B148 and bl_target(original, 0x0006B3DE) == 0x0806B148, "parallel condition bridge drift")
    gate(bl_target(original, 0x0006AFE0) == DRAW_WRAPPER and bl_target(original, 0x0006B3EC) == DRAW_WRAPPER, "parallel condition draw drift")

    apply = json.loads(CHARMAP.read_text(encoding="utf-8"))
    assignment = {row["char"]: row for row in apply["assignments"]}
    tokens = load_apply_tokens(CHARMAP)
    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    by_id = {row["record_id"]: row for row in merged["records"]}
    candidate = bytearray(current)
    allowed: set[int] = set()
    written: dict[int, bytes] = {}
    evidence = []

    for patch in PATCHES:
        row = by_id[patch["record_id"]]
        gate(tuple(int(owner.removeprefix("OWNER-U32-"), 16) for owner in row.get("owner_ids", [])) == patch["owners"], f"{patch['name']} owner drift")
        if patch["kind"] == "pending_promote":
            gate(row.get("translation_status") == "pending" and not row.get("translation_ko"), f"{patch['name']} pending state drift")
        else:
            gate(row.get("translation_status") == "translated" and row.get("translation_ko"), f"{patch['name']} translated state drift")
        for char in patch["translation"]:
            if char != " ":
                gate(assignment.get(char, {}).get("paint") == "both", f"{patch['name']} uses non-8x16 glyph {char!r}")
        payload = encode_literal(patch["translation"], tokens)
        at = patch["payload_offset"]
        if at in written:
            gate(written[at] == payload, f"shared payload conflict at 0x{at:08X}")
        else:
            gate(all(value == 0 for value in current[at : at + len(payload)]), f"{patch['name']} allocation is not zero-filled")
            candidate[at : at + len(payload)] = payload
            written[at] = payload
            allowed.update(range(at, at + len(payload)))
        old_addresses = [u32(current, owner) for owner in patch["owners"]]
        for owner in patch["owners"]:
            struct.pack_into("<I", candidate, owner, ROM_BASE + at)
            allowed.update(range(owner, owner + 4))
        gate(all(u32(candidate, owner) == ROM_BASE + at for owner in patch["owners"]), f"{patch['name']} redirect failed")
        gate(payload_at(candidate, ROM_BASE + at) == payload, f"{patch['name']} payload failed")

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
        row["translator_notes"] = "첨부 실측으로 병렬 전투조건 소비 경로와 8x16 글리프 제약을 확정"
        row["qa_status"] = "static_consumer_and_8x16_glyph_verified"
        row["overlay_batch_id"] = BATCH_ID
        update_payload_hash(row)
        evidence.append({
            "name": patch["name"], "record_id": patch["record_id"], "before": before,
            "source_text": patch["source"], "translation_ko": patch["translation"],
            "owner_offsets": [f"0x{owner:08X}" for owner in patch["owners"]],
            "old_active_addresses": [f"0x{address:08X}" for address in sorted(set(old_addresses))],
            "new_address": f"0x{ROM_BASE + at:08X}", "payload_hex": payload.hex(" ").upper(),
            "all_glyphs_painted_both_fonts": True,
        })

    changed = [index for index, (before, after) in enumerate(zip(current, candidate)) if before != after]
    gate(set(changed) <= allowed, "candidate changed outside target owners/payloads")
    parent = str(merged.get("identity", {}).get("translation_overlay_identity_sha256") or "")
    payload_rows = [{"record_id": patch["record_id"], "payload": by_id[patch["record_id"]]["translation_payload_sha256"]} for patch in PATCHES]
    identity = digest({"parent": parent, "batch_id": BATCH_ID, "records": payload_rows})
    merged["identity"]["parent_translation_overlay_identity_sha256"] = parent
    merged["identity"]["intermission_8x16_conditions_identity_sha256"] = identity
    merged["identity"]["translation_overlay_identity_sha256"] = identity
    counts = dict(sorted(Counter(str(row.get("translation_status") or "") for row in merged["records"]).items()))
    merged["summary"]["merged_translation_status_counts"] = counts
    merged["summary"]["translation_overlay_identity_sha256"] = identity
    merged["intermission_8x16_conditions"] = {"batch_id": BATCH_ID, "changed_records": len(PATCHES), "identity_sha256": identity, "static_consumer_report": advance_relative(REPORT)}

    SNAPSHOT.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(candidate)
    report = {
        "schema_version": 1, "kind": "ggen_advance_intermission_8x16_conditions_candidate_20260904",
        "source": {"main_tip": advance_relative(MAIN_TIP_ROM), "main_tip_sha256": sha256(current), "translation_source": advance_relative(TRANSLATION_MERGED_JSON)},
        "root_causes": [
            "The yellow-window second line is supplied by FCE1A0 through 0x0806B148, not search-record +0x10.",
            "The measured 8x16 path used translations containing 12x12-only glyphs (션 and 탐).",
        ],
        "consumers": evidence,
        "output": {"path": advance_relative(OUTPUT), "size": len(candidate), "sha256": sha256(candidate)},
        "verification": {"result": "PASS", "parallel_condition_bridge_verified": True, "all_output_glyphs_painted_both_fonts": True, "all_target_owners_redirected": True, "only_target_owners_and_zero_cave_mutated": True, "changed_bytes": len(changed), "main_tip_not_modified": sha256(MAIN_TIP_ROM.read_bytes()) == sha256(current)},
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "candidate": advance_relative(OUTPUT), "sha256": sha256(candidate), "changed_bytes": len(changed)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
