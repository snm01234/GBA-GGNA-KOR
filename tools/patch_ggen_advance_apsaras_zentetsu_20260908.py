#!/usr/bin/env python3
"""Unify Apsaras as 아프사라스 and fix Side 2 二の舞 (전철, not 재판)."""
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
    load_galmuri12,
    load_galmuri8,
    packed_12x12,
    packed_8x16,
    paint_8x16,
    slot_raw,
)
from ggen_advance_project_paths import (  # noqa: E402
    MAIN_TIP_MANIFEST,
    MAIN_TIP_ROM,
    ORIGINAL_ROM,
    TRANSLATION_MERGED_JSON,
    advance_relative,
)
from merge_ggen_advance_translation_overlays import digest  # noqa: E402
from patch_ggen_advance_intermission_text_consumers_20260904 import (  # noqa: E402
    gate,
    payload_at,
    sha256,
)
from patch_ggen_advance_kimi_jane_to_neo_20260904 import (  # noqa: E402
    owner_offsets,
    update_payload_hash,
    update_translation_manifest,
)
from patch_ggen_advance_map_script_inline_poc import (  # noqa: E402
    MAX_DIALOGUE_CELLS,
    ROM_BASE,
    encode_map_korean_line,
    load_identified_12x12,
    raw_hex_bytes,
)

BATCH_ID = "apsaras-zentetsu-unify-20260908"
SNAPSHOT = ROOT / "analysis" / "ggen_advance_translation_merged_20260908_apsaras_zentetsu.json"
OUT_DIR = ROOT / "outputs" / "20260908_ggen_advance_apsaras_zentetsu"
OUTPUT = OUT_DIR / "ggen_advance_apsaras_zentetsu_candidate_20260908.gba"
OUT_SAV = OUT_DIR / "ggen_advance_apsaras_zentetsu_candidate_20260908.sav"
MAIN_SAV = ROOT / "SD Gundam GGeneration Advance (Korean).sav"
REPORT = ROOT / "analysis" / "ggen_advance_apsaras_zentetsu_candidate_20260908.json"
MANIFEST = OUT_DIR / "manifest.json"
CAVE_START = 0x012B1820
CAVE_END = 0x012BF000
MAP_BANK = (0x00F00000, 0x00FC0000)
NOTES = (
    "앱살라스/앱살러스→아프사라스 유닛명 통일. "
    "사이드2 二の舞는 재판이 아니라 전철"
)

# 15칸을 넘는 맵 대사는 줄만 다시 나눈다. 세그먼트 수는 유지.
REWRAP: dict[str, list[str]] = {
    "GGA-MAPSCRIPT-00F71C96": ["후후후, 내 자식", "아프사라스 힘을 보일 기회다"],
    "GGA-MAPSCRIPT-00F7F729": ["형은 아프사라스 지키려", "병사들을희생시키려하고있습니다"],
    "GGA-MAPSCRIPT-00F7F747": ["모처럼 아프사라스 완성되고,", "자브로도 떨어뜨렸는데……"],
    "GGA-MAPSCRIPT-00F80408": ["노리스들을 일격한 적을", "내 아프사라스가 쓰러뜨린다…"],
    "GGA-MAPSCRIPT-00F8D81F": ["오빠가 아프사라스를", "뛰어넘었다고 말하는 이상,"],
    "GGA-MAPSCRIPT-00F8D837": ["저건 정말로 아프사라스", "이상의 힘을 가지고 있어"],
    "GGA-MAPSCRIPT-00FA9104": ["아프사라스 망령 같으니……!"],
}


PROTECTED = {0x010A, 0x0143, 0x071B, 0x071E, 0x07DB, 0x07DC}


def find_lookups(rom: bytes, orig_addr: int, expected_end: int) -> list[tuple[int, int, int]]:
    key = struct.pack("<I", orig_addr)
    hits: list[tuple[int, int, int]] = []
    cursor = 0
    while True:
        pos = rom.find(key, cursor)
        if pos < 0:
            break
        if pos + 12 <= len(rom):
            orig, neu, orig_end = struct.unpack_from("<III", rom, pos)
            if orig == orig_addr and orig_end == expected_end and 0x09000000 <= neu < 0x0A000000:
                hits.append((pos, neu, orig_end))
        cursor = pos + 1
    gate(hits, f"lookup missing for 0x{orig_addr:08X}")
    neus = {neu for _pos, neu, _end in hits}
    gate(len(neus) == 1, f"lookup neu drift for 0x{orig_addr:08X}: {[hex(value) for value in sorted(neus)]}")
    return hits


