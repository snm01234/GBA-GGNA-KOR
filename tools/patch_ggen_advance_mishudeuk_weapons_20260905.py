#!/usr/bin/env python3
"""Retarget missed 未修得 draw literals and translate the 15 pending weapons.

The previous candidate redirected only the two corpus owners
``0x0001F4A8`` / ``0x0006C53C``.  Live empty ID-command rows still load
``0x081BE74E`` from extra PC-literal pools at ``0x0001FF74`` (draw x=8) and
``0x0003A9B4``.  Character-DB name fields are NULL (337 zeros), so those
fallbacks are the on-screen 未修得 path.

Weapon names are identified from sibling armaments on the same entity, not
from mixed 12x12 leftover frames.  Slots are not globally promoted.
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
    FONT12_RELOCATED,
    load_galmuri12,
    load_galmuri8,
    packed_12x12,
    paint_8x16,
    recover_unique_12x12_slots,
    recover_unique_8x16_slots,
    slot_raw,
    token_from_slot,
    verify_payload_painted,
)
from ggen_advance_project_paths import (  # noqa: E402
    MAIN_TIP_ROM,
    ORIGINAL_ROM,
    TRANSLATION_MERGED_JSON,
    advance_relative,
)
from merge_ggen_advance_translation_overlays import digest  # noqa: E402
from patch_ggen_advance_idcmd_ecm_mishudeuk_20260905 import (  # noqa: E402
    CHARMAP,
    align16,
    hangul_chars,
    owner_offsets,
    tokens_for_text,
    update_payload_hash,
    update_translation_manifest,
    verified_from_charmap,
    verify_hangul_12x12,
    verify_mixed_8x16,
)
from patch_ggen_advance_intermission_text_consumers_20260904 import (  # noqa: E402
    ROM_BASE,
    gate,
    payload_at,
    sha256,
    u32,
)

BATCH_ID = "idcmd-mishudeuk-extra-pending-weapons-20260905"
PARENT = ROOT / "outputs" / "20260905_ggen_advance_idcmd_ecm_mishudeuk" / "ggen_advance_idcmd_ecm_mishudeuk_candidate_20260905.gba"
PARENT_SHA = "e6e134767363b7859bceb3355613c749ac4b9e94d2dbada4215e3d70b36cb3cb"
SNAPSHOT = ROOT / "analysis" / "ggen_advance_translation_merged_20260905_mishudeuk_weapons.json"
OUT_DIR = ROOT / "outputs" / "20260905_ggen_advance_mishudeuk_weapons"
OUTPUT = OUT_DIR / "ggen_advance_mishudeuk_weapons_candidate_20260905.gba"
OUT_SAV = OUT_DIR / "ggen_advance_mishudeuk_weapons_candidate_20260905.sav"
MAIN_SAV = ROOT / "SD Gundam GGeneration Advance (Korean).sav"
REPORT = ROOT / "analysis" / "ggen_advance_mishudeuk_weapons_candidate_20260905.json"
CAVE_START = 0x01304040
CAVE_END = 0x01304800
MISHUDEUK_KO = 0x09304020
EXTRA_OWNERS = (0x0001FF74, 0x0003A9B4)
FALLBACK_RECORD = "GGA-TEXT-001BE74E"
ORIG_WEIXIU = 0x081BE74E

PATCHES: tuple[dict[str, Any], ...] = (
    {"record_id": "GGA-TEXT-00179E89", "source_jp": "岩投げ", "translation": "바위던지기", "owner_count": 3, "notes": "자쿠II 도안기 slot1; slot0=격투. 원작 岩投げ"},
    {"record_id": "GGA-TEXT-00179F5A", "source_jp": "ヒート剣", "translation": "히트 검", "owner_count": 12, "notes": "돔/구프커스텀 계열; glossary ヒート剣. 히트서벨은 별 레코드"},
    {"record_id": "GGA-TEXT-0017A061", "source_jp": "狙撃", "translation": "저격", "owner_count": 3, "notes": "겔구그JG slot2; 빔머신건·빔사벨 다음 Jäger 저격"},
    {"record_id": "GGA-TEXT-0017A1C9", "source_jp": "Iフィールド", "translation": "I필드", "owner_count": 2, "notes": "GP03 덴드로비움 2글자 잔여. 메가빔포·폭도삭·미사일과 형제"},
    {"record_id": "GGA-TEXT-0017A1D9", "source_jp": "爆導索", "translation": "폭도삭", "owner_count": 2, "notes": "GP03 덴드로비움 MAP 爆導索, 索로 끝"},
    {"record_id": "GGA-TEXT-0017A3D1", "source_jp": "電磁ボルト", "translation": "전자 볼트", "owner_count": 2, "notes": "풀아머 백식 개량형 4번째, …ボルト"},
    {"record_id": "GGA-TEXT-0017A513", "source_jp": "大口径ビームカノン", "translation": "대구경 빔 캐논", "owner_count": 2, "notes": "S건담; 大口径ビームカノン. 슬롯 0x025F 미승격"},
    {"record_id": "GGA-TEXT-0017A5CB", "source_jp": "十二王方牌大車輪", "translation": "십이왕방패대차휠", "owner_count": 2, "notes": "쿠롱건담; 二/方/大/輪 고정. 비기 十二王方牌大車輪. 륜은 12x12 미페인트라 휠 사용"},
    {"record_id": "GGA-TEXT-0017A5D9", "source_jp": "石破天驚拳", "translation": "석파천경권", "owner_count": 2, "notes": "쿠롱건담; 破·驚 기지. 석파천경권"},
    {"record_id": "GGA-TEXT-0017A5E4", "source_jp": "超級覇王電影弾", "translation": "초급패왕전영탄", "owner_count": 2, "notes": "쿠롱건담 7자+弾; 超級覇王電影弾"},
    {"record_id": "GGA-TEXT-0017A707", "source_jp": "全弾発射", "translation": "전탄발사", "owner_count": 2, "notes": "프리덤; 全…射. 일제사격(一斉射撃)이 아니라 Full Burst 전탄발사"},
    {"record_id": "GGA-TEXT-0017A756", "source_jp": "射撃ウェポン・ユニット", "translation": "사격 웨폰 유닛", "owner_count": 2, "notes": "그롬린 포실; …撃ウェポン・유닛. 유선헤드빔·가변메가입자포와 형제"},
    {"record_id": "GGA-TEXT-0017ACC9", "source_jp": "覇王電影弾", "translation": "패왕전영탄", "owner_count": 1, "notes": "동방불패; 쿠롱 7자의 뒤 5자 覇王電影弾"},
    {"record_id": "GGA-TEXT-0017AD25", "source_jp": "主砲", "translation": "주포", "owner_count": 2, "notes": "화이트베이스/페가수스 X砲. glossary 主砲"},
    {"record_id": "GGA-TEXT-0017ADC2", "source_jp": "加速砲", "translation": "가속포", "owner_count": 1, "notes": "알마이어 加X砲. glossary 加速砲. 슬롯 0x0409 미승격"},
)


def encode_text(text: str, hangul_slots: dict[str, int], verified8: dict[str, int]) -> bytes:
    tokens = tokens_for_text(hangul_slots, verified8, text)
    payload = bytearray()
    for char in text:
        if char == " ":
            payload.append(0x01)
            continue
        token = tokens[char]
        if token <= 0xDF:
            payload.append(token)
        else:
            payload.extend((token >> 8, token & 0xFF))
    payload.append(0)
    return bytes(payload)


def main() -> int:
    original = ORIGINAL_ROM.read_bytes()
    parent = PARENT.read_bytes()
    gate(sha256(parent) == PARENT_SHA, "parent candidate drift")
    gate(MAIN_SAV.exists(), "current main SAV missing")
    gate(all(value == 0 for value in parent[CAVE_START:CAVE_END]), "weapon cave is not zero-filled")
    gate(u32(parent, 0x0001F4A8) == MISHUDEUK_KO, "previous 미습득 owner 0x1F4A8 drift")
    gate(u32(parent, 0x0006C53C) == MISHUDEUK_KO, "previous 미습득 owner 0x6C53C drift")
    for owner in EXTRA_OWNERS:
        gate(u32(parent, owner) == ORIG_WEIXIU, f"extra 未修得 owner 0x{owner:08X} is not original JP")
        gate(payload_at(parent, ORIG_WEIXIU) == bytes.fromhex("E4 7A E2 5F E3 BE 00"), "original 未修得 payload drift")

    charmap = json.loads(CHARMAP.read_text(encoding="utf-8"))
    verified8 = verified_from_charmap(charmap)
    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    by_id = {row["record_id"]: row for row in merged["records"]}

    fallback = by_id[FALLBACK_RECORD]
    gate(fallback.get("translation_ko") == "미습득", "미습득 record was not in previous overlay")

    patches: list[dict[str, Any]] = []
    for spec in PATCHES:
        row = by_id[spec["record_id"]]
        gate(not unified.uses_12x12(row), f"{spec['record_id']} is classified 12x12")
        gate(row.get("translation_status") == "pending", f"{spec['record_id']} is not pending")
        owners = owner_offsets(row)
        gate(len(owners) == spec["owner_count"], f"{spec['record_id']} owner count drift")
        patches.append({**spec, "owners": owners, "row": row})

    font8 = load_galmuri8()
    font12 = load_galmuri12()
    hangul = set().union(*(hangul_chars(patch["translation"]) for patch in patches))
    recovered12 = recover_unique_12x12_slots(parent, font12, hangul)
    missing8: set[str] = set()
    recovered8: dict[str, int] = {}
    for char in hangul:
        try:
            recovered8.update(recover_unique_8x16_slots(parent, font8, {char}))
        except SystemExit:
            missing8.add(char)
    live8, _live12 = unified.collect_live_slots(original, merged["records"])
    candidate = bytearray(parent)
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

    for owner in EXTRA_OWNERS:
        struct.pack_into("<I", candidate, owner, MISHUDEUK_KO)
        allowed.update(range(owner, owner + 4))
    gate(all(u32(candidate, owner) == MISHUDEUK_KO for owner in EXTRA_OWNERS), "extra 未修得 redirect failed")
    extra_ids = [f"OWNER-U32-{owner:08X}" for owner in EXTRA_OWNERS]
    owners_now = list(fallback.get("owner_ids") or [])
    for extra in extra_ids:
        if extra not in owners_now:
            owners_now.append(extra)
    fallback["owner_ids"] = owners_now
    fallback["owner_count"] = len(owners_now)
    fallback["translator_notes"] = (
        "empty ID-command row fallback 未修得. extra PC-literals 0x1FF74/0x3A9B4 "
        "still pointed at 0x081BE74E after the first candidate"
    )
    update_payload_hash(fallback)

    alloc: dict[str, int] = {}
    cursor = CAVE_START
    written: dict[int, bytes] = {}
    evidence: list[dict[str, Any]] = []

    for patch in patches:
        row = patch["row"]
        owners = patch["owners"]
        orig_raw = bytes.fromhex(str(row["raw_hex"]).replace(" ", ""))
        old_addresses = [u32(parent, owner) for owner in owners]
        for owner, address in zip(owners, old_addresses):
            gate(payload_at(parent, address) == orig_raw, f"{patch['record_id']} is not original JP")
        payload_bytes = encode_text(patch["translation"], recovered8, verified8)
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

    changed = [index for index, (before, after) in enumerate(zip(parent, candidate)) if before != after]
    gate(set(changed) <= allowed, "candidate changed outside target owners/payloads/glyphs")
    gate(u32(candidate, 0x001A95D8) == u32(parent, 0x001A95D8), "ECM pointer was rewritten")
    parent_overlay = str(merged.get("identity", {}).get("translation_overlay_identity_sha256") or "")
    identity = digest(
        {
            "parent": parent_overlay,
            "batch_id": BATCH_ID,
            "extra_owners": [f"0x{owner:08X}" for owner in EXTRA_OWNERS],
            "records": [{"record_id": patch["record_id"], "payload": by_id[patch["record_id"]]["translation_payload_sha256"]} for patch in patches],
        }
    )
    merged["identity"]["parent_translation_overlay_identity_sha256"] = parent_overlay
    merged["identity"]["mishudeuk_weapons_sha256"] = identity
    merged["identity"]["translation_overlay_identity_sha256"] = identity
    counts = dict(sorted(Counter(str(row.get("translation_status") or "") for row in merged["records"]).items()))
    merged["summary"]["merged_translation_status_counts"] = counts
    merged["summary"]["translation_overlay_identity_sha256"] = identity

    SNAPSHOT.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    TRANSLATION_MERGED_JSON.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    update_translation_manifest(merged, SNAPSHOT)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(candidate)
    shutil.copyfile(MAIN_SAV, OUT_SAV)
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_mishudeuk_weapons_candidate_20260905",
        "source": {
            "parent": advance_relative(PARENT),
            "parent_sha256": PARENT_SHA,
            "main_tip_untouched": sha256(MAIN_TIP_ROM.read_bytes()) != sha256(candidate),
        },
        "analysis": {
            "weixiu_missed_literals": [f"0x{owner:08X}" for owner in EXTRA_OWNERS],
            "weixiu_ko_address": f"0x{MISHUDEUK_KO:08X}",
            "freedom_is_zen_tan_launch_not_volley": "GGA-TEXT-0017A707 全弾発射 → 전탄발사",
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
            "extra_weixiu_retargeted": True,
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
                "weapons": [patch["translation"] for patch in patches],
                "painted": painted,
                "extra_weixiu": [f"0x{owner:08X}" for owner in EXTRA_OWNERS],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
