#!/usr/bin/env python3
"""User wording fixes on the 22.137 weapon candidate.

- 히트 검 → 히트 사벨 (share the existing ヒートサーベル payload)
- 폭도삭 → 폭도색
- 전자 볼트 → 작렬 볼트
- 십이왕방패대차휠 → 십이왕방패대차륜, painting 륜 on a free 12x12/8x16 pair
"""
from __future__ import annotations

import json
import shutil
import struct
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import build_ggen_advance_ko_poc as fontops  # noqa: E402
import build_ggen_advance_unified_rom_poc as unified  # noqa: E402
from ggen_advance_painted_glyph_identity import (  # noqa: E402
    FONT8_RELOCATED,
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

BATCH_ID = "weapon-name-wording-fixes-20260905"
PARENT = ROOT / "outputs" / "20260905_ggen_advance_mishudeuk_weapons" / "ggen_advance_mishudeuk_weapons_candidate_20260905.gba"
PARENT_SHA = "71c35e494bcae43e164e0948b4e07d48e2ed690bbcb8e3f3e9aca52e6edd9468"
SNAPSHOT = ROOT / "analysis" / "ggen_advance_translation_merged_20260905_weapon_wording.json"
OUT_DIR = ROOT / "outputs" / "20260905_ggen_advance_weapon_wording"
OUTPUT = OUT_DIR / "ggen_advance_weapon_wording_candidate_20260905.gba"
OUT_SAV = OUT_DIR / "ggen_advance_weapon_wording_candidate_20260905.sav"
MAIN_SAV = ROOT / "SD Gundam GGeneration Advance (Korean).sav"
REPORT = ROOT / "analysis" / "ggen_advance_weapon_wording_candidate_20260905.json"
CAVE_START = 0x01304140
CAVE_END = 0x01304800
SABER_RECORD = "GGA-TEXT-00179ECA"
PROTECTED = {0x010A, 0x0143, 0x071E, 0x07DB, 0x07DC}

FIXES: tuple[dict[str, Any], ...] = (
    {
        "record_id": "GGA-TEXT-00179F5A",
        "old_ko": "히트 검",
        "translation": "히트 사벨",
        "reuse_record_id": SABER_RECORD,
        "notes": "사용자 교정: ヒート剣을 히트 사벨로. ヒートサーベル 페이로드 공유",
    },
    {
        "record_id": "GGA-TEXT-0017A1D9",
        "old_ko": "폭도삭",
        "translation": "폭도색",
        "notes": "사용자 교정: 爆導索 → 폭도색",
    },
    {
        "record_id": "GGA-TEXT-0017A3D1",
        "old_ko": "전자 볼트",
        "translation": "작렬 볼트",
        "notes": "사용자 교정: …ボルト → 작렬 볼트",
    },
    {
        "record_id": "GGA-TEXT-0017A5CB",
        "old_ko": "십이왕방패대차휠",
        "translation": "십이왕방패대차륜",
        "notes": "사용자 교정: 十二王方牌大車輪 → 십이왕방패대차륜. 륜 12x12/8x16 신규 페인트",
    },
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


def paint_12x12(candidate: bytearray, slot: int, char: str, font12: Any) -> int:
    packed = packed_12x12(char, font12)
    start = FONT12_RELOCATED + slot * fontops.FONT_12X12_STRIDE
    candidate[start : start + fontops.FONT_12X12_STRIDE] = packed
    gate(bytes(candidate[start : start + fontops.FONT_12X12_STRIDE]) == packed, f"failed to paint 12x12 {char!r}")
    return start


def choose_free_both(
    candidate: bytearray,
    japan: bytes,
    live8: set[int],
    live12: set[int],
    occupied: set[int],
) -> int:
    protected = set(PROTECTED) | unified.SPECIAL_SLOTS | unified.RESERVED_GLYPH_SLOTS
    for slot in range(unified.SLOT_MAX, unified.SLOT_MIN - 1, -1):
        if slot in protected or slot in occupied or slot in live8 or slot in live12:
            continue
        cur12 = slot_raw(candidate, FONT12_RELOCATED, slot, fontops.FONT_12X12_STRIDE)
        jp12 = slot_raw(japan, fontops.FONT_12X12_BASE, slot, fontops.FONT_12X12_STRIDE)
        cur8 = slot_raw(candidate, FONT8_RELOCATED, slot, fontops.FONT_8X16_STRIDE)
        jp8 = slot_raw(japan, fontops.FONT_8X16_BASE, slot, fontops.FONT_8X16_STRIDE)
        if cur12 != jp12 or cur8 != jp8:
            continue
        return slot
    raise SystemExit("gate failed: no free 12x12/8x16 pair for new Hangul")


def try_recover_slot(fn, rom: bytes, font: Any, char: str) -> int | None:
    try:
        return fn(rom, font, {char})[char]
    except SystemExit as exc:
        if "is not painted" in str(exc):
            return None
        raise


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    japan = ORIGINAL_ROM.read_bytes()
    parent = PARENT.read_bytes()
    gate(sha256(parent) == PARENT_SHA, "parent candidate drift")
    gate(MAIN_SAV.exists(), "current main SAV missing")
    gate(all(value == 0 for value in parent[CAVE_START:CAVE_END]), "wording cave is not zero-filled")

    charmap = json.loads(CHARMAP.read_text(encoding="utf-8"))
    verified8 = verified_from_charmap(charmap)
    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    by_id = {row["record_id"]: row for row in merged["records"]}
    saber = by_id[SABER_RECORD]
    gate(saber.get("translation_ko") == "히트 사벨", "ヒートサーベル Korean drift")
    saber_owners = owner_offsets(saber)
    gate(saber_owners, "ヒートサーベル has no owners")
    saber_ptr = u32(parent, saber_owners[0])
    gate(all(u32(parent, owner) == saber_ptr for owner in saber_owners), "ヒートサーベル owners diverge")

    font8 = load_galmuri8()
    font12 = load_galmuri12()
    hangul = set().union(*(hangul_chars(fix["translation"]) for fix in FIXES))
    recovered12: dict[str, int] = {}
    recovered8: dict[str, int] = {}
    paint_8_onto_12: set[str] = set()
    paint_12_onto_8: set[str] = set()
    paint_both: set[str] = set()
    for char in hangul:
        slot12 = try_recover_slot(recover_unique_12x12_slots, parent, font12, char)
        slot8 = try_recover_slot(recover_unique_8x16_slots, parent, font8, char)
        if slot12 is not None and slot8 is not None:
            gate(slot12 == slot8, f"8x16/12x12 diverge for {char!r}")
            recovered12[char] = slot12
            recovered8[char] = slot8
        elif slot12 is not None:
            recovered12[char] = slot12
            paint_8_onto_12.add(char)
        elif slot8 is not None:
            recovered8[char] = slot8
            paint_12_onto_8.add(char)
        else:
            paint_both.add(char)
    live8, live12 = unified.collect_live_slots(japan, merged["records"])
    occupied = set(recovered12.values()) | set(recovered8.values())
    candidate = bytearray(parent)
    allowed: set[int] = set()
    painted: list[dict[str, str]] = []
    for char in sorted(paint_8_onto_12):
        slot = recovered12[char]
        gate(slot not in live8, f"cannot paint 8x16 {char!r} at live slot 0x{slot:04X}")
        start8 = paint_8x16(candidate, slot, char, font8)
        allowed.update(range(start8, start8 + fontops.FONT_8X16_STRIDE))
        recovered8[char] = slot
        occupied.add(slot)
        painted.append({"char": char, "slot": f"0x{slot:04X}", "paint": "8x16-match-12x12", "file_offset_8": f"0x{start8:08X}"})
    for char in sorted(paint_12_onto_8):
        slot = recovered8[char]
        gate(slot not in live12, f"cannot paint 12x12 {char!r} at live slot 0x{slot:04X}")
        start12 = paint_12x12(candidate, slot, char, font12)
        allowed.update(range(start12, start12 + fontops.FONT_12X12_STRIDE))
        recovered12[char] = slot
        occupied.add(slot)
        painted.append({"char": char, "slot": f"0x{slot:04X}", "paint": "12x12-match-8x16", "file_offset_12": f"0x{start12:08X}"})
    for char in sorted(paint_both):
        slot = choose_free_both(candidate, japan, live8, live12, occupied)
        start12 = paint_12x12(candidate, slot, char, font12)
        start8 = paint_8x16(candidate, slot, char, font8)
        allowed.update(range(start12, start12 + fontops.FONT_12X12_STRIDE))
        allowed.update(range(start8, start8 + fontops.FONT_8X16_STRIDE))
        occupied.add(slot)
        recovered12[char] = slot
        recovered8[char] = slot
        painted.append(
            {
                "char": char,
                "slot": f"0x{slot:04X}",
                "paint": "new-12x12-and-8x16",
                "file_offset_12": f"0x{start12:08X}",
                "file_offset_8": f"0x{start8:08X}",
            }
        )
    for spec in FIXES:
        row = by_id[spec["record_id"]]
        gate(not unified.uses_12x12(row), f"{spec['record_id']} is classified 12x12")
    for char in hangul:
        gate(recovered8[char] == recovered12[char], f"8x16/12x12 diverge for {char!r}")
    verify_hangul_12x12(candidate, recovered8, font12)

    alloc: dict[str, int] = {}
    cursor = CAVE_START
    written: dict[int, bytes] = {}
    evidence: list[dict[str, Any]] = []

    for spec in FIXES:
        row = by_id[spec["record_id"]]
        gate(row.get("translation_ko") == spec["old_ko"], f"{spec['record_id']} current Korean drift")
        owners = owner_offsets(row)
        gate(owners, f"{spec['record_id']} has no owners")
        old_addresses = [u32(parent, owner) for owner in owners]
        if spec.get("reuse_record_id"):
            payload_bytes = payload_at(candidate, saber_ptr)
            verify_mixed_8x16(candidate, japan, payload_bytes, spec["translation"], font8, hangul, verified8)
            pointer = saber_ptr
        else:
            payload_bytes = encode_text(spec["translation"], recovered8, verified8)
            verify_mixed_8x16(candidate, japan, payload_bytes, spec["translation"], font8, hangul, verified8)
            hangul_only = "".join(char for char in spec["translation"] if char in hangul)
            hangul_payload = bytearray()
            for char in hangul_only:
                token = token_from_slot(recovered8[char])
                if token <= 0xDF:
                    hangul_payload.append(token)
                else:
                    hangul_payload.extend((token >> 8, token & 0xFF))
            hangul_payload.append(0)
            verify_payload_painted(candidate, bytes(hangul_payload), hangul_only, font8)
            key = spec["translation"]
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
        gate(all(u32(candidate, owner) == pointer for owner in owners), f"{spec['record_id']} redirect failed")
        gate(payload_at(candidate, pointer) == payload_bytes, f"{spec['record_id']} payload write failed")

        before = {key: row.get(key) for key in ("translation_ko", "translator_notes")}
        row["baseline_translation_ko"] = spec["translation"]
        row["translation_ko"] = spec["translation"]
        row["translation_source"] = BATCH_ID
        row["review_status"] = "user_requested"
        row["review_count"] = int(row.get("review_count") or 0) + 1
        row["reviewed_at"] = "2026-09-05"
        row["translator_notes"] = spec["notes"]
        row["overlay_batch_id"] = BATCH_ID
        update_payload_hash(row)
        evidence.append(
            {
                "record_id": spec["record_id"],
                "before": before,
                "translation_ko": row["translation_ko"],
                "owner_offsets": [f"0x{owner:08X}" for owner in owners],
                "old_active_addresses": [f"0x{address:08X}" for address in sorted(set(old_addresses))],
                "new_address": f"0x{pointer:08X}",
                "payload_hex": payload_bytes.hex(" ").upper(),
                "reused_existing_payload": bool(spec.get("reuse_record_id")),
            }
        )

    changed = [index for index, (before, after) in enumerate(zip(parent, candidate)) if before != after]
    gate(set(changed) <= allowed, "candidate changed outside target owners/payloads/glyphs")
    parent_overlay = str(merged.get("identity", {}).get("translation_overlay_identity_sha256") or "")
    identity = digest(
        {
            "parent": parent_overlay,
            "batch_id": BATCH_ID,
            "records": [{"record_id": spec["record_id"], "payload": by_id[spec["record_id"]]["translation_payload_sha256"]} for spec in FIXES],
        }
    )
    merged["identity"]["parent_translation_overlay_identity_sha256"] = parent_overlay
    merged["identity"]["weapon_wording_sha256"] = identity
    merged["identity"]["translation_overlay_identity_sha256"] = identity
    SNAPSHOT.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    TRANSLATION_MERGED_JSON.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    update_translation_manifest(merged, SNAPSHOT)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(candidate)
    shutil.copyfile(MAIN_SAV, OUT_SAV)
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_weapon_wording_candidate_20260905",
        "source": {"parent": advance_relative(PARENT), "parent_sha256": PARENT_SHA},
        "painted_new_hangul": painted,
        "consumers": evidence,
        "output": {"path": advance_relative(OUTPUT), "size": len(candidate), "sha256": sha256(candidate)},
        "sav": {"path": advance_relative(OUT_SAV), "byte_exact_copy": OUT_SAV.read_bytes() == MAIN_SAV.read_bytes()},
        "verification": {
            "result": "PASS",
            "painted_glyph_identity_verified": True,
            "changed_bytes": len(changed),
            "main_tip_not_modified": sha256(MAIN_TIP_ROM.read_bytes()) != sha256(candidate),
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
                "painted": painted,
                "translations": [spec["translation"] for spec in FIXES],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
