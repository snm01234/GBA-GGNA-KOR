#!/usr/bin/env python3
"""Promote 8x16 編 and patch leftover=1 character 前編/後編 names still drawing JP.

ID-command names (129) and unit names (70) that still show Japanese are blocked
by mixed leftover slots (especially 0x0286, which fits 軍 in ジオン公国軍 frames
but also appears in 無…闘 victory lines).  Those stay pending.

0x04DA is leftover=1 in 16 character-name rows only, all NAME前/後X, so 編 is
safe.  Existing sheet glossary supplies the Korean bases.
"""
from __future__ import annotations

import json
import shutil
import struct
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import build_ggen_advance_ko_poc as fontops  # noqa: E402
from ggen_advance_painted_glyph_identity import (  # noqa: E402
    FONT8_RELOCATED,
    gate,
    load_galmuri12,
    load_galmuri8,
    paint_8x16,
    recover_unique_12x12_slots,
    recover_unique_8x16_slots,
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
    ROM_BASE,
    payload_at,
    sha256,
    u32,
)
from build_ggen_advance_unified_rom_poc import collect_live_slots  # noqa: E402

BATCH_ID = "character-zenpen-kouhen-20260904"
CHARMAP = ROOT / "analysis" / "ggen_advance_8x16_charmap_supplement_20260828.json"
SNAPSHOT = ROOT / "analysis" / "ggen_advance_translation_merged_20260904_zenpen_kouhen.json"
OUTPUT = ROOT / "outputs" / "20260904_ggen_advance_zenpen_kouhen" / "ggen_advance_zenpen_kouhen_candidate_20260904.gba"
OUT_SAV = ROOT / "outputs" / "20260904_ggen_advance_zenpen_kouhen" / "ggen_advance_zenpen_kouhen_candidate_20260904.sav"
MAIN_SAV = ROOT / "SD Gundam GGeneration Advance (Korean).sav"
REPORT = ROOT / "analysis" / "ggen_advance_zenpen_kouhen_20260904.json"
CAVE_START = 0x01290300
CAVE_END = 0x01290800
SLOT_HEN = 0x04DA

JP_BASES = {
    "アイナ・サハリン": "아이나 사할린",
    "アムロ・レイ": "아무로 레이",
    "オルバ・フロスト": "올바 프로스트",
    "ギニアス・サハリン": "기니아스 사할린",
    "キラ・ヤマト": "키라 야마토",
    "シャギア・フロスト": "샤기아 프로스트",
    "マリュー・ラミアス": "마류 라미아스",
    "ラウ・ル・クルーゼ": "라우 르 크루제",
}


