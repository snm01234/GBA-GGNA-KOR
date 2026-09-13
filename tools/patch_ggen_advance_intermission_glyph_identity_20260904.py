#!/usr/bin/env python3
"""Fix 8x16 glyph-identity drift on the intermission yellow-window path.

The visible 진→짊 error is 으 encoded to apply-charmap slot 0x018C, whose
relocated 8x16 cell actually still holds 짊.  션 was never painted for 8x16, so
세션 was rewritten to 작전.  索敵地上 stayed Japanese because the parallel
condition owners for GGA-TEXT-0018D65C were never redirected.
"""
from __future__ import annotations

import json
import struct
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from ggen_advance_painted_glyph_identity import (  # noqa: E402
    FONT8_RELOCATED,
    FONT12_RELOCATED,
    audit_apply_charmap_8x16,
    encode_literal,
    gate,
    load_galmuri12,
    load_galmuri8,
    packed_8x16,
    packed_12x12,
    paint_8x16_matching_12x12_slot,
    recover_unique_12x12_slots,
    recover_unique_8x16_slots,
    slot_raw,
    tokens_from_recovered,
    verify_payload_painted,
    verify_payload_painted_12x12,
)
from ggen_advance_project_paths import (  # noqa: E402
    MAIN_TIP_MANIFEST,
    MAIN_TIP_ROM,
    ORIGINAL_ROM,
    TRANSLATION_MANIFEST,
    TRANSLATION_MERGED_JSON,
    advance_relative,
)
from merge_ggen_advance_translation_overlays import digest, translation_payload_digest  # noqa: E402
from patch_ggen_advance_intermission_text_consumers_20260904 import (  # noqa: E402
    DRAW_WRAPPER,
    ROM_BASE,
    bl_target,
    payload_at,
    sha256,
    u32,
)
import build_ggen_advance_ko_poc as fontops  # noqa: E402

BATCH_ID = "intermission-glyph-identity-20260904"
CHARMAP = ROOT / "analysis" / "ggen_advance_korean_apply_charmap_20260844.json"
SNAPSHOT = ROOT / "analysis" / "ggen_advance_translation_merged_20260904_glyph_identity.json"
OUTPUT = ROOT / "outputs" / "20260904_ggen_advance_intermission_glyph_identity" / "ggen_advance_intermission_glyph_identity_candidate_20260904.gba"
REPORT = ROOT / "analysis" / "ggen_advance_intermission_glyph_identity_20260904.json"
SLOT_MAP = ROOT / "analysis" / "ggen_advance_8x16_runtime_slot_map_20260904.json"

ADVANCE_KO = "다음 세션으로 진행합니다"
GROUND_KO = "색적 지상"
SPACE_KO = "색적 우주"
SHION_SAK_COLLISION_SLOT = 0x071E

PATCHES = (
    {
        "name": "advance_direct",
        "record_id": "GGA-TEXT-001BE7CE",
        "source": "次のセッションへ進みます",
        "translation": ADVANCE_KO,
        "owners": (0x0006B008,),
        "payload_offset": 0x01290100,
        "reuse_existing": True,
    },
    {
        "name": "advance_fce128",
        "record_id": "GGA-TEXT-001BE836",
        "source": "次のセッションに進みます",
        "translation": ADVANCE_KO,
        "owners": (0x00FCE130, 0x00FCE15C),
        "payload_offset": 0x01290100,
        "reuse_existing": True,
    },
    {
        "name": "search_space_parallel_condition",
        "record_id": "GGA-TEXT-0018D656",
        "source": "索敵宇宙",
        "translation": SPACE_KO,
        "owners": (0x00FCE230, 0x00FCE258, 0x00FCE25C, 0x00FCE260, 0x00FCE264, 0x00FCE268, 0x00FCE26C, 0x00FCE270, 0x00FCE274, 0x00FCE278, 0x00FCE27C, 0x00FCE28C, 0x00FCE290),
        "payload_offset": 0x01290180,
        "reuse_existing": True,
    },
    {
        "name": "search_ground_parallel_condition",
        "record_id": "GGA-TEXT-0018D65C",
        "source": "索敵地上",
        "translation": GROUND_KO,
        "owners": (0x00FCE234, 0x00FCE238, 0x00FCE23C, 0x00FCE240, 0x00FCE244, 0x00FCE248, 0x00FCE24C, 0x00FCE250, 0x00FCE254, 0x00FCE280, 0x00FCE284, 0x00FCE288),
        "payload_offset": 0x01290070,
        "reuse_existing": True,
    },
    {
        "name": "search_ground_record",
        "record_id": "GGA-TEXT-001BF052",
        "source": "索敵地上",
        "translation": GROUND_KO,
        "owners": (0x00D55D38, 0x00D55D58, 0x00D55D78, 0x00D55D98, 0x00D55DB8, 0x00D55DD8, 0x00D55DF8, 0x00D55E18, 0x00D55E38, 0x00D55F98, 0x00D55FB8, 0x00D55FD8),
        "payload_offset": 0x01290070,
        "reuse_existing": True,
    },
)