def paint_12x12(candidate: bytearray, slot: int, char: str, font12) -> int:
    packed = packed_12x12(char, font12)
    start = FONT12_RELOCATED + slot * fontops.FONT_12X12_STRIDE
    candidate[start : start + fontops.FONT_12X12_STRIDE] = packed
    gate(bytes(candidate[start : start + fontops.FONT_12X12_STRIDE]) == packed, f"failed to paint 12x12 {char!r}")
    return start


def choose_free_12x12(candidate: bytearray, japan: bytes, live12: set[int], occupied: set[int]) -> int:
    protected = set(PROTECTED) | unified.SPECIAL_SLOTS | unified.RESERVED_GLYPH_SLOTS
    for slot in range(unified.SLOT_MAX, unified.SLOT_MIN - 1, -1):
        if slot in protected or slot in occupied or slot in live12:
            continue
        current = slot_raw(candidate, FONT12_RELOCATED, slot, fontops.FONT_12X12_STRIDE)
        native = slot_raw(japan, fontops.FONT_12X12_BASE, slot, fontops.FONT_12X12_STRIDE)
        if current != native:
            continue
        return slot
    raise SystemExit("gate failed: no free 12x12 slot for new Hangul")


def choose_free_8x16(candidate: bytearray, japan: bytes, live8: set[int], occupied: set[int]) -> int:
    protected = set(PROTECTED) | unified.SPECIAL_SLOTS | unified.RESERVED_GLYPH_SLOTS
    for slot in range(unified.SLOT_MAX, unified.SLOT_MIN - 1, -1):
        if slot in protected or slot in occupied or slot in live8:
            continue
        current = slot_raw(candidate, FONT8_RELOCATED, slot, fontops.FONT_8X16_STRIDE)
        native = slot_raw(japan, fontops.FONT_8X16_BASE, slot, fontops.FONT_8X16_STRIDE)
        if current != native:
            continue
        return slot
    raise SystemExit("gate failed: no free 8x16 slot for new Hangul")


def write_payload(
    candidate: bytearray,
    address: int,
    encoded: bytes,
    old_size: int,
    allowed: set[int],
    cursor: int,
    *,
    require_nul: bool = True,
) -> tuple[int, int]:
    if require_nul:
        gate(encoded.endswith(b"\x00"), "encoded payload missing NUL")
    if len(encoded) <= old_size:
        start = address - ROM_BASE
        candidate[start : start + len(encoded)] = encoded
        if len(encoded) < old_size:
            candidate[start + len(encoded) : start + old_size] = b"\x00" * (old_size - len(encoded))
        allowed.update(range(start, start + old_size))
        return address, cursor
    cursor = (cursor + 15) & ~15
    gate(cursor + len(encoded) <= CAVE_END, "apsaras cave overflow")
    candidate[cursor : cursor + len(encoded)] = encoded
    allowed.update(range(cursor, cursor + len(encoded)))
    return ROM_BASE + cursor, cursor + len(encoded)


def rewrite_text(text: str) -> str:
    return (
        text.replace("앱살러스", "아프사라스")
        .replace("앱살라스", "아프사라스")
        .replace("재판은 사양", "전철은 사양")
    )


def needs_rewrite(text: str) -> bool:
    return any(token in text for token in ("앱살라스", "앱살러스", "재판은 사양"))


def hangul_chars(text: str) -> set[str]:
    return {char for char in text if "가" <= char <= "힣"}


def visible_segments(segments: list[str]) -> list[str]:
    return [item for item in segments if item]


def apply_row_text(row: dict[str, Any]) -> tuple[str, list[str]]:
    record_id = str(row["record_id"])
    old_segments = [str(item) for item in (row.get("translation_segments") or [])]
    if record_id in REWRAP:
        new_visible = list(REWRAP[record_id])
        old_visible = visible_segments(old_segments)
        gate(len(old_visible) == len(new_visible), f"rewrap visible count {record_id}")
        if old_segments:
            new_segments: list[str] = []
            visible_index = 0
            for item in old_segments:
                if item:
                    new_segments.append(new_visible[visible_index])
                    visible_index += 1
                else:
                    new_segments.append(item)
            gate(visible_index == len(new_visible), f"rewrap framing {record_id}")
        else:
            new_segments = list(new_visible)
        after = "\n".join(new_visible)
        return after, new_segments
    before = str(row.get("translation_ko") or "")
    after = rewrite_text(before)
    new_segments = [rewrite_text(item) if item else item for item in old_segments]
    return after, new_segments


