#!/usr/bin/env python3
"""Unify scenario/UI name spellings requested 20260909.

- 무 라 프라가 / vocative 무 (ムウ) -> 무우 라 프라가 / 무우
- 노이에른 비터 -> 노이엔 비터 (ノイエン・ビッター)
- 애너벨 가토 -> 아나벨 가토
- 동방불패 왕자의 풍격이다 -> 왕자의 바람이다

武의 길/소양, 무의미, and the elongated shout 무우웃!! are left alone.
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
    load_galmuri12,
    load_galmuri8,
    packed_12x12,
    packed_8x16,
    paint_8x16,
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
    choose_free_8x16,
    find_lookups,
    hangul_chars,
    paint_12x12,
    patch_owned_payload,
    recover_or_paint,
    visible_segments,
    write_payload,
)
from patch_ggen_advance_dialogue_idcmd_fit_20260909 import (  # noqa: E402
    live_char_tokens,
    read_tokens,
)
from patch_ggen_advance_intermission_text_consumers_20260904 import (  # noqa: E402
    gate,
    payload_at,
    sha256,
)
from patch_ggen_advance_kimi_jane_to_neo_20260904 import (  # noqa: E402
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

BATCH_ID = "name-unify-muu-neuen-anavel-20260909"
IDENTITY_KEY = "name_unify_muu_neuen_anavel_sha256"
BATCH_KEY = "name_unify_muu_neuen_anavel_20260909"
REPORT_KIND = "ggen_advance_name_unify_candidate_20260909"
SNAPSHOT = ROOT / "analysis" / "ggen_advance_translation_merged_20260909_name_unify.json"
OUT_DIR = ROOT / "outputs" / "20260909_ggen_advance_name_unify"
OUTPUT = OUT_DIR / "ggen_advance_name_unify_candidate_20260909.gba"
OUT_SAV = OUT_DIR / "ggen_advance_name_unify_candidate_20260909.sav"
MAIN_SAV = ROOT / "SD Gundam GGeneration Advance (Korean).sav"
REPORT = ROOT / "analysis" / "ggen_advance_name_unify_candidate_20260909.json"
MANIFEST = OUT_DIR / "manifest.json"
CAVE_START = 0x012B2000
CAVE_END = 0x012BF000
MAP_BANK = (0x00F00000, 0x00FC0000)
NOTES = (
    "무→무우 라 프라가, 노이에른→노이엔 비터, 애너벨→아나벨 가토, "
    "동방불패 왕자의 풍격→왕자의 바람"
)
PROTECTED_UNCHANGED = {
    "GGA-MAPSCRIPT-00FA2730": "무우웃!!",
}
REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("무 라 프라가", "무우 라 프라가"),
    ("노이에른 비터", "노이엔 비터"),
    ("애너벨 가토", "아나벨 가토"),
    ("왕자의 풍격이다", "왕자의 바람이다"),
    ("무의 아버지", "무우의 아버지"),
    ("무 씨", "무우 씨"),
    ("무 못지않게", "무우 못지않게"),
)
OLD_TOKENS = (
    "무 라 프라가",
    "노이에른",
    "애너벨",
    "왕자의 풍격",
    "무의 아버지",
    "무 씨",
    "무 못지않게",
)
ALLOWED_SCOPES = {
    "scenario_map_script",
    "scenario_main",
    "battle_event_dialogue",
    "non_scenario_ui",
    "production",
}
DIALOGUE_SCOPES = {
    "scenario_map_script",
    "scenario_main",
    "battle_event_dialogue",
}


def rewrite_text(text: str) -> str:
    if not text:
        return text
    out = text
    for old, new in REPLACEMENTS:
        out = out.replace(old, new)
    if out == "무……":
        out = "무우……"
    return out


def needs_rewrite(text: str) -> bool:
    if text == "무……":
        return True
    return any(token in text for token in OLD_TOKENS)


def encode_overlay(
    text: str,
    recovered: dict[str, int],
    verified: dict[str, int],
    live_tokens: dict[str, bytes],
    *,
    identified: dict[str, int] | None = None,
) -> bytes:
    if identified is not None:
        encoded, missing = encode_map_korean_line(text, recovered, identified)
    else:
        encoded, missing = unified.encode_korean_text(
            text,
            recovered,
            verified_charmap=verified,
            strict_punctuation=True,
        )
    gate(encoded is not None and not missing, f"encode failed {text!r}: {missing}")
    gate(encoded.endswith(b"\x00"), f"encoded line missing NUL {text!r}")
    out = bytearray()
    fallback = read_tokens(encoded)
    gate(len(fallback) == len(text), f"token/text drift {text!r}")
    for char, token in zip(text, fallback):
        out.extend(live_tokens.get(char, token))
    out.append(0)
    return bytes(out)


def patch_map_row_live(
    row: dict[str, Any],
    old_segments: list[str],
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
        if not old_text:
            encoded_new = old_payload
        elif old_text == new_text:
            encoded_new = old_payload
        else:
            live_tokens = live_char_tokens(old_text, old_payload)
            gate(
                "\n" not in new_text and len(new_text) <= MAX_DIALOGUE_CELLS,
                f"map dialogue width {row['record_id']}#{index} len={len(new_text)} text={new_text!r}",
            )
            encoded_new = encode_overlay(new_text, recovered12, verified12, live_tokens, identified=identified)
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


def rebuild_scenario_live(
    row: dict[str, Any],
    old_segments: list[str],
    new_segments: list[str],
    live: bytes,
    recovered12: dict[str, int],
    verified12: dict[str, int],
) -> tuple[bytes, int]:
    segments = list(row.get("segments") or [])
    controls = list(row.get("control_signature") or [])
    gate(len(segments) == len(controls) == len(old_segments) == len(new_segments), f"scenario framing {row['record_id']}")
    out = bytearray()
    index = 0
    for segment, control, old_text, new_text in zip(segments, controls, old_segments, new_segments):
        original = raw_hex_bytes(str(segment.get("raw_hex") or ""))
        code = int(control["code"], 16)
        extra = 1 + (1 if code in (0x05, 0x06) else 0)
        if old_text:
            nul = live.find(0, index)
            gate(nul >= 0, f"live scenario missing NUL {row['record_id']}")
            old_enc = bytes(live[index : nul + 1])
            live_tokens = live_char_tokens(old_text, old_enc)
            out.extend(encode_overlay(new_text, recovered12, verified12, live_tokens))
            index = nul + 1
        else:
            gate(live[index : index + len(original)] == original, f"live scenario framing drift {row['record_id']}")
            out.extend(original)
            index += len(original)
        ctrl = bytes(live[index : index + extra])
        gate(len(ctrl) == extra, f"live scenario control truncated {row['record_id']}")
        out.append(code)
        if extra == 2:
            argument = int(control["argument"])
            out.append(argument)
            gate(ctrl[0] == code and ctrl[1] == argument, f"live control drift {row['record_id']}")
        else:
            gate(ctrl[0] == code, f"live control code drift {row['record_id']}")
        index += extra
    return bytes(out), index


def apply_row_text(row: dict[str, Any]) -> tuple[str, list[str]]:
    old_segments = [str(item) for item in (row.get("translation_segments") or [])]
    before = str(row.get("translation_ko") or "")
    if old_segments:
        new_segments = [rewrite_text(item) if item else item for item in old_segments]
        after = "\n".join(visible_segments(new_segments))
        return after, new_segments
    after = rewrite_text(before)
    return after, []


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    original = ORIGINAL_ROM.read_bytes()
    current = MAIN_TIP_ROM.read_bytes()
    main_manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(len(current) == 32 * 1024 * 1024, "main TIP size drift")
    gate(sha256(current) == main_manifest.get("sha256"), "main TIP/manifest hash drift")
    gate(all(value == 0 for value in current[CAVE_START:CAVE_END]), "name-unify cave is not zero-filled")
    gate(MAIN_SAV.exists(), "current main SAV missing")

    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    by_id = {str(row["record_id"]): row for row in merged["records"]}
    for record_id, expected in PROTECTED_UNCHANGED.items():
        gate(str(by_id[record_id].get("translation_ko") or "") == expected, f"{record_id} shout drift")

    targets = [
        row
        for row in merged["records"]
        if needs_rewrite(str(row.get("translation_ko") or ""))
        or any(needs_rewrite(str(item)) for item in (row.get("translation_segments") or []))
    ]
    gate(targets, "no name-unify rows found")
    leftover_scopes = {str(row.get("source_scope")) for row in targets} - ALLOWED_SCOPES
    gate(not leftover_scopes, f"unexpected scopes {sorted(leftover_scopes)}")

    planned: list[tuple[dict[str, Any], str, list[str], list[str]]] = []
    hangul: set[str] = set()
    for row in targets:
        before = str(row.get("translation_ko") or "")
        old_segments = [str(item) for item in (row.get("translation_segments") or [])]
        after, new_segments = apply_row_text(row)
        gate(len(new_segments) == len(old_segments), f"segment count drift {row['record_id']}")
        gate(after != before or new_segments != old_segments, f"no-op {row['record_id']}")
        if str(row.get("source_scope")) in DIALOGUE_SCOPES:
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
    live8, live12 = unified.collect_live_slots(original, merged["records"])
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
    counts: Counter[str] = Counter()

    for row, before, old_segments, new_segments in planned:
        after = "\n".join(visible_segments(new_segments)) if new_segments else rewrite_text(before)
        row["translation_ko"] = after
        if old_segments:
            row["translation_segments"] = new_segments
        row["translation_status"] = "translated"
        row["translation_source"] = "user_verified"
        row["review_status"] = "user_verified"
        row["review_count"] = int(row.get("review_count") or 0) + 1
        row["reviewed_at"] = "2026-09-09"
        row["translator_notes"] = NOTES
        row["qa_status"] = "static_consumer_verified"
        row["overlay_batch_id"] = BATCH_ID
        update_payload_hash(row)

        scope = str(row.get("source_scope"))
        if scope == "scenario_map_script":
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
                    "record_id": row["record_id"],
                    "source_scope": scope,
                    "before": before,
                    "after": after,
                    "segments": written,
                }
            )
            continue

        if scope in {"scenario_main", "battle_event_dialogue"}:
            owners = tuple(
                int(owner.removeprefix("OWNER-U32-"), 16)
                for owner in row.get("owner_ids", [])
                if str(owner).startswith("OWNER-U32-")
            )
            gate(owners, f"scenario owner missing {row['record_id']}")
            pointer = struct.unpack_from("<I", current, owners[0])[0]
            live_from = bytes(current[pointer - ROM_BASE :])
            identity_payload, consumed = rebuild_scenario_live(
                row, old_segments, old_segments, live_from, recovered12, verified12
            )
            old_payload = live_from[:consumed]
            gate(identity_payload == old_payload, f"live identity rebuild drift {row['record_id']}")
            new_payload, _new_consumed = rebuild_scenario_live(
                row, old_segments, new_segments, live_from, recovered12, verified12
            )
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
            counts["scenario" if scope == "scenario_main" else "battle"] += 1
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

        gate(scope in {"non_scenario_ui", "production"}, f"unexpected scope {row['record_id']}")
        owners = tuple(
            int(owner.removeprefix("OWNER-U32-"), 16)
            for owner in row.get("owner_ids", [])
            if str(owner).startswith("OWNER-U32-")
        )
        gate(owners, f"UI has no U32 owners {row['record_id']}")
        pointer = struct.unpack_from("<I", current, owners[0])[0]
        live = payload_at(current, pointer)
        encoded12_old, miss12_old = unified.encode_korean_text(
            before, recovered12, verified_charmap=verified12, strict_punctuation=True
        )
        encoded8_old, miss8_old = unified.encode_korean_text(
            before, recovered8, verified_charmap=verified8, strict_punctuation=True
        )
        if encoded12_old == live and not miss12_old:
            font_used = "12x12"
            new_payload = encode_overlay(after, recovered12, verified12, live_char_tokens(before, live))
            old_payload = encoded12_old
        elif encoded8_old == live and not miss8_old:
            font_used = "8x16"
            new_payload = encode_overlay(after, recovered8, verified8, live_char_tokens(before, live))
            old_payload = encoded8_old
        else:
            live_tokens = live_char_tokens(before, live)
            try12 = encode_overlay(before, recovered12, verified12, live_tokens)
            try8 = encode_overlay(before, recovered8, verified8, live_tokens)
            if try12 == live:
                font_used = "12x12"
                old_payload = live
                new_payload = encode_overlay(after, recovered12, verified12, live_tokens)
            elif try8 == live:
                font_used = "8x16"
                old_payload = live
                new_payload = encode_overlay(after, recovered8, verified8, live_tokens)
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
    for record_id, expected in PROTECTED_UNCHANGED.items():
        gate(str(by_id[record_id].get("translation_ko") or "") == expected, f"{record_id} was rewritten")
    changed = [index for index, (before, after) in enumerate(zip(current, candidate)) if before != after]
    gate(set(changed) <= allowed, f"unexpected ROM byte change x{len(set(changed) - allowed)}")
    gate(bytes(candidate[MAP_BANK[0] : MAP_BANK[1]]) == current[MAP_BANK[0] : MAP_BANK[1]], "original map-script bank changed")
    gate(sha256(MAIN_TIP_ROM.read_bytes()) == sha256(current), "main TIP mutated during patch")
    gate(cave_cursor <= CAVE_END, "name-unify cave overflow")

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
    identity[IDENTITY_KEY] = new_identity
    identity["translation_overlay_identity_sha256"] = new_identity
    status_counts = dict(sorted(Counter(str(row.get("translation_status") or "") for row in merged["records"]).items()))
    summary = merged.setdefault("summary", {})
    summary["merged_translation_status_counts"] = status_counts
    summary["translation_overlay_identity_sha256"] = new_identity
    merged[BATCH_KEY] = {
        "batch_id": BATCH_ID,
        "changed_records": [row["record_id"] for row, _before, _old, _new in planned],
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
            "no_old_name_leftover": True,
            "elongated_muu_shout_untouched": True,
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
