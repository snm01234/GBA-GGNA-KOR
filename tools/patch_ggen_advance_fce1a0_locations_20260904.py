#!/usr/bin/env python3
"""Redirect FCE1A0 yellow-window condition locations that still draw Japanese.

Search-record +0x10 location names are already Korean, but the parallel
FCE1A0 table (yellow-window line 2) was left pending because production
decode used 8x16 maps.  Re-decode with 12x12, reuse already-verified Korean
payloads, and encode the remaining closed strings with painted glyph identity.
Hold ニューヤーク廃<0x07AE> — that last kanji is still unidentified.
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
from build_ggen_advance_unified_rom_poc import collect_live_slots  # noqa: E402

BATCH_ID = "fce1a0-condition-locations-20260904"
SNAPSHOT = ROOT / "analysis" / "ggen_advance_translation_merged_20260904_fce1a0_locations.json"
OUTPUT = ROOT / "outputs" / "20260904_ggen_advance_fce1a0_locations" / "ggen_advance_fce1a0_locations_candidate_20260904.gba"
OUT_SAV = ROOT / "outputs" / "20260904_ggen_advance_fce1a0_locations" / "ggen_advance_fce1a0_locations_candidate_20260904.sav"
MAIN_SAV = ROOT / "SD Gundam GGeneration Advance (Korean).sav"
REPORT = ROOT / "analysis" / "ggen_advance_fce1a0_locations_20260904.json"

FCE1A0 = 0x00FCE1A0
FCE1A0_END = FCE1A0 + 64 * 4
FCE2D8 = 0x00FCE2D8
FCE2D8_END = FCE2D8 + 69 * 4
CAVE_START = 0x012901A0
CAVE_END = 0x01290800

# 12x12 identified compatibility slots.  Digit 3 is fullwidth ３ at 0x00FA.
ASCII_12_SLOTS = {
    "0": 0x000A,
    "1": 0x00F8,
    "3": 0x00FA,
    "5": 0x00FC,
    "L": 0x0104,
}

# Hangul whose 12x12 unique slot is still live Japanese on 8x16 — do not paint.
SKIP_8X16_PAINT = {"앙"}

PATCHES = (
    {"record_id": "GGA-TEXT-0018D4D6", "source": "へリオポリス", "translation": "헬리오폴리스", "reuse": "GGA-TEXT-001BEEDC"},
    {"record_id": "GGA-TEXT-0018D4E9", "source": "ニューヤーク", "translation": "뉴야크", "reuse": "GGA-TEXT-001BEEEE"},
    {"record_id": "GGA-TEXT-0018D4EF", "source": "太平洋沿岸部", "translation": "태평양 연안부", "alloc": "pacific"},
    {"record_id": "GGA-TEXT-0018D4FC", "source": "中央アジア 死線地帯", "translation": "중앙아시아 사선지대", "alloc": "central_asia"},
    {"record_id": "GGA-TEXT-0018D512", "source": "ジャブロー地下", "translation": "자브로 지하", "reuse": "GGA-TEXT-001BEF16"},
    {"record_id": "GGA-TEXT-0018D51C", "source": "トリントン基地", "translation": "트리턴 기지", "reuse": "GGA-TEXT-001BEF1F"},
    {"record_id": "GGA-TEXT-0018D526", "source": "キンバライト基地", "translation": "킨바라이트 기지", "reuse": "GGA-TEXT-001BEF28"},
    {"record_id": "GGA-TEXT-0018D531", "source": "衛星軌道", "translation": "위성 궤도", "alloc": "satellite"},
    {"record_id": "GGA-TEXT-0018D53A", "source": "ジャブロー地下", "translation": "자브로 지하", "reuse": "GGA-TEXT-001BEF16"},
    {"record_id": "GGA-TEXT-0018D544", "source": "Ｌ1宙域", "translation": "L1 우주역", "alloc": "l1"},
    {"record_id": "GGA-TEXT-0018D54D", "source": "Ｌ5宙域", "translation": "L5 우주역", "alloc": "l5"},
    {"record_id": "GGA-TEXT-0018D556", "source": "月航路", "translation": "달 항로", "alloc": "moon_route"},
    {"record_id": "GGA-TEXT-0018D55D", "source": "フォン・シティ", "translation": "폰 시티", "reuse": "GGA-TEXT-001BEF5B"},
    {"record_id": "GGA-TEXT-0018D565", "source": "宇宙要塞バルジ", "translation": "우주요새 벌지", "reuse": "GGA-TEXT-001BEF64"},
    {"record_id": "GGA-TEXT-0018D56F", "source": "ソロモン周辺宙域", "translation": "솔로몬 주변 우주역", "alloc": "solomon_area"},
    {"record_id": "GGA-TEXT-0018D57C", "source": "ソロモン", "translation": "솔로몬", "reuse": "GGA-TEXT-001BEF79"},
    {"record_id": "GGA-TEXT-0018D589", "source": "ア・バオア・クー", "translation": "아 바오아 쿠", "reuse": "GGA-TEXT-001BEF86"},
    {"record_id": "GGA-TEXT-0018D592", "source": "ア・バオア・クー宙域", "translation": "아 바오아 쿠 우주역", "reuse": "GGA-TEXT-001BEF8F"},
    {"record_id": "GGA-TEXT-0018D5CA", "source": "ポイント３05", "translation": "포인트 305", "alloc": "point305"},
    {"record_id": "GGA-TEXT-0018D5D5", "source": "中央アジア 死線地帯", "translation": "중앙아시아 사선지대", "alloc": "central_asia"},
    {"record_id": "GGA-TEXT-0018D5E6", "source": "アリス・スプリングス", "translation": "앨리스 스프링스", "reuse": "GGA-TEXT-001BEFE0"},
    {"record_id": "GGA-TEXT-0018D5F1", "source": "廃コロニー宙域", "translation": "폐 콜로니 우주역", "alloc": "abandoned_colony"},
    {"record_id": "GGA-TEXT-0018D5FC", "source": "シャングリラ", "translation": "샹그릴라", "reuse": "GGA-TEXT-001BEFF5"},
    {"record_id": "GGA-TEXT-0018D5A9", "source": "アクシズ", "translation": "액시즈", "reuse": "GGA-TEXT-001BEFA5"},
    {"record_id": "GGA-TEXT-0018D603", "source": "死線地帯", "translation": "사선지대", "alloc": "dead_line"},
    {"record_id": "GGA-TEXT-0018D60C", "source": "大西洋軍基地", "translation": "대서양군 기지", "alloc": "atlantic"},
    {"record_id": "GGA-TEXT-0018D622", "source": "地球軌道 デブリ帯", "translation": "지구 궤도 데브리대", "alloc": "debris"},
    {"record_id": "GGA-TEXT-0018D62F", "source": "暗礁宙域", "translation": "암초 우주역", "reuse": "GGA-TEXT-001BF026"},
    {"record_id": "GGA-TEXT-0018D638", "source": "月軌道航路", "translation": "달 궤도 항로", "alloc": "moon_orbit"},
    {"record_id": "GGA-TEXT-0018D643", "source": "Ｌ３コロニー", "translation": "L3 콜로니", "alloc": "l3_colony"},
    {"record_id": "GGA-TEXT-0018D64C", "source": "サイド1コロニー", "translation": "사이드 1 콜로니", "alloc": "side1"},
    {"record_id": "GGA-TEXT-001BE9D7", "source": "死線地帯", "translation": "사선지대", "alloc": "dead_line"},
    {"record_id": "GGA-TEXT-001BE9E0", "source": "大西洋軍基地", "translation": "대서양군 기지", "alloc": "atlantic"},
    {"record_id": "GGA-TEXT-001BE9F6", "source": "地球軌道 デブリ帯", "translation": "지구 궤도 데브리대", "alloc": "debris"},
    {"record_id": "GGA-TEXT-001BEA03", "source": "暗礁宙域", "translation": "암초 우주역", "reuse": "GGA-TEXT-001BF026"},
    {"record_id": "GGA-TEXT-001BEA0C", "source": "月軌道航路", "translation": "달 궤도 항로", "alloc": "moon_orbit"},
    {"record_id": "GGA-TEXT-001BEA17", "source": "Ｌ３コロニー", "translation": "L3 콜로니", "alloc": "l3_colony"},
    {"record_id": "GGA-TEXT-001BEA20", "source": "サイド1コロニー", "translation": "사이드 1 콜로니", "alloc": "side1"},
)

HELD = {
    "GGA-TEXT-0018D618": "ニューヤーク廃<0x07AE> — 12x12 slot 0x07AE unidentified; fail closed",
    "GGA-TEXT-001BE9EC": "same unidentified 廃X clone on FCE2D8",
}


def owner_offsets(row: dict) -> tuple[int, ...]:
    return tuple(int(owner.removeprefix("OWNER-U32-"), 16) for owner in row.get("owner_ids", []) if str(owner).startswith("OWNER-U32-"))


def in_target_tables(offset: int) -> bool:
    return FCE1A0 <= offset < FCE1A0_END or FCE2D8 <= offset < FCE2D8_END


def emit_slot(slot: int) -> bytes:
    token = token_from_slot(slot)
    if token <= 0xDF:
        return bytes((token,))
    gate(0xE000 <= token <= 0xEFFF, f"invalid literal token for slot 0x{slot:04X}")
    return bytes((token >> 8, token & 0xFF))


def encode_mixed(text: str, hangul_tokens: dict[str, int]) -> bytes:
    out = bytearray()
    for char in text:
        if char == " ":
            out.append(0x01)
            continue
        if char in ASCII_12_SLOTS:
            out.extend(emit_slot(ASCII_12_SLOTS[char]))
            continue
        token = hangul_tokens.get(char)
        gate(token is not None, f"missing painted Hangul token for {char!r}")
        if token <= 0xDF:
            out.append(token)
        else:
            gate(0xE000 <= token <= 0xEFFF, f"invalid Hangul token for {char!r}: 0x{token:04X}")
            out.extend((token >> 8, token & 0xFF))
    out.append(0)
    return bytes(out)


def payload_slots(payload: bytes) -> list[int]:
    slots: list[int] = []
    index = 0
    while index < len(payload):
        value = payload[index]
        if value == 0:
            break
        if value == 1:
            index += 1
            continue
        if value >= 0xE0:
            token = (value << 8) | payload[index + 1]
            slots.append((token + 0x20E0) & 0xFFFF)
            index += 2
        else:
            slots.append(value)
            index += 1
    return slots


def verify_mixed(
    rom: bytes | bytearray,
    original: bytes,
    payload: bytes,
    text: str,
    font8,
    font12,
    hangul_8_ok: set[str],
) -> None:
    expected = [char for char in text if char != " "]
    slots = payload_slots(payload)
    gate(len(slots) == len(expected), f"payload glyph count {len(slots)} != {len(expected)} for {text!r}")
    for char, slot in zip(expected, slots):
        if char in ASCII_12_SLOTS:
            gate(slot == ASCII_12_SLOTS[char], f"ASCII {char!r} encoded at 0x{slot:04X}, expected 0x{ASCII_12_SLOTS[char]:04X}")
            actual12 = slot_raw(rom, FONT12_RELOCATED, slot, fontops.FONT_12X12_STRIDE)
            native12 = slot_raw(original, fontops.FONT_12X12_BASE, slot, fontops.FONT_12X12_STRIDE)
            gate(actual12 == native12, f"12x12 ASCII slot 0x{slot:04X} for {char!r} was overpainted")
            continue
        actual12 = slot_raw(rom, FONT12_RELOCATED, slot, fontops.FONT_12X12_STRIDE)
        gate(actual12 == packed_12x12(char, font12), f"12x12 painted glyph for {char!r} is not at slot 0x{slot:04X}")
        if char in hangul_8_ok:
            actual8 = slot_raw(rom, FONT8_RELOCATED, slot, fontops.FONT_8X16_STRIDE)
            gate(actual8 == packed_8x16(char, font8), f"8x16 painted glyph for {char!r} is not at slot 0x{slot:04X}")


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


def main() -> int:
    original = ORIGINAL_ROM.read_bytes()
    current = MAIN_TIP_ROM.read_bytes()
    manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(len(current) == 32 * 1024 * 1024 and sha256(current) == manifest["sha256"], "main TIP/manifest drift")
    gate(u32(original, 0x0006B170) == 0x08FCE1A0, "parallel condition table literal drift")
    gate(bl_target(original, 0x0006AFD2) == 0x0806B148 and bl_target(original, 0x0006B3DE) == 0x0806B148, "parallel condition bridge drift")
    gate(bl_target(original, 0x0006AFE0) == DRAW_WRAPPER and bl_target(original, 0x0006B3EC) == DRAW_WRAPPER, "parallel condition draw drift")
    gate(MAIN_SAV.exists(), "current main SAV missing")
    gate(all(value == 0 for value in current[CAVE_START:CAVE_END]), "condition-location cave is not zero-filled")

    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    by_id = {row["record_id"]: row for row in merged["records"]}
    font8 = load_galmuri8()
    font12 = load_galmuri12()
    live8, _live12 = collect_live_slots(original, merged["records"])

    hangul = set("".join(patch["translation"] for patch in PATCHES)) - set(ASCII_12_SLOTS) - {" "}
    recovered12 = recover_unique_12x12_slots(current, font12, hangul)
    painted_8 = {char for char in hangul if char not in SKIP_8X16_PAINT}
    recovered8 = recover_unique_8x16_slots(current, font8, painted_8 - {"궤", "태", "평", "폐"})
    candidate = bytearray(current)
    allowed: set[int] = set()
    painted_slots = []
    for char in ("궤", "태", "평", "폐"):
        slot = recovered12[char]
        gate(slot not in live8, f"8x16 slot 0x{slot:04X} for {char!r} became live Japanese")
        start = paint_8x16(candidate, slot, char, font8)
        allowed.update(range(start, start + fontops.FONT_8X16_STRIDE))
        painted_slots.append({"char": char, "slot": f"0x{slot:04X}", "file_offset": f"0x{start:08X}"})
        recovered8[char] = slot
    for char in recovered8:
        gate(recovered8[char] == recovered12[char], f"8x16/12x12 slots diverge for {char!r}")
    hangul_8_ok = set(recovered8)
    hangul_tokens = tokens_from_recovered(recovered12)

    reuse_ptr: dict[str, int] = {}
    for patch in PATCHES:
        reuse_id = patch.get("reuse")
        if not reuse_id or reuse_id in reuse_ptr:
            continue
        reuse_row = by_id[reuse_id]
        owners = owner_offsets(reuse_row)
        gate(owners, f"{reuse_id} has no owners")
        pointer = u32(current, owners[0])
        payload = payload_at(current, pointer)
        verify_payload_painted(current, payload, patch["translation"], font8)
        verify_payload_painted_12x12(current, payload, patch["translation"], font12)
        reuse_ptr[reuse_id] = pointer

    alloc_at: dict[str, int] = {}
    cursor = CAVE_START
    written: dict[int, bytes] = {}
    evidence = []

    for patch in PATCHES:
        row = by_id[patch["record_id"]]
        owners = owner_offsets(row)
        gate(owners, f"{patch['record_id']} has no owners")
        gate(all(in_target_tables(owner) for owner in owners), f"{patch['record_id']} owner outside FCE1A0/FCE2D8")
        gate(row.get("translation_status") == "pending", f"{patch['record_id']} is not pending")
        orig_raw = bytes.fromhex(str(row["raw_hex"]).replace(" ", ""))
        old_addresses = [u32(current, owner) for owner in owners]
        for owner, address in zip(owners, old_addresses):
            gate(payload_at(current, address) == orig_raw, f"{patch['record_id']} owner 0x{owner:08X} is not original JP")

        if patch.get("reuse"):
            pointer = reuse_ptr[patch["reuse"]]
            payload = payload_at(candidate, pointer)
            at = pointer - ROM_BASE
        else:
            key = patch["alloc"]
            if key in alloc_at:
                at = alloc_at[key]
                payload = written[at]
                pointer = ROM_BASE + at
            else:
                payload = encode_mixed(patch["translation"], hangul_tokens)
                verify_mixed(candidate, original, payload, patch["translation"], font8, font12, hangul_8_ok)
                at = cursor
                gate(at + len(payload) <= CAVE_END, "condition-location cave exhausted")
                gate(all(value == 0 for value in candidate[at : at + len(payload)]), f"cave dirty at 0x{at:08X}")
                candidate[at : at + len(payload)] = payload
                written[at] = payload
                allowed.update(range(at, at + len(payload)))
                alloc_at[key] = at
                cursor = align16(at + len(payload))
                pointer = ROM_BASE + at

        for owner in owners:
            struct.pack_into("<I", candidate, owner, pointer)
            allowed.update(range(owner, owner + 4))
        gate(all(u32(candidate, owner) == pointer for owner in owners), f"{patch['record_id']} redirect failed")
        gate(payload_at(candidate, pointer) == payload, f"{patch['record_id']} payload mismatch")
        if patch.get("reuse"):
            verify_payload_painted(candidate, payload, patch["translation"], font8)
            verify_payload_painted_12x12(candidate, payload, patch["translation"], font12)
        else:
            verify_mixed(candidate, original, payload, patch["translation"], font8, font12, hangul_8_ok)

        before = {key: row.get(key) for key in ("source_text", "source_decode_status", "source_unresolved_slots", "translation_ko", "translation_status")}
        row["source_text"] = patch["source"]
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
        row["translator_notes"] = (
            "FCE1A0/FCE2D8 12x12 closed location; yellow-window condition line still had original JP. "
            "Held 뉴야크폐X because slot 0x07AE is unidentified. 앙 is 12x12-only (8x16 slot still live JP)."
        )
        row["qa_status"] = "painted_glyph_identity_verified"
        row["overlay_batch_id"] = BATCH_ID
        update_payload_hash(row)
        evidence.append(
            {
                "record_id": patch["record_id"],
                "before": before,
                "source_text": patch["source"],
                "translation_ko": patch["translation"],
                "reuse_record_id": patch.get("reuse"),
                "alloc_key": patch.get("alloc"),
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
            "records": [{"record_id": patch["record_id"], "payload": by_id[patch["record_id"]]["translation_payload_sha256"]} for patch in PATCHES],
        }
    )
    merged["identity"]["parent_translation_overlay_identity_sha256"] = parent
    merged["identity"]["fce1a0_condition_locations_sha256"] = identity
    merged["identity"]["translation_overlay_identity_sha256"] = identity
    counts = dict(sorted(Counter(str(row.get("translation_status") or "") for row in merged["records"]).items()))
    merged["summary"]["merged_translation_status_counts"] = counts
    merged["summary"]["translation_overlay_identity_sha256"] = identity
    merged["fce1a0_condition_locations"] = {
        "batch_id": BATCH_ID,
        "changed_records": len(PATCHES),
        "held": HELD,
        "identity_sha256": identity,
        "static_consumer_report": advance_relative(REPORT),
    }

    SNAPSHOT.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    TRANSLATION_MERGED_JSON.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    update_translation_manifest(merged, SNAPSHOT)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(candidate)
    shutil.copyfile(MAIN_SAV, OUT_SAV)
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_fce1a0_condition_locations_candidate_20260904",
        "source": {
            "main_tip": advance_relative(MAIN_TIP_ROM),
            "main_tip_sha256": sha256(current),
            "translation_source": advance_relative(TRANSLATION_MERGED_JSON),
        },
        "root_cause": (
            "FCE1A0 yellow-window condition bodies were pending because production "
            "decode used 8x16 maps. 12x12 decode closes 31 unique location strings. "
            "Search-record +0x10 counterparts were already Korean."
        ),
        "held": HELD,
        "painted_8x16_to_match_12x12": painted_slots,
        "skip_8x16_paint": sorted(SKIP_8X16_PAINT),
        "ascii_12x12_slots": {char: f"0x{slot:04X}" for char, slot in ASCII_12_SLOTS.items()},
        "consumers": evidence,
        "output": {"path": advance_relative(OUTPUT), "size": len(candidate), "sha256": sha256(candidate)},
        "sav": {
            "path": advance_relative(OUT_SAV),
            "sha256": sha256(OUT_SAV.read_bytes()),
            "byte_exact_copy": OUT_SAV.read_bytes() == MAIN_SAV.read_bytes(),
        },
        "verification": {
            "result": "PASS",
            "painted_glyph_identity_verified": True,
            "all_target_owners_redirected": True,
            "only_target_owners_payloads_and_new_glyph_mutated": True,
            "changed_bytes": len(changed),
            "changed_records": len(PATCHES),
            "main_tip_not_modified": sha256(MAIN_TIP_ROM.read_bytes()) == sha256(current),
            "held_unresolved_07AE": True,
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
                "changed_records": len(PATCHES),
                "painted_8x16": painted_slots,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