def recover_or_paint(
    candidate: bytearray,
    original: bytes,
    font,
    char: str,
    *,
    choose_free,
    paint,
    packed,
    live: set[int],
    occupied: set[int],
    allowed: set[int],
    painted: list[dict[str, str]],
    label: str,
    relocated: int,
    stride: int,
    count: int,
) -> int:
    wanted = packed(char, font)
    hits = [slot for slot in range(count) if slot_raw(candidate, relocated, slot, stride) == wanted]
    if hits:
        slot = min(hits)
    else:
        slot = choose_free(candidate, original, live, occupied)
        start = paint(candidate, slot, char, font)
        allowed.update(range(start, start + stride))
        painted.append({"font": label, "char": char, "slot": f"0x{slot:04X}"})
        live.add(slot)
    occupied.add(slot)
    gate(
        slot_raw(candidate, relocated, slot, stride) == wanted,
        f"{label} painted glyph for {char!r} is not at 0x{slot:04X}",
    )
    return slot


def patch_map_row(
    row: dict[str, Any],
    old_segments: list[str],
    new_segments: list[str],
    current: bytes,
    candidate: bytearray,
    recovered12: dict[str, int],
    identified: dict[str, int],
    allowed: set[int],
    cave_cursor: int,
) -> tuple[int, list[dict[str, Any]]]:
    segments = list(row.get("segments") or [])
    gate(len(segments) == len(new_segments), f"map segment framing drift {row['record_id']}")
    cursor = int(str(row["target_file_offset"]), 16)
    first_new_addr: int | None = None
    first_old_end: int | None = None
    written: list[dict[str, Any]] = []
    for index, (segment, old_text, new_text) in enumerate(zip(segments, old_segments, new_segments)):
        original_bytes = raw_hex_bytes(str(segment.get("raw_hex") or ""))
        gate(original_bytes.endswith(b"\x00"), f"map segment missing NUL {row['record_id']}")
        orig_addr = ROM_BASE + cursor
        orig_end = orig_addr + len(original_bytes) - 1
        lookups = find_lookups(current, orig_addr, orig_end)
        neu = lookups[0][1]
        old_payload = payload_at(current, neu)
        if old_text:
            encoded_old, missing_old = encode_map_korean_line(old_text, recovered12, identified)
            gate(
                encoded_old == old_payload and not missing_old,
                f"live encode mismatch {row['record_id']}#{index}: "
                f"{None if encoded_old is None else encoded_old.hex()} vs {old_payload.hex()} missing={missing_old}",
            )
            gate(
                "\n" not in new_text and len(new_text) <= MAX_DIALOGUE_CELLS,
                f"map dialogue width {row['record_id']}#{index} len={len(new_text)} text={new_text!r}",
            )
            encoded_new, missing_new = encode_map_korean_line(new_text, recovered12, identified)
            gate(encoded_new is not None and not missing_new, f"encode failed {row['record_id']}: {missing_new}")
        else:
            encoded_new = old_payload
        new_addr, cave_cursor = write_payload(
            candidate, neu, encoded_new, len(old_payload), allowed, cave_cursor
        )
        if new_addr != neu:
            for lookup_pos, _neu, _end in lookups:
                struct.pack_into("<I", candidate, lookup_pos + 4, new_addr)
                allowed.update(range(lookup_pos + 4, lookup_pos + 8))
        if index == 0:
            first_new_addr = new_addr
            first_old_end = orig_end
        written.append(
            {
                "segment": index,
                "old": old_text,
                "new": new_text,
                "cells": len(new_text),
                "old_payload": f"0x{neu:08X}",
                "new_payload": f"0x{new_addr:08X}",
                "encoded_size": len(encoded_new),
                "lookup_count": len(lookups),
            }
        )
        cursor += len(original_bytes)
    opcode_text = str(row.get("opcode_18_file_offset") or "")
    if opcode_text and first_new_addr is not None and first_old_end is not None:
        opcode_addr = ROM_BASE + int(opcode_text, 16)
        if opcode_addr != ROM_BASE + int(str(row["target_file_offset"]), 16):
            alias_hits = find_lookups(current, opcode_addr, first_old_end)
            for alias_pos, alias_neu, _alias_end in alias_hits:
                if alias_neu != first_new_addr:
                    struct.pack_into("<I", candidate, alias_pos + 4, first_new_addr)
                    allowed.update(range(alias_pos + 4, alias_pos + 8))
    return cave_cursor, written


