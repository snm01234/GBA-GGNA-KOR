#!/usr/bin/env python3
"""Translate leftover 8x16 ID-command name / empty-slot / chest-missile text.

Current-main Korean.ss6 still draws Japanese for:

- ID-command name ``「ECM最大強度!」`` (pending leftover=1 ``度`` at 0x047E)
- empty-row fallback ``未修得`` (direct-PC literal GGA-TEXT-001BE74E)
- weapon name ``胸部ミサイル`` (pending leftover ``部`` at mixed slot 0x0515)

These are ordinary NUL 8x16 streams, not graphic tiles.  Korean payloads are
encoded from painted Hangul identity plus the reviewed 8x16 punctuation/Latin
map, written into a zero-filled expansion cave, and OWNER-U32 pointers are
redirected.  Original JP bytes stay in place.

``一斉射撃`` / 일제사격 is excluded in this batch; that identification is not
closed.  Slot 0x0515 is not promoted (weapon ``胸部`` vs unit-name frame
disagreement).  Slot 0x047E=度 is promoted because both leftover=1 frames agree.
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

import build_ggen_advance_ko_poc as fontops  # noqa: E402
import build_ggen_advance_unified_rom_poc as unified  # noqa: E402
from ggen_advance_painted_glyph_identity import (  # noqa: E402
    FONT8_RELOCATED,
    FONT12_RELOCATED,
    gate,
    load_galmuri12,
    load_galmuri8,
    packed_8x16,
    packed_12x12,
    paint_8x16,
    recover_unique_12x12_slots,
    recover_unique_8x16_slots,
    slot_raw,
    token_from_slot,
    verify_payload_painted,
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

BATCH_ID = "idcmd-ecm-mishudeuk-chest-missile-20260905"
CHARMAP = ROOT / "analysis" / "ggen_advance_8x16_charmap_supplement_20260828.json"
SNAPSHOT = ROOT / "analysis" / "ggen_advance_translation_merged_20260905_idcmd_ecm_mishudeuk.json"
OUT_DIR = ROOT / "outputs" / "20260905_ggen_advance_idcmd_ecm_mishudeuk"
OUTPUT = OUT_DIR / "ggen_advance_idcmd_ecm_mishudeuk_candidate_20260905.gba"
OUT_SAV = OUT_DIR / "ggen_advance_idcmd_ecm_mishudeuk_candidate_20260905.sav"
MAIN_SAV = ROOT / "SD Gundam GGeneration Advance (Korean).sav"
REPORT = ROOT / "analysis" / "ggen_advance_idcmd_ecm_mishudeuk_candidate_20260905.json"
CAVE_START = 0x01304000
CAVE_END = 0x01304800
SLOT_DO = 0x047E
EXCLUDED_RECORD_ID = "GGA-TEXT-0017A707"

PATCHES: tuple[dict[str, Any], ...] = (
    {
        "record_id": "GGA-TEXT-0017C9A8",
        "source_jp": "「ECM最大強度！」",
        "translation": "「ECM최대강도!」",
        "owner_count": 1,
        "notes": "8x16 leftover=1 度@0x047E; ID커맨드 목록명. 괄호는 원문 「」 유지",
    },
    {
        "record_id": "GGA-TEXT-001BE74E",
        "source_jp": "未修得",
        "translation": "미습득",
        "owner_count": 2,
        "notes": "empty ID-command row fallback (未=0x055A 修=0x033F 得=0x049E). 未/得는 다른 프레임과 공유라 슬롯 승격 없음",
    },
    {
        "record_id": "GGA-TEXT-00179F7B",
        "source_jp": "胸部ミサイル",
        "translation": "흉부미사일",
        "owner_count": 15,
        "notes": "무기명 胸部ミサイル. 0x0515는 unit_name_alternate와 불일치라 슬롯 승격 없음",
    },
)


def owner_offsets(row: dict[str, Any]) -> tuple[int, ...]:
    return tuple(
        int(owner.removeprefix("OWNER-U32-"), 16)
        for owner in row.get("owner_ids", [])
        if str(owner).startswith("OWNER-U32-")
    )


def update_payload_hash(row: dict[str, Any]) -> None:
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


def update_translation_manifest(merged: dict[str, Any], snapshot: Path) -> None:
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


def hangul_chars(text: str) -> set[str]:
    return {char for char in text if "가" <= char <= "힣"}


def verified_from_charmap(payload: dict[str, Any]) -> dict[str, int]:
    result: dict[str, int] = {}
    for slot_text, char in payload.get("verified_charmap", {}).items():
        if not isinstance(char, str) or not char:
            continue
        slot = int(str(slot_text), 16)
        previous = result.get(char)
        if previous is None or slot < previous:
            result[char] = slot
    return result


def promote_do(charmap: dict[str, Any]) -> None:
    verified = dict(charmap["verified_charmap"])
    current = verified.get("0x047E")
    gate(current is None or current == "度", f"0x047E collision: {current}")
    verified["0x047E"] = "度"
    charmap["verified_charmap"] = {key: verified[key] for key in sorted(verified, key=lambda value: int(value, 16))}
    charmap["combined_slot_count"] = len(verified)
    provenance = charmap.setdefault("added_idcmd_ecm_mishudeuk_20260905", {})
    provenance["0x047E"] = {
        "to": "度",
        "basis": "leftover=1 id_command_name only; 強度 and 度胸 frames agree",
    }


def tokens_for_text(hangul_slots: dict[str, int], verified8: dict[str, int], text: str) -> dict[str, int]:
    tokens: dict[str, int] = {char: token_from_slot(slot) for char, slot in hangul_slots.items()}
    for char in text:
        if char == " " or char in tokens:
            continue
        slot = unified.verified_slot_for(char, verified8)
        gate(slot is not None, f"no reviewed 8x16 slot for {char!r}")
        tokens[char] = token_from_slot(slot)
    return tokens


def verify_mixed_8x16(
    rom: bytes | bytearray,
    original: bytes,
    payload: bytes,
    text: str,
    font8: Any,
    hangul: set[str],
    verified8: dict[str, int],
) -> None:
    expected = [char for char in text if char != " "]
    index = 0
    seen = 0
    while index < len(payload):
        value = payload[index]
        if value == 0:
            break
        if value == 1:
            index += 1
            continue
        if value >= 0xE0:
            token = (value << 8) | payload[index + 1]
            slot = (token + 0x20E0) & 0xFFFF
            index += 2
        else:
            slot = value
            index += 1
        gate(seen < len(expected), f"payload has extra glyph beyond {text!r}")
        char = expected[seen]
        actual = slot_raw(rom, FONT8_RELOCATED, slot, fontops.FONT_8X16_STRIDE)
        if char in hangul:
            gate(actual == packed_8x16(char, font8), f"8x16 painted glyph for {char!r} is not at slot 0x{slot:04X}")
        else:
            mapped = unified.verified_slot_for(char, verified8)
            gate(mapped == slot, f"8x16 compatibility {char!r} encoded at 0x{slot:04X}, expected 0x{mapped:04X}")
            native = slot_raw(original, fontops.FONT_8X16_BASE, slot, fontops.FONT_8X16_STRIDE)
            gate(actual == native, f"8x16 compatibility slot 0x{slot:04X} for {char!r} was overpainted")
        seen += 1
    gate(seen == len(expected), f"payload missing glyphs for {text!r}")


def verify_hangul_12x12(rom: bytes | bytearray, hangul_slots: dict[str, int], font12: Any) -> None:
    for char, slot in hangul_slots.items():
        actual = slot_raw(rom, FONT12_RELOCATED, slot, fontops.FONT_12X12_STRIDE)
        gate(actual == packed_12x12(char, font12), f"12x12 painted glyph for {char!r} is not at slot 0x{slot:04X}")


def main() -> int:
    original = ORIGINAL_ROM.read_bytes()
    current = MAIN_TIP_ROM.read_bytes()
    manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(len(current) == 32 * 1024 * 1024 and sha256(current) == manifest["sha256"], "main TIP/manifest drift")
    gate(MAIN_SAV.exists(), "current main SAV missing")
    gate(all(value == 0 for value in current[CAVE_START:CAVE_END]), "idcmd ecm cave is not zero-filled")

    charmap = json.loads(CHARMAP.read_text(encoding="utf-8"))
    promote_do(charmap)
    verified8 = verified_from_charmap(charmap)

    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    by_id = {row["record_id"]: row for row in merged["records"]}
    excluded = by_id[EXCLUDED_RECORD_ID]
    excluded_owners = owner_offsets(excluded)
    excluded_before = {owner: u32(current, owner) for owner in excluded_owners}

    patches: list[dict[str, Any]] = []
    for spec in PATCHES:
        row = by_id[spec["record_id"]]
        gate(not unified.uses_12x12(row), f"{spec['record_id']} is classified 12x12")
        gate(row.get("translation_status") == "pending", f"{spec['record_id']} is not pending")
        gate(row.get("translation_policy") == "translate", f"{spec['record_id']} policy is not translate")
        owners = owner_offsets(row)
        gate(len(owners) == spec["owner_count"], f"{spec['record_id']} owner count drift")
        patches.append({**spec, "owners": owners, "row": row})

    font8 = load_galmuri8()
    font12 = load_galmuri12()
    hangul = set().union(*(hangul_chars(patch["translation"]) for patch in patches))
    recovered12 = recover_unique_12x12_slots(current, font12, hangul)
    missing8: set[str] = set()
    recovered8: dict[str, int] = {}
    for char in hangul:
        try:
            recovered8.update(recover_unique_8x16_slots(current, font8, {char}))
        except SystemExit:
            missing8.add(char)
    live8, _live12 = unified.collect_live_slots(original, merged["records"])
    candidate = bytearray(current)
    allowed: set[int] = set()
    painted: list[dict[str, str]] = []
    for char in sorted(missing8):
        slot = recovered12[char]
        gate(slot not in live8, f"cannot paint 8x16 {char!r} at live slot 0x{slot:04X}")
        start = paint_8x16(candidate, slot, char, font8)
        allowed.update(range(start, start + fontops.FONT_8X16_STRIDE))
        painted.append({"char": char, "slot": f"0x{slot:04X}", "file_offset": f"0x{start:08X}"})
        recovered8[char] = slot
    for char in hangul:
        gate(recovered8[char] == recovered12[char], f"8x16/12x12 diverge for {char!r}")
    verify_hangul_12x12(candidate, recovered8, font12)

    alloc: dict[str, int] = {}
    cursor = CAVE_START
    written: dict[int, bytes] = {}
    evidence: list[dict[str, Any]] = []

    for patch in patches:
        row = patch["row"]
        owners = patch["owners"]
        orig_raw = bytes.fromhex(str(row["raw_hex"]).replace(" ", ""))
        old_addresses = [u32(current, owner) for owner in owners]
        for owner, address in zip(owners, old_addresses):
            gate(payload_at(current, address) == orig_raw, f"{patch['record_id']} is not original JP")
        tokens = tokens_for_text(recovered8, verified8, patch["translation"])
        payload = bytearray()
        for char in patch["translation"]:
            if char == " ":
                payload.append(0x01)
                continue
            token = tokens[char]
            if token <= 0xDF:
                payload.append(token)
            else:
                payload.extend((token >> 8, token & 0xFF))
        payload.append(0)
        payload_bytes = bytes(payload)
        verify_mixed_8x16(candidate, original, payload_bytes, patch["translation"], font8, hangul, verified8)
        hangul_only = "".join(char for char in patch["translation"] if char in hangul)
        if hangul_only:
            hangul_payload = bytearray()
            for char in hangul_only:
                token = token_from_slot(recovered8[char])
                if token <= 0xDF:
                    hangul_payload.append(token)
                else:
                    hangul_payload.extend((token >> 8, token & 0xFF))
            hangul_payload.append(0)
            verify_payload_painted(candidate, bytes(hangul_payload), hangul_only, font8)

        key = patch["translation"]
        if key in alloc:
            at = alloc[key]
            gate(written[at] == payload_bytes, "shared payload conflict")
        else:
            at = cursor
            gate(at + len(payload_bytes) <= CAVE_END, "cave exhausted")
            gate(all(value == 0 for value in candidate[at : at + len(payload_bytes)]), f"cave dirty at 0x{at:08X}")
            candidate[at : at + len(payload_bytes)] = payload_bytes
            written[at] = payload_bytes
            allowed.update(range(at, at + len(payload_bytes)))
            alloc[key] = at
            cursor = align16(at + len(payload_bytes))
        pointer = ROM_BASE + at
        for owner in owners:
            struct.pack_into("<I", candidate, owner, pointer)
            allowed.update(range(owner, owner + 4))
        gate(all(u32(candidate, owner) == pointer for owner in owners), f"{patch['record_id']} redirect failed")
        gate(payload_at(candidate, pointer) == payload_bytes, f"{patch['record_id']} payload write failed")
        verify_mixed_8x16(candidate, original, payload_at(candidate, pointer), patch["translation"], font8, hangul, verified8)

        before = {
            key: row.get(key)
            for key in ("source_text", "source_decode_status", "source_unresolved_slots", "translation_ko", "translation_status")
        }
        row["source_text"] = patch["source_jp"]
        row["source_decode_status"] = "complete"
        row["source_unresolved_slots"] = []
        row["baseline_translation_ko"] = patch["translation"]
        row["baseline_translation_status"] = "translated"
        row["translation_ko"] = patch["translation"]
        row["translation_status"] = "translated"
        row["translation_source"] = BATCH_ID
        row["review_status"] = "draft"
        row["review_count"] = int(row.get("review_count") or 0) + 1
        row["reviewed_at"] = "2026-09-05"
        row["translator_notes"] = patch["notes"]
        row["qa_status"] = "painted_glyph_identity_verified"
        row["overlay_batch_id"] = BATCH_ID
        update_payload_hash(row)
        evidence.append(
            {
                "record_id": patch["record_id"],
                "before": before,
                "source_text": row["source_text"],
                "translation_ko": row["translation_ko"],
                "owner_offsets": [f"0x{owner:08X}" for owner in owners],
                "old_active_addresses": [f"0x{address:08X}" for address in sorted(set(old_addresses))],
                "new_address": f"0x{pointer:08X}",
                "payload_hex": payload_bytes.hex(" ").upper(),
            }
        )

    for owner, address in excluded_before.items():
        gate(u32(candidate, owner) == address, f"{EXCLUDED_RECORD_ID} owner was rewritten")

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
    merged["identity"]["idcmd_ecm_mishudeuk_sha256"] = identity
    merged["identity"]["translation_overlay_identity_sha256"] = identity
    counts = dict(sorted(Counter(str(row.get("translation_status") or "") for row in merged["records"]).items()))
    merged["summary"]["merged_translation_status_counts"] = counts
    merged["summary"]["translation_overlay_identity_sha256"] = identity

    CHARMAP.write_text(json.dumps(charmap, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    SNAPSHOT.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    TRANSLATION_MERGED_JSON.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    update_translation_manifest(merged, SNAPSHOT)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(candidate)
    shutil.copyfile(MAIN_SAV, OUT_SAV)
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_idcmd_ecm_mishudeuk_candidate_20260905",
        "source": {
            "main_tip": advance_relative(MAIN_TIP_ROM),
            "main_tip_sha256": sha256(current),
        },
        "analysis": {
            "excluded_record_id": EXCLUDED_RECORD_ID,
            "excluded_reason": "일제사격/一斉射撃 추정은 사용자 지시로 이번 배치에서 제외",
            "promoted_slot": "0x047E=度",
            "held_slot_0x0515": "weapon 胸部 vs unit_name_alternate frame disagreement; not promoted",
            "empty_slot_is_not_inactive_placeholder": "GGA-TEXT-001BE74E id_command_row_fallback, not the 668 preserve dummy streams",
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
            "excluded_record_untouched": True,
            "main_tip_not_modified": sha256(MAIN_TIP_ROM.read_bytes()) == sha256(current),
        },
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "result": "PASS",
                "candidate": advance_relative(OUTPUT),
                "sha256": sha256(candidate),
                "changed_bytes": len(changed),
                "records": [patch["record_id"] for patch in patches],
                "translations": [patch["translation"] for patch in patches],
                "painted": painted,
                "excluded": EXCLUDED_RECORD_ID,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
