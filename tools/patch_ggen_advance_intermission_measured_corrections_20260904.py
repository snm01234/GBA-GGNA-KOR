#!/usr/bin/env python3
"""Apply measured 8x16 corrections for advance and ground/space search labels."""
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

BATCH_ID = "intermission-measured-corrections-20260904"
CHARMAP = ROOT / "analysis" / "ggen_advance_korean_apply_charmap_20260844.json"
SNAPSHOT = ROOT / "analysis" / "ggen_advance_translation_merged_20260904_measured_corrections.json"
OUTPUT = ROOT / "outputs" / "20260904_ggen_advance_intermission_measured_corrections" / "ggen_advance_intermission_measured_corrections_candidate_20260904.gba"
REPORT = ROOT / "analysis" / "ggen_advance_intermission_measured_corrections_20260904.json"

PATCHES = (
    {
        "name": "advance_direct",
        "record_id": "GGA-TEXT-001BE7CE",
        "source": "次のセッションへ進みます",
        "translation": "다음 작전을 시작합니다",
        "owners": (0x0006B008,),
        "payload_offset": 0x01290200,
        "evidence": "measured 8x16 output showed 진 as 짊",
    },
    {
        "name": "advance_fce128",
        "record_id": "GGA-TEXT-001BE836",
        "source": "次のセッションに進みます",
        "translation": "다음 작전을 시작합니다",
        "owners": (0x00FCE130, 0x00FCE15C),
        "payload_offset": 0x01290200,
        "evidence": "same measured phrase and font path",
    },
    {
        "name": "search_space_parallel_condition",
        "record_id": "GGA-TEXT-0018D656",
        "source": "索敵宇宙",
        "translation": "색적 우주",
        "owners": (0x00FCE230, 0x00FCE258, 0x00FCE25C, 0x00FCE260, 0x00FCE264, 0x00FCE268, 0x00FCE26C, 0x00FCE270, 0x00FCE274, 0x00FCE278, 0x00FCE27C, 0x00FCE28C, 0x00FCE290),
        "payload_offset": 0x01290230,
        "evidence": "F0 51 suffix matches the independently decoded search-location record GGA-TEXT-001BF04C",
    },
    {
        "name": "search_ground_parallel_condition",
        "record_id": "GGA-TEXT-0018D65C",
        "source": "索敵地上",
        "translation": "색적 지상",
        "owners": (0x00FCE234, 0x00FCE238, 0x00FCE23C, 0x00FCE240, 0x00FCE244, 0x00FCE248, 0x00FCE24C, 0x00FCE250, 0x00FCE254, 0x00FCE280, 0x00FCE284, 0x00FCE288),
        "payload_offset": 0x01290240,
        "evidence": "measured ground label and literal tokens E2 5D CE E4 03 BE = 索敵 + 地 + 上",
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
    manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(len(current) == 32 * 1024 * 1024 and sha256(current) == manifest["sha256"], "main TIP/manifest drift")
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
        actual_owners = tuple(int(owner.removeprefix("OWNER-U32-"), 16) for owner in row.get("owner_ids", []))
        gate(actual_owners == patch["owners"], f"{patch['name']} owner drift")
        if patch["record_id"] == "GGA-TEXT-0018D65C":
            gate(row.get("translation_status") == "pending" and not row.get("translation_ko"), "ground record is no longer pending")
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
        row["translator_notes"] = patch["evidence"]
        row["qa_status"] = "runtime_measured_and_8x16_glyph_verified"
        row["overlay_batch_id"] = BATCH_ID
        update_payload_hash(row)
        evidence.append({
            "name": patch["name"], "record_id": patch["record_id"], "before": before,
            "source_text": patch["source"], "translation_ko": patch["translation"], "evidence": patch["evidence"],
            "owner_offsets": [f"0x{owner:08X}" for owner in patch["owners"]],
            "old_active_addresses": [f"0x{address:08X}" for address in sorted(set(old_addresses))],
            "new_address": f"0x{ROM_BASE + at:08X}", "payload_hex": payload.hex(" ").upper(),
            "all_glyphs_painted_both_fonts": True,
        })

    changed = [index for index, (before, after) in enumerate(zip(current, candidate)) if before != after]
    gate(set(changed) <= allowed, "candidate changed outside target owners/payloads")
    parent = str(merged.get("identity", {}).get("translation_overlay_identity_sha256") or "")
    identity = digest({"parent": parent, "batch_id": BATCH_ID, "records": [{"record_id": patch["record_id"], "payload": by_id[patch["record_id"]]["translation_payload_sha256"]} for patch in PATCHES]})
    merged["identity"]["parent_translation_overlay_identity_sha256"] = parent
    merged["identity"]["intermission_measured_corrections_identity_sha256"] = identity
    merged["identity"]["translation_overlay_identity_sha256"] = identity
    counts = dict(sorted(Counter(str(row.get("translation_status") or "") for row in merged["records"]).items()))
    merged["summary"]["merged_translation_status_counts"] = counts
    merged["summary"]["translation_overlay_identity_sha256"] = identity
    merged["intermission_measured_corrections"] = {"batch_id": BATCH_ID, "changed_records": len(PATCHES), "identity_sha256": identity, "static_consumer_report": advance_relative(REPORT)}

    SNAPSHOT.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(candidate)
    report = {
        "schema_version": 1, "kind": "ggen_advance_intermission_measured_corrections_candidate_20260904",
        "source": {"main_tip": advance_relative(MAIN_TIP_ROM), "main_tip_sha256": sha256(current), "translation_source": advance_relative(TRANSLATION_MERGED_JSON)},
        "root_causes": ["The active 8x16 font renders the metadata-approved 진 slot as 짊 on this path.", "0x0818D656 is 索敵宇宙; the actual 索敵地上 record is 0x0818D65C."],
        "consumers": evidence,
        "output": {"path": advance_relative(OUTPUT), "size": len(candidate), "sha256": sha256(candidate)},
        "verification": {"result": "PASS", "parallel_condition_bridge_verified": True, "ground_owner_count": 12, "space_owner_count": 13, "all_output_glyphs_painted_both_fonts": True, "all_target_owners_redirected": True, "only_target_owners_and_zero_cave_mutated": True, "changed_bytes": len(changed), "main_tip_not_modified": sha256(MAIN_TIP_ROM.read_bytes()) == sha256(current)},
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "candidate": advance_relative(OUTPUT), "sha256": sha256(candidate), "changed_bytes": len(changed)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