def patch_owned_payload(
    row: dict[str, Any],
    old_payload: bytes,
    new_payload: bytes,
    current: bytes,
    candidate: bytearray,
    allowed: set[int],
    cave_cursor: int,
    *,
    require_nul: bool,
) -> tuple[int, list[str], str]:
    owners = owner_offsets(row)
    gate(owners, f"no U32 owners {row['record_id']}")
    old_addresses: list[str] = []
    new_addr = None
    for owner in owners:
        pointer = struct.unpack_from("<I", current, owner)[0]
        live = bytes(current[pointer - ROM_BASE : pointer - ROM_BASE + len(old_payload)])
        gate(live == old_payload, f"live mismatch {row['record_id']} owner 0x{owner:08X}")
        old_addresses.append(f"0x{pointer:08X}")
        written_addr, cave_cursor = write_payload(
            candidate,
            pointer,
            new_payload,
            len(old_payload),
            allowed,
            cave_cursor,
            require_nul=require_nul,
        )
        if written_addr != pointer:
            struct.pack_into("<I", candidate, owner, written_addr)
            allowed.update(range(owner, owner + 4))
        new_addr = written_addr
    gate(new_addr is not None, f"no payload written {row['record_id']}")
    return cave_cursor, old_addresses, f"0x{new_addr:08X}"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    original = ORIGINAL_ROM.read_bytes()
    current = MAIN_TIP_ROM.read_bytes()
    main_manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(len(current) == 32 * 1024 * 1024, "main TIP size drift")
    gate(sha256(current) == main_manifest.get("sha256"), "main TIP/manifest hash drift")
    gate(all(value == 0 for value in current[CAVE_START:CAVE_END]), "apsaras cave is not zero-filled")
    gate(MAIN_SAV.exists(), "current main SAV missing")

    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    targets = [
        row
        for row in merged["records"]
        if needs_rewrite(str(row.get("translation_ko") or ""))
        or any(needs_rewrite(str(item)) for item in (row.get("translation_segments") or []))
        or str(row.get("record_id")) in REWRAP
    ]
    gate(targets, "no 앱살라스/재판은 사양 rows found")
    leftover_scopes = {str(row.get("source_scope")) for row in targets} - {
        "scenario_map_script",
        "scenario_main",
        "non_scenario_ui",
    }
    gate(not leftover_scopes, f"unexpected scopes {sorted(leftover_scopes)}")

    planned: list[tuple[dict[str, Any], str, list[str], list[str]]] = []
    hangul: set[str] = set()
    for row in targets:
        before = str(row.get("translation_ko") or "")
        old_segments = [str(item) for item in (row.get("translation_segments") or [])]
        after, new_segments = apply_row_text(row)
        gate(len(new_segments) == len(old_segments), f"segment count drift {row['record_id']}")
        if row.get("source_scope") in {"scenario_map_script", "scenario_main"}:
            for text in visible_segments(new_segments) or after.split("\n"):
                gate(
                    "\n" not in text and len(text) <= MAX_DIALOGUE_CELLS,
                    f"dialogue width {row['record_id']} len={len(text)} text={text!r}",
                )
        hangul.update(hangul_chars(before))
        hangul.update(hangul_chars(after))
        for text in old_segments + new_segments:
            hangul.update(hangul_chars(text))
        planned.append((row, before, old_segments, new_segments))

    font12 = load_galmuri12()
    font8 = load_galmuri8()
    live12, live8 = unified.collect_live_slots(original, merged["records"])
    candidate = bytearray(current)
    allowed: set[int] = set()
    occupied12: set[int] = set()
    occupied8: set[int] = set()
    painted: list[dict[str, str]] = []
    recovered12: dict[str, int] = {}
    recovered8: dict[str, int] = {}
    for char in sorted(hangul):
        recovered12[char] = recover_or_paint(
            candidate,
            original,
            font12,
            char,
            choose_free=choose_free_12x12,
            paint=paint_12x12,
            packed=packed_12x12,
            live=live12,
            occupied=occupied12,
            allowed=allowed,
            painted=painted,
            label="12x12",
            relocated=FONT12_RELOCATED,
            stride=fontops.FONT_12X12_STRIDE,
            count=fontops.FONT_12X12_COUNT,
        )
        recovered8[char] = recover_or_paint(
            candidate,
            original,
            font8,
            char,
            choose_free=choose_free_8x16,
            paint=paint_8x16,
            packed=packed_8x16,
            live=live8,
            occupied=occupied8,
            allowed=allowed,
            painted=painted,
            label="8x16",
            relocated=FONT8_RELOCATED,
            stride=fontops.FONT_8X16_STRIDE,
            count=fontops.FONT_8X16_COUNT,
        )

    identified = load_identified_12x12()
    verified12 = unified.load_verified_charmap(unified.CHARMAP_12X12_PATH)
    verified8 = unified.load_verified_charmap(unified.CHARMAP_8X16_PATH)
    cave_cursor = CAVE_START
    evidence: list[dict[str, Any]] = []
    counts = Counter()

    for row, before, old_segments, new_segments in planned:
        after = "\n".join(visible_segments(new_segments)) if new_segments else rewrite_text(before)
        row["translation_ko"] = after
        row["translation_segments"] = new_segments
        row["translation_status"] = "translated"
        row["translation_source"] = "user_verified"
        row["review_status"] = "user_verified"
        row["review_count"] = int(row.get("review_count") or 0) + 1
        row["reviewed_at"] = "2026-09-08"
        row["translator_notes"] = NOTES
        row["qa_status"] = "static_consumer_verified"
        row["overlay_batch_id"] = BATCH_ID
        update_payload_hash(row)

        scope = str(row.get("source_scope"))
        if scope == "scenario_map_script":
            cave_cursor, written = patch_map_row(
                row,
                old_segments,
                new_segments,
                current,
                candidate,
                recovered12,
                identified,
                allowed,
                cave_cursor,
            )
            counts["map_script"] += 1
            evidence.append(
                {
                    "record_id": row["record_id"],
                    "source_scope": scope,
                    "before": before,
                    "after": after,
                    "segments": written,
                }
            )
            continue

        if scope == "scenario_main":
            old_row = dict(row)
            old_row["translation_segments"] = old_segments
            old_payload, old_missing = unified.rebuild_scenario_payload(
                old_row, recovered12, verified12, translate=True
            )
            new_payload, new_missing = unified.rebuild_scenario_payload(
                row, recovered12, verified12, translate=True
            )
            gate(old_payload is not None and not old_missing, f"scenario old rebuild failed {row['record_id']}: {old_missing}")
            gate(new_payload is not None and not new_missing, f"scenario new rebuild failed {row['record_id']}: {new_missing}")
            cave_cursor, old_addresses, new_addr = patch_owned_payload(
                row,
                old_payload,
                new_payload,
                current,
                candidate,
                allowed,
                cave_cursor,
                require_nul=False,
            )
            counts["scenario"] += 1
            evidence.append(
                {
                    "record_id": row["record_id"],
                    "source_scope": scope,
                    "before": before,
                    "after": after,
                    "old_active_addresses": old_addresses,
                    "new_address": new_addr,
                    "encoded_size": len(new_payload),
                }
            )
            continue

        gate(scope == "non_scenario_ui", f"unexpected scope {row['record_id']}")
        owners = owner_offsets(row)
        gate(owners, f"UI has no U32 owners {row['record_id']}")
        pointer = struct.unpack_from("<I", current, owners[0])[0]
        live = payload_at(current, pointer)
        old_ko = before
        encoded12_old, miss12_old = unified.encode_korean_text(
            old_ko, recovered12, verified_charmap=verified12, strict_punctuation=True
        )
        encoded8_old, miss8_old = unified.encode_korean_text(
            old_ko, recovered8, verified_charmap=verified8, strict_punctuation=True
        )
        if encoded12_old == live and not miss12_old:
            font_used = "12x12"
            new_payload, miss_new = unified.encode_korean_text(
                after, recovered12, verified_charmap=verified12, strict_punctuation=True
            )
            gate(new_payload is not None and not miss_new, f"UI 12x12 encode failed {row['record_id']}: {miss_new}")
            old_payload = encoded12_old
        elif encoded8_old == live and not miss8_old:
            font_used = "8x16"
            new_payload, miss_new = unified.encode_korean_text(
                after, recovered8, verified_charmap=verified8, strict_punctuation=True
            )
            gate(new_payload is not None and not miss_new, f"UI 8x16 encode failed {row['record_id']}: {miss_new}")
            old_payload = encoded8_old
        else:
            raise SystemExit(
                f"gate failed: UI live encode mismatch {row['record_id']} "
                f"live={live.hex()} 12={None if encoded12_old is None else encoded12_old.hex()} "
                f"8={None if encoded8_old is None else encoded8_old.hex()} miss12={miss12_old} miss8={miss8_old}"
            )
        cave_cursor, old_addresses, new_addr = patch_owned_payload(
            row,
            old_payload,
            new_payload,
            current,
            candidate,
            allowed,
            cave_cursor,
            require_nul=True,
        )
        counts["ui"] += 1
        evidence.append(
            {
                "record_id": row["record_id"],
                "source_scope": scope,
                "font": font_used,
                "before": before,
                "after": after,
                "old_active_addresses": old_addresses,
                "new_address": new_addr,
                "encoded_size": len(new_payload),
            }
        )

    leftover = [
        row["record_id"]
        for row in merged["records"]
        if needs_rewrite(str(row.get("translation_ko") or ""))
        or any(needs_rewrite(str(item)) for item in (row.get("translation_segments") or []))
    ]
    gate(not leftover, f"rewrite leftover: {leftover[:8]}")
    changed = [index for index, (before, after) in enumerate(zip(current, candidate)) if before != after]
    gate(set(changed) <= allowed, f"unexpected ROM byte change x{len(set(changed) - allowed)}")
    gate(bytes(candidate[MAP_BANK[0] : MAP_BANK[1]]) == current[MAP_BANK[0] : MAP_BANK[1]], "original map-script bank changed")
    gate(sha256(MAIN_TIP_ROM.read_bytes()) == sha256(current), "main TIP mutated during patch")

    parent_identity = str(merged.get("identity", {}).get("translation_overlay_identity_sha256") or "")
    new_identity = digest(
        {
            "parent": parent_identity,
            "batch_id": BATCH_ID,
            "records": [row["record_id"] for row, _before, _old, _new in planned],
        }
    )
    identity = merged.setdefault("identity", {})
    identity["parent_translation_overlay_identity_sha256"] = parent_identity
    identity["apsaras_zentetsu_unify_identity_sha256"] = new_identity
    identity["translation_overlay_identity_sha256"] = new_identity
    status_counts = dict(sorted(Counter(str(row.get("translation_status") or "") for row in merged["records"]).items()))
    summary = merged.setdefault("summary", {})
    summary["merged_translation_status_counts"] = status_counts
    summary["translation_overlay_identity_sha256"] = new_identity
    merged["apsaras_zentetsu_unify_20260908"] = {
        "batch_id": BATCH_ID,
        "changed_records": [row["record_id"] for row, _before, _old, _new in planned],
        "rewrap": sorted(REWRAP),
    }
    payload_json = json.dumps(merged, ensure_ascii=False, indent=2) + "\n"
    SNAPSHOT.write_text(payload_json, encoding="utf-8")
    TRANSLATION_MERGED_JSON.write_text(payload_json, encoding="utf-8")
    update_translation_manifest(merged, SNAPSHOT)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(bytes(candidate))
    shutil.copy2(MAIN_SAV, OUT_SAV)
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_apsaras_zentetsu_candidate_20260908",
        "result": "PASS",
        "batch_id": BATCH_ID,
        "painted_glyphs": painted,
        "cave": {"start": hex(CAVE_START), "end": hex(cave_cursor), "capacity_end": hex(CAVE_END)},
        "counts": dict(counts),
        "changed_records": len(planned),
        "jobs": evidence,
        "parent": {"path": advance_relative(MAIN_TIP_ROM), "sha256": sha256(current)},
        "output": {"path": advance_relative(OUTPUT), "sha256": sha256(candidate), "size": len(candidate)},
        "sav": {"path": advance_relative(OUT_SAV), "byte_exact_copy": OUT_SAV.read_bytes() == MAIN_SAV.read_bytes()},
        "translation_source": {
            "path": advance_relative(TRANSLATION_MERGED_JSON),
            "sha256": sha256(payload_json.encode("utf-8")),
        },
        "verification": {
            "result": "PASS",
            "original_map_script_bank_unchanged": True,
            "dialogue_width_limit": MAX_DIALOGUE_CELLS,
            "no_apsalus_or_saiban_leftover": True,
            "runtime_emulator": "not run; static ROM verification only",
            "changed_bytes": len(changed),
        },
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    MANIFEST.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "result": "PASS",
                "painted_glyphs": painted,
                "cave": report["cave"],
                "counts": report["counts"],
                "changed_records": len(planned),
                "output": report["output"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