def owner_offsets(row: dict) -> tuple[int, ...]:
    return tuple(
        int(owner.removeprefix("OWNER-U32-"), 16)
        for owner in row.get("owner_ids", [])
        if str(owner).startswith("OWNER-U32-")
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


def align16(value: int) -> int:
    return (value + 15) & ~15


def promote_hen(charmap: dict) -> None:
    verified = dict(charmap["verified_charmap"])
    current = verified.get("0x04DA")
    gate(current is None or current == "編", f"0x04DA collision: {current}")
    verified["0x04DA"] = "編"
    charmap["verified_charmap"] = {key: verified[key] for key in sorted(verified, key=lambda value: int(value, 16))}
    charmap["combined_slot_count"] = len(verified)
    provenance = charmap.setdefault("added_zenpen_kouhen_20260904", {})
    provenance["0x04DA"] = {
        "to": "編",
        "basis": "leftover=1 character_name only; 16 rows NAME前/後X with no other 8x16 consumer",
    }


def classify_source(source: str) -> tuple[str, str] | None:
    for jp, ko in JP_BASES.items():
        if not source.startswith(jp):
            continue
        if "<<00B8><04DA>>" in source:
            return jp, f"{ko} 전편"
        if "<<029E><04DA>>" in source:
            return jp, f"{ko} 후편"
    return None


def main() -> int:
    original = ORIGINAL_ROM.read_bytes()
    current = MAIN_TIP_ROM.read_bytes()
    manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(len(current) == 32 * 1024 * 1024 and sha256(current) == manifest["sha256"], "main TIP/manifest drift")
    gate(MAIN_SAV.exists(), "current main SAV missing")
    gate(all(value == 0 for value in current[CAVE_START:CAVE_END]), "zenpen/kouhen cave is not zero-filled")

    charmap = json.loads(CHARMAP.read_text(encoding="utf-8"))
    promote_hen(charmap)
    CHARMAP.write_text(json.dumps(charmap, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    patches = []
    for row in merged["records"]:
        if row.get("semantic_category") != "character_name" or row.get("translation_status") != "pending":
            continue
        classified = classify_source(str(row.get("source_text") or ""))
        if not classified:
            continue
        jp, ko = classified
        patches.append({"record_id": row["record_id"], "source_jp": jp, "source": row["source_text"], "translation": ko, "owners": owner_offsets(row)})
    gate(len(patches) == 16, f"expected 16 前編/後編 rows, found {len(patches)}")

    font8 = load_galmuri8()
    font12 = load_galmuri12()
    hangul = set("".join(patch["translation"] for patch in patches)) - {" "}
    recovered12 = recover_unique_12x12_slots(current, font12, hangul)
    missing8 = set()
    recovered8 = {}
    for char in hangul:
        try:
            recovered8.update(recover_unique_8x16_slots(current, font8, {char}))
        except SystemExit:
            missing8.add(char)
    live8, _live12 = collect_live_slots(original, merged["records"])
    candidate = bytearray(current)
    allowed: set[int] = set()
    painted = []
    for char in sorted(missing8):
        slot = recovered12[char]
        gate(slot not in live8, f"cannot paint 8x16 {char!r} at live slot 0x{slot:04X}")
        start = paint_8x16(candidate, slot, char, font8)
        allowed.update(range(start, start + fontops.FONT_8X16_STRIDE))
        painted.append({"char": char, "slot": f"0x{slot:04X}", "file_offset": f"0x{start:08X}"})
        recovered8[char] = slot
    for char in hangul:
        gate(recovered8[char] == recovered12[char], f"8x16/12x12 diverge for {char!r}")
    tokens = tokens_from_recovered(recovered12)

    from ggen_advance_painted_glyph_identity import encode_literal  # noqa: E402

    alloc: dict[str, int] = {}
    cursor = CAVE_START
    written: dict[int, bytes] = {}
    evidence = []
    by_id = {row["record_id"]: row for row in merged["records"]}

    for patch in patches:
        row = by_id[patch["record_id"]]
        owners = patch["owners"]
        gate(owners, f"{patch['record_id']} has no owners")
        orig_raw = bytes.fromhex(str(row["raw_hex"]).replace(" ", ""))
        old_addresses = [u32(current, owner) for owner in owners]
        for owner, address in zip(owners, old_addresses):
            gate(payload_at(current, address) == orig_raw, f"{patch['record_id']} is not original JP")
        payload = encode_literal(patch["translation"], tokens)
        verify_payload_painted(candidate, payload, patch["translation"], font8)
        verify_payload_painted_12x12(candidate, payload, patch["translation"], font12)
        key = patch["translation"]
        if key in alloc:
            at = alloc[key]
            gate(written[at] == payload, "shared payload conflict")
        else:
            at = cursor
            gate(at + len(payload) <= CAVE_END, "cave exhausted")
            gate(all(value == 0 for value in candidate[at : at + len(payload)]), f"cave dirty at 0x{at:08X}")
            candidate[at : at + len(payload)] = payload
            written[at] = payload
            allowed.update(range(at, at + len(payload)))
            alloc[key] = at
            cursor = align16(at + len(payload))
        pointer = ROM_BASE + at
        for owner in owners:
            struct.pack_into("<I", candidate, owner, pointer)
            allowed.update(range(owner, owner + 4))
        gate(all(u32(candidate, owner) == pointer for owner in owners), f"{patch['record_id']} redirect failed")
        before = {key: row.get(key) for key in ("source_text", "source_decode_status", "source_unresolved_slots", "translation_ko", "translation_status")}
        suffix = "前編" if "전편" in patch["translation"] else "後編"
        row["source_text"] = f"{patch['source_jp']}{suffix}"
        row["source_decode_status"] = "complete"
        row["source_unresolved_slots"] = []
        row["baseline_translation_ko"] = patch["translation"]
        row["baseline_translation_status"] = "translated"
        row["translation_ko"] = patch["translation"]
        row["translation_status"] = "translated"
        row["translation_source"] = BATCH_ID
        row["review_status"] = "draft"
        row["review_count"] = int(row.get("review_count") or 0) + 1
        row["reviewed_at"] = "2026-09-04"
        row["translator_notes"] = "8x16 leftover=1 編@0x04DA; 전편/후편. ID커맨드명·기체명은 혼재 슬롯으로 이번 배치에서 제외"
        row["qa_status"] = "painted_glyph_identity_verified"
        row["overlay_batch_id"] = BATCH_ID
        update_payload_hash(row)
        evidence.append(
            {
                "record_id": patch["record_id"],
                "before": before,
                "source_text": row["source_text"],
                "translation_ko": patch["translation"],
                "owner_offsets": [f"0x{owner:08X}" for owner in owners],
                "old_active_addresses": [f"0x{address:08X}" for address in sorted(set(old_addresses))],
                "new_address": f"0x{pointer:08X}",
                "payload_hex": payload.hex(" ").upper(),
            }
        )

    changed = [index for index, (before, after) in enumerate(zip(current, candidate)) if before != after]
    gate(set(changed) <= allowed, "candidate changed outside target owners/payloads/glyphs")
    parent = str(merged.get("identity", {}).get("translation_overlay_identity_sha256") or "")
    identity = digest(
        {
            "parent": parent,
            "batch_id": BATCH_ID,
            "records": [{"record_id": patch["record_id"], "payload": by_id[patch["record_id"]]["translation_payload_sha256"]} for patch in patches],
        }
    )
    merged["identity"]["parent_translation_overlay_identity_sha256"] = parent
    merged["identity"]["zenpen_kouhen_sha256"] = identity
    merged["identity"]["translation_overlay_identity_sha256"] = identity
    counts = dict(sorted(Counter(str(row.get("translation_status") or "") for row in merged["records"]).items()))
    merged["summary"]["merged_translation_status_counts"] = counts
    merged["summary"]["translation_overlay_identity_sha256"] = identity

    SNAPSHOT.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    TRANSLATION_MERGED_JSON.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    update_translation_manifest(merged, SNAPSHOT)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(candidate)
    shutil.copyfile(MAIN_SAV, OUT_SAV)
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_zenpen_kouhen_candidate_20260904",
        "source": {
            "main_tip": advance_relative(MAIN_TIP_ROM),
            "main_tip_sha256": sha256(current),
        },
        "analysis": {
            "id_command_name_pending_still_jp": 129,
            "unit_name_pending_still_jp": 70,
            "id_command_name_readable_closable": 0,
            "unit_name_readable_closable": 0,
            "held_slot_0x0286": "mixed 軍-like unit bios vs 無…闘 condition lines; not promoted",
            "promoted_slot": "0x04DA=編",
        },
        "painted_8x16_to_match_12x12": painted,
        "consumers": evidence,
        "output": {"path": advance_relative(OUTPUT), "size": len(candidate), "sha256": sha256(candidate)},
        "sav": {"path": advance_relative(OUT_SAV), "byte_exact_copy": OUT_SAV.read_bytes() == MAIN_SAV.read_bytes()},
        "verification": {
            "result": "PASS",
            "painted_glyph_identity_verified": True,
            "changed_bytes": len(changed),
            "changed_records": len(patches),
            "main_tip_not_modified": sha256(MAIN_TIP_ROM.read_bytes()) == sha256(current),
        },
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "candidate": advance_relative(OUTPUT), "sha256": sha256(candidate), "changed_bytes": len(changed), "records": len(patches), "painted": painted}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