def update_payload_hash(row: dict) -> None:
    patch = {
        "record_id": row["record_id"],
        "batch_id": row["overlay_batch_id"],
        "translation_ko": row.get("translation_ko") or "",
        "translation_segments": row.get("translation_segments"),
        "translation_status": row.get("translation_status") or "",
        "translation_source": row.get("translation_source") or "",
        "source_model": row.get("source_model") or "",
        "prompt_version": row.get("prompt_version") or "",
        "review_status": row.get("review_status") or "",
        "review_count": row.get("review_count") or 0,
        "reviewed_at": row.get("reviewed_at") or "",
        "translator_notes": row.get("translator_notes") or "",
        "qa_status": row.get("qa_status") or "",
    }
    row["translation_payload_sha256"] = translation_payload_digest(patch)


def update_translation_manifest(merged: dict, snapshot: Path) -> None:
    manifest = json.loads(TRANSLATION_MANIFEST.read_text(encoding="utf-8"))
    merged_sha = sha256(TRANSLATION_MERGED_JSON.read_bytes())
    counts = dict(sorted(Counter(str(row.get("translation_status") or "") for row in merged["records"]).items()))
    manifest.update(
        {
            "source_snapshot": advance_relative(snapshot),
            "sha256": merged_sha,
            "source_sha256": merged_sha,
            "record_count": len(merged["records"]),
            "record_identity_sha256": merged.get("identity", {}).get("record_identity_sha256"),
            "translation_overlay_identity_sha256": merged.get("identity", {}).get("translation_overlay_identity_sha256"),
            "record_translation_status_counts": counts,
            "source_summary_translation_status_counts": counts,
        }
    )
    TRANSLATION_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    original = ORIGINAL_ROM.read_bytes()
    current = MAIN_TIP_ROM.read_bytes()
    manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(len(current) == 32 * 1024 * 1024 and sha256(current) == manifest["sha256"], "main TIP/manifest drift")
    gate(u32(original, 0x0006B170) == 0x08FCE1A0, "parallel condition table literal drift")
    gate(bl_target(original, 0x0006AFD2) == 0x0806B148 and bl_target(original, 0x0006B3DE) == 0x0806B148, "parallel condition bridge drift")
    gate(bl_target(original, 0x0006AFE0) == DRAW_WRAPPER and bl_target(original, 0x0006B3EC) == DRAW_WRAPPER, "parallel condition draw drift")

    apply = json.loads(CHARMAP.read_text(encoding="utf-8"))
    font8 = load_galmuri8()
    font12 = load_galmuri12()
    audit = audit_apply_charmap_8x16(current, original, apply, font8)
    gate(audit["mismatch_count"] >= 1, "expected 8x16 metadata/paint drift was already gone")
    eu_mismatch = next((row for row in audit["mismatches"] if row["char"] == "으"), None)
    gate(eu_mismatch is not None and eu_mismatch.get("painted_as") == "짊", "으→짊 drift is no longer present")

    needed = set("".join(patch["translation"] for patch in PATCHES)) - {" "}
    recovered12 = recover_unique_12x12_slots(current, font12, needed)
    gate(recovered12["션"] != SHION_SAK_COLLISION_SLOT, "12x12 션 recovered onto the 삭 slot")
    gate(
        slot_raw(current, FONT12_RELOCATED, SHION_SAK_COLLISION_SLOT, fontops.FONT_12X12_STRIDE) == packed_12x12("삭", font12),
        "0x071E is no longer 12x12 삭; 세삭 collision diagnosis drifted",
    )
    painted_8x16_chars = {char for char in needed if char != "션"}
    recovered8 = recover_unique_8x16_slots(current, font8, painted_8x16_chars)
    for char, slot in recovered8.items():
        gate(slot == recovered12[char], f"8x16/12x12 recovered slots diverge for {char!r}: 0x{slot:04X} vs 0x{recovered12[char]:04X}")
    recovered = dict(recovered12)
    candidate = bytearray(current)
    allowed: set[int] = set()
    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    shion_slot = recovered["션"]
    shion_start = paint_8x16_matching_12x12_slot(candidate, original, merged["records"], shion_slot, "션", font8)
    if shion_start is not None:
        allowed.update(range(shion_start, shion_start + fontops.FONT_8X16_STRIDE))

    tokens = tokens_from_recovered(recovered)
    gate(slot_raw(candidate, FONT8_RELOCATED, recovered["으"], fontops.FONT_8X16_STRIDE) == packed_8x16("으", font8), "recovered 으 slot is not 으")
    gate(recovered["으"] != int("0x018C", 16), "encoder still using the drifted 으 metadata slot")
    gate(recovered["지"] != int("0x019B", 16), "encoder still using the drifted 지 metadata slot")
    gate(recovered["션"] != SHION_SAK_COLLISION_SLOT, "encoder still using 12x12 삭 slot for 션")
    by_id = {row["record_id"]: row for row in merged["records"]}
    written: dict[int, bytes] = {}
    evidence = []

    for patch in PATCHES:
        row = by_id[patch["record_id"]]
        actual_owners = tuple(int(owner.removeprefix("OWNER-U32-"), 16) for owner in row.get("owner_ids", []))
        gate(actual_owners == patch["owners"], f"{patch['name']} owner drift")
        payload = encode_literal(patch["translation"], tokens)
        verify_payload_painted(candidate, payload, patch["translation"], font8)
        verify_payload_painted_12x12(candidate, payload, patch["translation"], font12)
        at = patch["payload_offset"]
        if at in written:
            gate(written[at] == payload, f"shared payload conflict at 0x{at:08X}")
        else:
            if patch.get("reuse_existing"):
                gate(current[at] != 0 or any(current[at : at + len(payload)]), f"{patch['name']} expected an existing payload")
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
        verify_payload_painted(candidate, payload_at(candidate, ROM_BASE + at), patch["translation"], font8)
        verify_payload_painted_12x12(candidate, payload_at(candidate, ROM_BASE + at), patch["translation"], font12)

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
        row["translator_notes"] = "원문 セッション을 세션으로 복원. 노란 창은 12x12이므로 션은 0x0473(삭 슬롯 0x071E 금지). 페인트된 글리프로 인코드하고 8x16/12x12 모두 검증"
        row["qa_status"] = "painted_glyph_identity_verified"
        row["overlay_batch_id"] = BATCH_ID
        update_payload_hash(row)
        evidence.append(
            {
                "name": patch["name"],
                "record_id": patch["record_id"],
                "before": before,
                "source_text": patch["source"],
                "translation_ko": patch["translation"],
                "owner_offsets": [f"0x{owner:08X}" for owner in patch["owners"]],
                "old_active_addresses": [f"0x{address:08X}" for address in sorted(set(old_addresses))],
                "new_address": f"0x{ROM_BASE + at:08X}",
                "payload_hex": payload.hex(" ").upper(),
                "tokens": {char: f"0x{tokens[char]:04X}" for char in patch["translation"] if char != " "},
            }
        )

    changed = [index for index, (before, after) in enumerate(zip(current, candidate)) if before != after]
    gate(set(changed) <= allowed, "candidate changed outside target owners/payloads/glyph")
    parent = str(merged.get("identity", {}).get("translation_overlay_identity_sha256") or "")
    identity = digest(
        {
            "parent": parent,
            "batch_id": BATCH_ID,
            "records": [{"record_id": patch["record_id"], "payload": by_id[patch["record_id"]]["translation_payload_sha256"]} for patch in PATCHES],
        }
    )
    merged["identity"]["parent_translation_overlay_identity_sha256"] = parent
    merged["identity"]["intermission_glyph_identity_sha256"] = identity
    merged["identity"]["translation_overlay_identity_sha256"] = identity
    counts = dict(sorted(Counter(str(row.get("translation_status") or "") for row in merged["records"]).items()))
    merged["summary"]["merged_translation_status_counts"] = counts
    merged["summary"]["translation_overlay_identity_sha256"] = identity
    merged["intermission_glyph_identity"] = {
        "batch_id": BATCH_ID,
        "changed_records": len(PATCHES),
        "identity_sha256": identity,
        "static_consumer_report": advance_relative(REPORT),
    }

    SNAPSHOT.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    TRANSLATION_MERGED_JSON.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    update_translation_manifest(merged, SNAPSHOT)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(candidate)
    slot_map = {
        "schema_version": 1,
        "kind": "ggen_advance_8x16_runtime_slot_map",
        "source_rom_sha256": sha256(current),
        "policy": "recover unique painted Galmuri11-Condensed glyphs; paint missing Hangul onto audited-free 8x16 slots",
        "recovered_slots": {char: f"0x{slot:04X}" for char, slot in recovered.items()},
        "recovered_tokens": {char: f"0x{token:04X}" for char, token in tokens.items()},
        "shion_slot": f"0x{shion_slot:04X}" if shion_slot is not None else None,
        "shion_file_offset": f"0x{shion_start:08X}" if shion_start is not None else None,
        "apply_charmap_8x16_mismatches": audit["mismatch_count"],
    }
    SLOT_MAP.write_text(json.dumps(slot_map, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_intermission_glyph_identity_candidate_20260904",
        "source": {
            "main_tip": advance_relative(MAIN_TIP_ROM),
            "main_tip_sha256": sha256(current),
            "translation_source": advance_relative(TRANSLATION_MERGED_JSON),
        },
        "root_causes": [
            "Relocated fonts and apply-charmap 20260844 have Hangul slot mismatches; 으 metadata 0x018C paints 짊 on both fonts.",
            "The yellow window is 12x12. Painting 션 only onto free 8x16 slot 0x071E made 12x12 draw 삭 (세삭).",
            "션 is already unique at 12x12 slot 0x0473; 8x16 must share that slot, not a 12x12-live Hangul cell.",
            "Yellow-window 索敵地上 is GGA-TEXT-0018D65C / FCE1A0, not the 索敵宇宙 record 0x0818D656.",
        ],
        "prevention": {
            "encoder": "tools/ggen_advance_painted_glyph_identity.py",
            "rule": "Recover unique painted slots per font; shared payloads must verify both 8x16 and 12x12; never steal a 12x12 Hangul cell for an 8x16-only paint",
            "runtime_slot_map": advance_relative(SLOT_MAP),
        },
        "consumers": evidence,
        "output": {"path": advance_relative(OUTPUT), "size": len(candidate), "sha256": sha256(candidate)},
        "verification": {
            "result": "PASS",
            "painted_glyph_identity_verified": True,
            "all_target_owners_redirected": True,
            "only_target_owners_payloads_and_new_glyph_mutated": True,
            "changed_bytes": len(changed),
            "main_tip_not_modified": sha256(MAIN_TIP_ROM.read_bytes()) == sha256(current),
            "apply_charmap_8x16_mismatch_count": audit["mismatch_count"],
            "recovered_eu_slot": f"0x{recovered['으']:04X}",
            "recovered_ji_slot": f"0x{recovered['지']:04X}",
            "shion_slot": f"0x{shion_slot:04X}",
        },
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "candidate": advance_relative(OUTPUT), "sha256": sha256(candidate), "changed_bytes": len(changed), "shion_slot": f"0x{shion_slot:04X}"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
