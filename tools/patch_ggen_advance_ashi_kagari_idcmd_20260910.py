#!/usr/bin/env python3
"""Fix 足つき nickname, Kagari 姉として, and overflowing ID-command effects.

1. 足つき/足付き is slang, not Archangel's proper name. Korean keeps the
   nickname as 발달린놈 (14-cell map lines).
2. Kagari ``<0355>として……`` (姉) was pending, so the JP line still drew.
3. ID-command 8x16 effect summaries clip after 8 cells (ss showed
   ``자신 HP완전회``). Space-compress remaining 9–10 cell lines.
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
import patch_ggen_advance_apsaras_zentetsu_20260908 as apsaras_mod  # noqa: E402
from ggen_advance_painted_glyph_identity import (  # noqa: E402
    FONT8_RELOCATED,
    FONT12_RELOCATED,
    load_galmuri12,
    load_galmuri8,
    packed_12x12,
    packed_8x16,
    paint_8x16,
    recover_unique_12x12_slots,
    recover_unique_8x16_slots,
    verify_payload_painted,
)
from ggen_advance_project_paths import (  # noqa: E402
    MAIN_TIP_MANIFEST,
    MAIN_TIP_ROM,
    ORIGINAL_ROM,
    TRANSLATION_MERGED_JSON,
    advance_relative,
)
from merge_ggen_advance_translation_overlays import digest  # noqa: E402
from patch_ggen_advance_apsaras_zentetsu_20260908 import (  # noqa: E402
    choose_free_12x12,
    find_lookups,
    hangul_chars,
    paint_12x12,
    recover_or_paint,
    visible_segments,
    write_payload,
)
from patch_ggen_advance_dialogue_idcmd_fit_20260909 import (  # noqa: E402
    live_char_tokens,
    write_padded,
)
from patch_ggen_advance_idcmd_ecm_mishudeuk_20260905 import (  # noqa: E402
    verified_from_charmap,
    verify_hangul_12x12,
    verify_mixed_8x16,
)
from patch_ggen_advance_idcmd_list_fit_20260909 import (  # noqa: E402
    CHARMAP_8,
    encode_8x16,
    try_recover_slot,
)
from patch_ggen_advance_intermission_text_consumers_20260904 import (  # noqa: E402
    ROM_BASE,
    gate,
    payload_at,
    sha256,
    u32,
)
from patch_ggen_advance_kimi_jane_to_neo_20260904 import (  # noqa: E402
    owner_offsets,
    update_payload_hash,
    update_translation_manifest,
)
from patch_ggen_advance_map_script_inline_poc import (  # noqa: E402
    load_identified_12x12,
    raw_hex_bytes,
)
from patch_ggen_advance_name_unify_20260909 import (  # noqa: E402
    encode_overlay,
    patch_map_row_live,
)

BATCH_ID = "ashi-kagari-idcmd-effect-20260910"
IDENTITY_KEY = "ashi_kagari_idcmd_effect_sha256"
BATCH_KEY = "ashi_kagari_idcmd_effect_20260910"
REPORT_KIND = "ggen_advance_ashi_kagari_idcmd_candidate_20260910"
SNAPSHOT = ROOT / "analysis" / "ggen_advance_translation_merged_20260910_ashi_kagari_idcmd.json"
OUT_DIR = ROOT / "outputs" / "20260910_ggen_advance_ashi_kagari_idcmd"
OUTPUT = OUT_DIR / "ggen_advance_ashi_kagari_idcmd_candidate_20260910.gba"
OUT_SAV = OUT_DIR / "ggen_advance_ashi_kagari_idcmd_candidate_20260910.sav"
MAIN_SAV = ROOT / "SD Gundam GGeneration Advance (Korean).sav"
REPORT = ROOT / "analysis" / "ggen_advance_ashi_kagari_idcmd_candidate_20260910.json"
MANIFEST = OUT_DIR / "manifest.json"
CAVE_START = 0x012B23F0
CAVE_END = 0x012B3000
MAP_BANK = (0x00F00000, 0x00FC0000)
VISUAL_DIALOGUE_CELLS = 14
EFFECT_CAP = 8
LIVE_LOOKUP_TABLE = 0x01308000
LIVE_LOOKUP_PTR_OFF = 0x01112588
LIVE_LOOKUP_COUNT_OFF = 0x0111258C
LIVE_LOOKUP_PTR = 0x09308000
LOOKUP_ENTRY_SIZE = 12
NOTES = (
    "足つき는 발달린놈. 카가리 姉として는 누나로서. "
    "ID커맨드 효과 요약 8칸"
)

MAP_JOBS: dict[str, list[str]] = {
    "GGA-MAPSCRIPT-00F5A936": ["「발달린놈」포착하는 대로", "우리는 쳐나간다"],
    "GGA-MAPSCRIPT-00F5E750": ["……그럼 『발달린놈』은", "남미에 내릴 수없단건가？"],
    "GGA-MAPSCRIPT-00F5E87A": ["유감스럽게도 발달린놈도", "신형도 놓쳤다"],
    "GGA-MAPSCRIPT-00F675E1": ["저거로군？", "목마와 발달린놈이라는게"],
    "GGA-MAPSCRIPT-00F68834": ["이쪽으로서는 발달린놈만", "해치울 수 있다면……"],
    "GGA-MAPSCRIPT-00F71C76": ["저 붉은 혜성도 목마와", "발달린놈엔 애를 먹나……"],
    "GGA-MAPSCRIPT-00F82B7C": ["그보다, 발달린놈은", "포착했나?"],
    "GGA-MAPSCRIPT-00F84F9C": ["아아, 알고 있어", "발달린놈을떨어뜨리겠지!?"],
    "GGA-MAPSCRIPT-00F98622": ["아무래도 적의 발달린놈도", "같은 모양이다"],
    "GGA-MAPSCRIPT-00FA7C28": ["게다가 목마와 발달린놈까지", "다 모여 있잖아"],
    "GGA-MAPSCRIPT-00FB5860": ["발달린놈이 자브로에", "나타난다는 정보가 들어왔다"],
    "GGA-MAPSCRIPT-00FB58AA": ["발달린놈이 자브로에……"],
}
FRESH_MAP_JOBS: dict[str, list[str]] = {
    "GGA-MAPSCRIPT-00F8637A": ["누나로서……"],
}
EFFECT_JOBS: dict[str, dict[str, str]] = {
    "GGA-TEXT-0017B480": {"old": "특수방어무효＋위력↑", "new": "특방무효＋위력↑"},
    "GGA-TEXT-0017BA8D": {"old": "1턴 아군 공격력↑", "new": "1턴아군공격력↑"},
    "GGA-TEXT-0017C5A1": {"old": "특수방어무효＋반응↑", "new": "특방무효＋반응↑"},
    "GGA-TEXT-0017CBA1": {"old": "특수방어무효＋공격↑", "new": "특방무효＋공격↑"},
    "GGA-TEXT-0017CEA1": {"old": "1턴 아군 전능력↑", "new": "1턴아군전능력↑"},
    "GGA-TEXT-0017B35C": {"old": "1턴 아군 능력↑", "new": "1턴아군능력↑"},
    "GGA-TEXT-0017B3A8": {"old": "1턴 공격·방어↑", "new": "1턴공격·방어↑"},
    "GGA-TEXT-0017B3F1": {"old": "1턴 방어·명중↑", "new": "1턴방어·명중↑"},
    "GGA-TEXT-0017B422": {"old": "아군 HP완전회복", "new": "아군HP완전회복"},
    "GGA-TEXT-0017B4EA": {"old": "특수방어무효＋통격", "new": "특방무효＋통격"},
    "GGA-TEXT-0017B510": {"old": "이동 강화＋회피↑", "new": "이동강화＋회피↑"},
    "GGA-TEXT-0017B5B8": {"old": "자신 HP완전회복", "new": "자신HP완전회복"},
    "GGA-TEXT-0017B628": {"old": "1턴 아군 명중↑", "new": "1턴아군명중↑"},
    "GGA-TEXT-0017B6AB": {"old": "아군 위력·명중↑", "new": "아군위력·명중↑"},
    "GGA-TEXT-0017B747": {"old": "ID 커맨드 봉인", "new": "ID커맨드봉인"},
    "GGA-TEXT-0017B7D4": {"old": "1턴 위력·명중↑", "new": "1턴위력·명중↑"},
    "GGA-TEXT-0017B8F4": {"old": "산개 봉인＋공격↑", "new": "산개봉인＋공격↑"},
    "GGA-TEXT-0017B9BE": {"old": "1턴 능력↑＋선제", "new": "1턴능력↑＋선제"},
    "GGA-TEXT-0017BAE2": {"old": "적 방어력·명중↓", "new": "적방어력·명중↓"},
    "GGA-TEXT-0017BB86": {"old": "산개 봉인＋위력↑", "new": "산개봉인＋위력↑"},
    "GGA-TEXT-0017BBA5": {"old": "자군 공격·방어↑", "new": "자군공격·방어↑"},
    "GGA-TEXT-0017BC04": {"old": "1턴 자신 능력↑", "new": "1턴자신능력↑"},
    "GGA-TEXT-0017BC1A": {"old": "공격 봉인＋위력↑", "new": "공격봉인＋위력↑"},
    "GGA-TEXT-0017BF92": {"old": "산개·특수방어무효", "new": "산개·특방무효"},
    "GGA-TEXT-0017C0D1": {"old": "아군 명중·위력↑", "new": "아군명중·위력↑"},
    "GGA-TEXT-0017C387": {"old": "1턴 위력·장갑↑", "new": "1턴위력·장갑↑"},
    "GGA-TEXT-0017C408": {"old": "1턴 공격·장갑↑", "new": "1턴공격·장갑↑"},
    "GGA-TEXT-0017C876": {"old": "1턴 아군 위력↑", "new": "1턴아군위력↑"},
    "GGA-TEXT-0017CD36": {"old": "1턴 아군 방어↑", "new": "1턴아군방어↑"},
    "GGA-TEXT-0017CDCA": {"old": "공격 봉인＋명중↑", "new": "공격봉인＋명중↑"},
}


def payload_token_stream(rom: bytes | bytearray, address: int, limit: int = 128) -> bytes:
    """Read a NUL-terminated 8x16/12x12 token stream.

    ``payload_at`` stops at the first 0x00 byte, which truncates ``E0 00``
    (digit 1) and similar tokens.  Walk E0–FF as 2-byte tokens.
    """
    offset = address - ROM_BASE
    gate(0 <= offset < len(rom), f"payload address outside ROM: 0x{address:08X}")
    index = offset
    end = min(len(rom), offset + limit)
    while index < end:
        lead = rom[index]
        if lead == 0:
            return bytes(rom[offset : index + 1])
        if lead >= 0xE0:
            gate(index + 1 < end, f"truncated token at 0x{address:08X}")
            index += 2
        else:
            index += 1
    raise SystemExit(f"gate failed: unterminated token payload: 0x{address:08X}")


def lookup_hits(rom: bytes, orig_addr: int, expected_end: int) -> list[tuple[int, int, int]]:
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
    return hits


def insert_live_lookup(
    candidate: bytearray,
    orig: int,
    neu: int,
    orig_end: int,
    allowed: set[int],
) -> int:
    ptr = struct.unpack_from("<I", candidate, LIVE_LOOKUP_PTR_OFF)[0]
    gate(ptr == LIVE_LOOKUP_PTR, f"live lookup pointer drift 0x{ptr:08X}")
    count = struct.unpack_from("<I", candidate, LIVE_LOOKUP_COUNT_OFF)[0]
    lo = 0
    hi = count
    while lo < hi:
        mid = (lo + hi) // 2
        current_orig = struct.unpack_from("<I", candidate, LIVE_LOOKUP_TABLE + mid * LOOKUP_ENTRY_SIZE)[0]
        if current_orig < orig:
            lo = mid + 1
        else:
            hi = mid
    if lo < count:
        existing = struct.unpack_from("<I", candidate, LIVE_LOOKUP_TABLE + lo * LOOKUP_ENTRY_SIZE)[0]
        gate(existing != orig, f"duplicate live lookup 0x{orig:08X}")
    start = LIVE_LOOKUP_TABLE + lo * LOOKUP_ENTRY_SIZE
    old_end = LIVE_LOOKUP_TABLE + count * LOOKUP_ENTRY_SIZE
    room = bytes(candidate[old_end : old_end + LOOKUP_ENTRY_SIZE])
    gate(room == b"\x00" * LOOKUP_ENTRY_SIZE, "live lookup table has no trailing room")
    candidate[start + LOOKUP_ENTRY_SIZE : old_end + LOOKUP_ENTRY_SIZE] = candidate[start:old_end]
    struct.pack_into("<III", candidate, start, orig, neu, orig_end)
    allowed.update(range(start, old_end + LOOKUP_ENTRY_SIZE))
    struct.pack_into("<I", candidate, LIVE_LOOKUP_COUNT_OFF, count + 1)
    allowed.update(range(LIVE_LOOKUP_COUNT_OFF, LIVE_LOOKUP_COUNT_OFF + 4))
    return lo


def mark_row(row: dict[str, Any], after: str, new_segments: list[str]) -> None:
    row["translation_ko"] = after
    row["translation_segments"] = new_segments
    row["translation_status"] = "translated"
    row["translation_source"] = "user_verified"
    row["review_status"] = "user_verified"
    row["review_count"] = int(row.get("review_count") or 0) + 1
    row["reviewed_at"] = "2026-09-10"
    row["translator_notes"] = NOTES
    row["qa_status"] = "static_consumer_verified"
    row["overlay_batch_id"] = BATCH_ID
    update_payload_hash(row)


def plan_map_row(row: dict[str, Any], new_visible: list[str]) -> tuple[str, list[str], list[str]]:
    record_id = str(row["record_id"])
    before = str(row.get("translation_ko") or "")
    old_segments = [str(item) for item in (row.get("translation_segments") or [])]
    if old_segments:
        old_visible = visible_segments(old_segments)
        gate(len(old_visible) == len(new_visible), f"visible count {record_id}")
        new_segments: list[str] = []
        visible_index = 0
        for item in old_segments:
            if item:
                new_segments.append(new_visible[visible_index])
                visible_index += 1
            else:
                new_segments.append(item)
        gate(visible_index == len(new_visible), f"framing {record_id}")
    else:
        gate(len(list(row.get("segments") or [])) == len(new_visible), f"fresh segment count {record_id}")
        new_segments = list(new_visible)
        old_segments = [""] * len(new_segments)
    after = "\n".join(new_visible)
    gate(after != before or new_segments != old_segments, f"no-op {record_id}")
    return before, old_segments, new_segments


def patch_map_row_fresh(
    row: dict[str, Any],
    new_segments: list[str],
    current: bytes,
    candidate: bytearray,
    recovered12: dict[str, int],
    identified: dict[str, int],
    verified12: dict[str, int],
    allowed: set[int],
    cave_cursor: int,
) -> tuple[int, list[dict[str, Any]]]:
    segments = list(row.get("segments") or [])
    gate(len(segments) == len(new_segments), f"fresh framing {row['record_id']}")
    cursor = int(str(row["target_file_offset"]), 16)
    written: list[dict[str, Any]] = []
    first_new_addr: int | None = None
    first_old_end: int | None = None
    for index, (segment, new_text) in enumerate(zip(segments, new_segments)):
        original_bytes = raw_hex_bytes(str(segment.get("raw_hex") or ""))
        gate(original_bytes.endswith(b"\x00"), f"fresh segment missing NUL {row['record_id']}")
        orig_addr = ROM_BASE + cursor
        orig_end = orig_addr + len(original_bytes) - 1
        encoded_new = encode_overlay(new_text, recovered12, verified12, {}, identified=identified)
        lookups = lookup_hits(current, orig_addr, orig_end)
        inserted = False
        if lookups:
            neu = lookups[0][1]
            old_payload = payload_at(current, neu)
            new_addr, cave_cursor = write_payload(
                candidate, neu, encoded_new, len(old_payload), allowed, cave_cursor
            )
            if new_addr != neu:
                for lookup_pos, _neu, _end in lookups:
                    struct.pack_into("<I", candidate, lookup_pos + 4, new_addr)
                    allowed.update(range(lookup_pos + 4, lookup_pos + 8))
        else:
            neu = 0
            new_addr, cave_cursor = write_payload(
                candidate, 0, encoded_new, 0, allowed, cave_cursor
            )
            insert_live_lookup(candidate, orig_addr, new_addr, orig_end, allowed)
            inserted = True
            lookups = lookup_hits(candidate, orig_addr, orig_end)
            gate(lookups, f"fresh lookup insert missing for 0x{orig_addr:08X}")
            neus = {item[1] for item in lookups}
            gate(neus == {new_addr}, f"fresh lookup neu drift 0x{orig_addr:08X}")
        start = new_addr - ROM_BASE
        gate(not (MAP_BANK[0] <= start < MAP_BANK[1]), f"fresh write hit map bank {row['record_id']}")
        if index == 0:
            first_new_addr = new_addr
            first_old_end = orig_end
        written.append(
            {
                "segment": index,
                "old": str(segment.get("source_text") or ""),
                "new": new_text,
                "cells": len(new_text),
                "old_payload": f"0x{neu:08X}" if neu else None,
                "new_payload": f"0x{new_addr:08X}",
                "encoded_size": len(encoded_new),
                "lookup_count": len(lookups),
                "lookup_inserted": inserted,
            }
        )
        cursor += len(original_bytes)
    opcode_text = str(row.get("opcode_18_file_offset") or "")
    if opcode_text and first_new_addr is not None and first_old_end is not None:
        opcode_addr = ROM_BASE + int(opcode_text, 16)
        if opcode_addr != ROM_BASE + int(str(row["target_file_offset"]), 16):
            alias_hits = lookup_hits(current, opcode_addr, first_old_end)
            if alias_hits:
                for alias_pos, alias_neu, _alias_end in alias_hits:
                    if alias_neu != first_new_addr:
                        struct.pack_into("<I", candidate, alias_pos + 4, first_new_addr)
                        allowed.update(range(alias_pos + 4, alias_pos + 8))
            else:
                insert_live_lookup(candidate, opcode_addr, first_new_addr, first_old_end, allowed)
                alias_hits = lookup_hits(candidate, opcode_addr, first_old_end)
                gate(alias_hits, f"fresh opcode lookup insert missing for 0x{opcode_addr:08X}")
                neus = {item[1] for item in alias_hits}
                gate(neus == {first_new_addr}, f"fresh opcode neu drift 0x{opcode_addr:08X}")
            written[0]["opcode_alias"] = f"0x{opcode_addr:08X}"
            written[0]["opcode_lookup_count"] = len(alias_hits)
    return cave_cursor, written


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    apsaras_mod.CAVE_END = CAVE_END
    for table in (MAP_JOBS, FRESH_MAP_JOBS):
        for record_id, lines in table.items():
            for line in lines:
                gate("\n" not in line, f"newline in {record_id}: {line!r}")
                gate(len(line) <= VISUAL_DIALOGUE_CELLS, f"{record_id} {len(line)}>{VISUAL_DIALOGUE_CELLS}: {line!r}")
    for record_id, spec in EFFECT_JOBS.items():
        gate(len(spec["new"]) <= EFFECT_CAP, f"{record_id} effect {spec['new']!r} is {len(spec['new'])}>{EFFECT_CAP}")
        extra = hangul_chars(spec["new"]) - hangul_chars(spec["old"])
        gate(not extra, f"{record_id} new Hangul {extra}")

    original = ORIGINAL_ROM.read_bytes()
    current = MAIN_TIP_ROM.read_bytes()
    main_manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(len(current) == 32 * 1024 * 1024, "main TIP size drift")
    gate(sha256(current) == main_manifest.get("sha256"), "main TIP/manifest hash drift")
    gate(u32(current, LIVE_LOOKUP_PTR_OFF) == LIVE_LOOKUP_PTR, "live lookup pointer drift")
    gate(all(value == 0 for value in current[CAVE_START:CAVE_END]), "ashi cave is not zero-filled")
    gate(MAIN_SAV.exists(), "current main SAV missing")

    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    by_id = {str(row["record_id"]): row for row in merged["records"]}
    wanted = set(MAP_JOBS) | set(FRESH_MAP_JOBS) | set(EFFECT_JOBS)
    missing = sorted(wanted - set(by_id))
    gate(not missing, f"records missing {missing}")

    planned_map: list[tuple[str, dict[str, Any], str, list[str], list[str]]] = []
    hangul12: set[str] = set()
    hangul8: set[str] = set()
    for record_id, new_visible in MAP_JOBS.items():
        row = by_id[record_id]
        before, old_segments, new_segments = plan_map_row(row, new_visible)
        hangul12.update(hangul_chars(before))
        hangul12.update(hangul_chars("\n".join(new_visible)))
        for text in old_segments + new_segments:
            hangul12.update(hangul_chars(text))
        planned_map.append(("live", row, before, old_segments, new_segments))
    for record_id, new_visible in FRESH_MAP_JOBS.items():
        row = by_id[record_id]
        before, old_segments, new_segments = plan_map_row(row, new_visible)
        hangul12.update(hangul_chars("\n".join(new_visible)))
        planned_map.append(("fresh", row, before, old_segments, new_segments))
    for record_id, spec in EFFECT_JOBS.items():
        row = by_id[record_id]
        gate(str(row.get("semantic_category")) == "id_command_effect_summary", f"{record_id} category")
        gate(str(row.get("translation_ko") or "") == spec["old"], f"{record_id} Korean drift {row.get('translation_ko')!r}")
        hangul8.update(hangul_chars(spec["old"]))
        hangul8.update(hangul_chars(spec["new"]))

    ashi_ids = [
        str(row["record_id"])
        for row in merged["records"]
        if row.get("scope_status") != "alias"
        and ("足つき" in str(row.get("source_text") or "") or "足付き" in str(row.get("source_text") or ""))
    ]
    gate(set(ashi_ids) == set(MAP_JOBS), f"足つき set drift {sorted(set(ashi_ids) ^ set(MAP_JOBS))}")

    font12 = load_galmuri12()
    font8 = load_galmuri8()
    live8, live12 = unified.collect_live_slots(original, merged["records"])
    candidate = bytearray(current)
    allowed: set[int] = set()
    occupied12: set[int] = set()
    painted: list[dict[str, str]] = []
    recovered12: dict[str, int] = {}
    for char in sorted(hangul12):
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

    identified = load_identified_12x12()
    verified12 = unified.load_verified_charmap(unified.CHARMAP_12X12_PATH)
    cave_cursor = CAVE_START
    evidence: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()

    for kind, row, before, old_segments, new_segments in planned_map:
        record_id = str(row["record_id"])
        after = "\n".join(visible_segments(new_segments))
        mark_row(row, after, new_segments)
        gate(str(row.get("source_scope")) == "scenario_map_script", f"map scope {record_id}")
        if kind == "fresh":
            cave_cursor, written = patch_map_row_fresh(
                row,
                new_segments,
                current,
                candidate,
                recovered12,
                identified,
                verified12,
                allowed,
                cave_cursor,
            )
            counts["map_fresh"] += 1
        else:
            cave_cursor, written = patch_map_row_live(
                row,
                old_segments,
                new_segments,
                current,
                candidate,
                recovered12,
                identified,
                verified12,
                allowed,
                cave_cursor,
            )
            counts["map_script"] += 1
        evidence.append(
            {
                "record_id": record_id,
                "kind": kind,
                "before": before,
                "after": after,
                "cells": [len(line) for line in visible_segments(new_segments)],
                "segments": written,
            }
        )

    charmap = json.loads(CHARMAP_8.read_text(encoding="utf-8"))
    verified8 = verified_from_charmap(charmap)
    recovered8: dict[str, int] = {}
    recovered12_effect: dict[str, int] = {}
    paint_8_onto_12: set[str] = set()
    for char in hangul8:
        slot8 = try_recover_slot(recover_unique_8x16_slots, candidate, font8, char)
        slot12 = try_recover_slot(recover_unique_12x12_slots, candidate, font12, char)
        if slot8 is not None:
            recovered8[char] = slot8
            if slot12 is not None:
                recovered12_effect[char] = slot12
            continue
        if slot12 is None:
            raise SystemExit(f"gate failed: no unique painted slot for effect {char!r}")
        recovered12_effect[char] = slot12
        paint_8_onto_12.add(char)
    for char in sorted(paint_8_onto_12):
        slot = recovered12_effect[char]
        gate(slot not in live8, f"cannot paint 8x16 {char!r} at live slot 0x{slot:04X}")
        start = paint_8x16(candidate, slot, char, font8)
        allowed.update(range(start, start + fontops.FONT_8X16_STRIDE))
        recovered8[char] = slot
        painted.append({"font": "8x16-mirror", "char": char, "slot": f"0x{slot:04X}"})
    if paint_8_onto_12:
        verify_hangul_12x12(candidate, {char: recovered12_effect[char] for char in paint_8_onto_12}, font12)

    for record_id, spec in EFFECT_JOBS.items():
        row = by_id[record_id]
        owners = owner_offsets(row)
        gate(owners, f"{record_id} has no U32 owners")
        old_addresses = [u32(current, owner) for owner in owners]
        gate(len(set(old_addresses)) == 1, f"{record_id} owners point at different payloads")
        pointer = old_addresses[0]
        old_payload = payload_token_stream(current, pointer)
        live_tokens = live_char_tokens(spec["old"], old_payload)
        encoded_new = encode_8x16(spec["new"], recovered8, verified8, live_tokens)
        verify_mixed_8x16(candidate, original, encoded_new, spec["new"], font8, hangul_chars(spec["new"]), verified8)
        hangul_only = "".join(char for char in spec["new"] if char in hangul8)
        if hangul_only:
            hangul_payload = encode_8x16(hangul_only, recovered8, verified8)
            verify_payload_painted(candidate, hangul_payload, hangul_only, font8)
        start = pointer - ROM_BASE
        write_padded(candidate, start, encoded_new, old_payload, allowed)
        row["translation_ko"] = spec["new"]
        row["translation_status"] = "translated"
        row["translation_source"] = "user_verified"
        row["review_status"] = "user_verified"
        row["review_count"] = int(row.get("review_count") or 0) + 1
        row["reviewed_at"] = "2026-09-10"
        row["translator_notes"] = NOTES
        row["qa_status"] = "static_consumer_verified"
        row["overlay_batch_id"] = BATCH_ID
        update_payload_hash(row)
        counts["idcmd_effect"] += 1
        evidence.append(
            {
                "record_id": record_id,
                "kind": "effect",
                "before": spec["old"],
                "after": spec["new"],
                "before_cells": len(spec["old"]),
                "after_cells": len(spec["new"]),
                "payload": f"0x{pointer:08X}",
            }
        )

    stale_ashi = [
        str(row["record_id"])
        for row in merged["records"]
        if row.get("scope_status") != "alias"
        and ("足つき" in str(row.get("source_text") or "") or "足付き" in str(row.get("source_text") or ""))
        and "발달린놈" not in str(row.get("translation_ko") or "")
    ]
    gate(not stale_ashi, f"足つき not rewritten {stale_ashi}")
    leftover_name = [
        str(row["record_id"])
        for row in merged["records"]
        if row.get("scope_status") != "alias" and "아시츠키" in str(row.get("translation_ko") or "")
    ]
    gate(not leftover_name, f"아시츠키 leftover {leftover_name}")
    leftover_archangel = [
        record_id
        for record_id in MAP_JOBS
        if "아크엔젤" in str(by_id[record_id].get("translation_ko") or "")
    ]
    gate(not leftover_archangel, f"足つき still Archangel {leftover_archangel}")
    overflow_effects = [
        str(row["record_id"])
        for row in merged["records"]
        if row.get("semantic_category") == "id_command_effect_summary"
        and row.get("scope_status") != "alias"
        and str(row.get("translation_status") or "") == "translated"
        and len(str(row.get("translation_ko") or "").replace("\n", "")) > EFFECT_CAP
    ]
    gate(not overflow_effects, f"effect overflow remains {overflow_effects}")
    gate(str(by_id["GGA-MAPSCRIPT-00F8637A"].get("translation_ko")) == "누나로서……", "kagari drift")
    gate(str(by_id["GGA-TEXT-0017B5B8"].get("translation_ko")) == "자신HP완전회복", "self-heal drift")

    changed = [index for index, (before, after) in enumerate(zip(current, candidate)) if before != after]
    gate(set(changed) <= allowed, f"unexpected ROM byte change x{len(set(changed) - allowed)}")
    gate(bytes(candidate[MAP_BANK[0] : MAP_BANK[1]]) == current[MAP_BANK[0] : MAP_BANK[1]], "original map-script bank changed")
    gate(sha256(MAIN_TIP_ROM.read_bytes()) == sha256(current), "main TIP mutated during patch")
    gate(cave_cursor <= CAVE_END, "ashi cave overflow")

    parent_identity = str(merged.get("identity", {}).get("translation_overlay_identity_sha256") or "")
    new_identity = digest(
        {
            "parent": parent_identity,
            "batch_id": BATCH_ID,
            "map": sorted(MAP_JOBS) + sorted(FRESH_MAP_JOBS),
            "effects": sorted(EFFECT_JOBS),
        }
    )
    identity = merged.setdefault("identity", {})
    identity["parent_translation_overlay_identity_sha256"] = parent_identity
    identity[IDENTITY_KEY] = new_identity
    identity["translation_overlay_identity_sha256"] = new_identity
    status_counts = dict(sorted(Counter(str(row.get("translation_status") or "") for row in merged["records"]).items()))
    summary = merged.setdefault("summary", {})
    summary["merged_translation_status_counts"] = status_counts
    summary["translation_overlay_identity_sha256"] = new_identity
    merged[BATCH_KEY] = {
        "batch_id": BATCH_ID,
        "map_records": sorted(MAP_JOBS) + sorted(FRESH_MAP_JOBS),
        "effect_records": sorted(EFFECT_JOBS),
        "visual_dialogue_cells": VISUAL_DIALOGUE_CELLS,
        "effect_cap": EFFECT_CAP,
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
        "kind": REPORT_KIND,
        "result": "PASS",
        "batch_id": BATCH_ID,
        "painted_glyphs": painted,
        "cave": {"start": hex(CAVE_START), "end": hex(cave_cursor), "capacity_end": hex(CAVE_END)},
        "counts": dict(counts),
        "changed_records": len(planned_map) + len(EFFECT_JOBS),
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
            "visual_dialogue_cells": VISUAL_DIALOGUE_CELLS,
            "effect_cap": EFFECT_CAP,
            "ashi_leftover": 0,
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
                "changed_records": report["changed_records"],
                "output": report["output"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
