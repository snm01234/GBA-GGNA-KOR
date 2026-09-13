"""Follow-up term fixes and the Gihren 껍/꺄 painted-slot bug.

Japanese sources:
- バラエーナ leftover 발레나 → 발라에나 (SEED Archangel Balaena)
- 自軍 leftover 자군 → 아군
- 見えたぞ！術のひとしずく！ 술=術 calque → 물의 한 방울 (Domon ID)
- 本命を叩き込め！！ misread as 本名 → 결정타를 꽂아라 (Bright ID)
- map それはすでに形骸である！ sheet already 껍데기, live 12x12 used 꺄 slot 0x0146
"""
from __future__ import annotations

import json
import shutil
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import build_ggen_advance_ko_poc as fontops  # noqa: E402
import build_ggen_advance_unified_rom_poc as unified  # noqa: E402
import patch_ggen_advance_apsaras_zentetsu_20260908 as aps  # noqa: E402
import patch_ggen_profile_followup2_20260912 as f2  # noqa: E402
from ggen_advance_project_paths import (  # noqa: E402
    MAIN_TIP_MANIFEST,
    MAIN_TIP_ROM,
    ORIGINAL_ROM,
    TRANSLATION_MERGED_JSON,
    advance_relative,
)
from ggen_advance_text_codec import (  # noqa: E402
    DICT_8X16_BASE,
    DICT_8X16_END,
    DICT_12X12_BASE,
    DICT_12X12_END,
    ROM_BASE,
    load_dictionary,
)
from merge_ggen_advance_translation_overlays import digest  # noqa: E402
from patch_ggen_advance_apsaras_zentetsu_20260908 import hangul_chars, visible_segments  # noqa: E402
from patch_ggen_advance_dialogue_idcmd_fit_20260909 import (  # noqa: E402
    live_pair_blob,
    owner_u16,
    split_pair,
    write_padded,
)
from patch_ggen_advance_dialogue_idcmd_fit_20260909 import (  # noqa: E402
    live_char_tokens as desc_live_char_tokens,
)
from patch_ggen_advance_idcmd_list_fit_20260909 import DESC_CAP, EFFECT_CAP, NAME_CAP  # noqa: E402
from patch_ggen_advance_intermission_text_consumers_20260904 import gate, payload_at, sha256  # noqa: E402
from patch_ggen_advance_kimi_jane_to_neo_20260904 import (  # noqa: E402
    owner_offsets,
    update_payload_hash,
    update_translation_manifest,
)
from patch_ggen_advance_map_script_inline_poc import (  # noqa: E402
    MAX_DIALOGUE_CELLS,
    load_identified_12x12,
    raw_hex_bytes,
)
from patch_ggen_advance_name_unify_20260909 import (  # noqa: E402
    encode_overlay as _encode_overlay,
    rebuild_scenario_live,
)
import patch_ggen_advance_name_unify_20260909 as nu_mod  # noqa: E402


def encode_overlay(
    text: str,
    recovered: dict[str, int],
    verified: dict[str, int],
    live_tokens: dict[str, bytes],
    *,
    identified: dict[str, int] | None = None,
) -> bytes:
    if identified is not None:
        return _encode_overlay(text, recovered, verified, live_tokens, identified=identified)
    out = bytearray()
    for char in text:
        if char in live_tokens:
            out.extend(live_tokens[char])
            continue
        piece, missing = unified.encode_korean_text(
            char, recovered, verified_charmap=verified, strict_punctuation=True
        )
        gate(
            piece is not None and not missing and piece.endswith(b"\x00"),
            f"encode char {ascii(char)} missing={missing!r}",
        )
        out.extend(piece[:-1])
    out.append(0)
    return bytes(out)


nu_mod.encode_overlay = encode_overlay


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
    force = str(row.get("record_id") or "") in FORCE_MAP_REENCODE
    for index, (segment, old_text, new_text) in enumerate(zip(segments, old_segments, new_segments)):
        original_bytes = raw_hex_bytes(str(segment.get("raw_hex") or ""))
        gate(original_bytes.endswith(b"\x00"), f"map segment missing NUL {row['record_id']}")
        orig_addr = ROM_BASE + cursor
        orig_end = orig_addr + len(original_bytes) - 1
        lookups = aps.find_lookups(current, orig_addr, orig_end)
        neu = lookups[0][1]
        old_payload = payload_at(current, neu)
        if not old_text:
            encoded_new = old_payload
        elif old_text == new_text and not force:
            encoded_new = old_payload
        else:
            live_tokens = desc_live_char_tokens(old_text, old_payload)
            for char in DROP_LIVE_CHARS:
                live_tokens.pop(char, None)
            gate(
                "\n" not in new_text and len(new_text) <= MAX_DIALOGUE_CELLS,
                f"map dialogue width {row['record_id']}#{index} len={len(new_text)} text={new_text!r}",
            )
            encoded_new = encode_overlay(new_text, recovered12, verified12, live_tokens, identified=identified)
        new_addr, cave_cursor = aps.write_payload(
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
            alias_hits = aps.find_lookups(current, opcode_addr, first_old_end)
            for alias_pos, alias_neu, _alias_end in alias_hits:
                if alias_neu != first_new_addr:
                    struct.pack_into("<I", candidate, alias_pos + 4, first_new_addr)
                    allowed.update(range(alias_pos + 4, alias_pos + 8))
    return cave_cursor, written


BATCH_ID = "followup-terms-balaena-ally-domon-bright-kkeop-20260912"
IDENTITY_KEY = "followup_terms_20260912_sha256"
BATCH_KEY = "followup_terms_20260912"
OUT = ROOT / "outputs" / "20260912_followup_terms"
WORK = OUT / "ggen_followup_terms_20260912.gba"
SNAPSHOT = ROOT / "analysis" / "ggen_advance_translation_merged_20260912_followup_terms.json"
BARKS = ROOT / "integrated" / "translation" / "ggen_advance_id_command_battle_barks.json"
MAIN_SAV = ROOT / "SD Gundam GGeneration Advance (Korean).sav"
CAVE_START = 0x011353C0
CAVE_END = 0x01230000
MAP_BANK = (0x00F00000, 0x00FC0000)
NOTES = (
    "후속 용어: バラエーナ 발레나→발라에나, 自軍 자군→아군, "
    "도몬 術→물의 한 방울, 브라이트 本命→결정타를 꽂아라, "
    "기렌 연설 껍데기 12x12 슬롯 재인코드"
)
REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("발레나", "발라에나"),
    ("자군", "아군"),
    ("술의 한 방울", "물의 한 방울"),
    ("본명을 때려 넣어", "결정타를 꽂아라"),
)
FORCE_MAP_REENCODE = {"GGA-MAPSCRIPT-00FABCEA"}
DROP_LIVE_CHARS = {"껍"}
GIHREN_SHELL_ID = "GGA-MAPSCRIPT-00FABCEA"
DOMON_ID = "GGA-TEXT-0017C47E"
BRIGHT_ID = "GGA-TEXT-0017C7F2"
BALAENA_ID = "GGA-TEXT-0017A701"
BALAENA_DYN_ID = "GGA-DYNAMIC-001F1DAE"
ALLY_EFFECT_ID = "GGA-TEXT-0017BBA5"
OLD_TOKENS = tuple(old for old, _new in REPLACEMENTS)
ALLOWED_SCOPES = {
    "scenario_map_script",
    "scenario_main",
    "scenario_dynamic",
    "battle_event_dialogue",
    "non_scenario_ui",
    "production",
}
DIALOGUE_SCOPES = {"scenario_map_script", "scenario_main", "battle_event_dialogue"}
U32_SCOPES = {"non_scenario_ui", "production", "scenario_dynamic"}


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def rewrite_text(text: str) -> str:
    out = text
    for old, new in REPLACEMENTS:
        out = out.replace(old, new)
    return out


def needs_rewrite(text: str) -> bool:
    return any(token in text for token in OLD_TOKENS)


def leftover_hits(text: str) -> list[str]:
    return [token for token in OLD_TOKENS if token in text]


def apply_row_text(row: dict[str, Any]) -> tuple[str, list[str]]:
    old_segments = [str(item) for item in (row.get("translation_segments") or [])]
    before = str(row.get("translation_ko") or "")
    if old_segments:
        new_segments = [rewrite_text(item) if item else item for item in old_segments]
        after = "\n".join(visible_segments(new_segments))
        return after, new_segments
    return rewrite_text(before), []


def patch_merged_row(row: dict[str, Any], ko: str, segments: list[str] | None) -> None:
    row["translation_ko"] = ko
    if segments:
        row["translation_segments"] = segments
    elif "translation_segments" in row and not segments:
        pass
    row["translation_status"] = "translated"
    row["translation_source"] = "user_verified"
    row["review_status"] = "user_verified"
    row["review_count"] = int(row.get("review_count") or 0) + 1
    row["reviewed_at"] = "2026-09-12"
    row["translator_notes"] = NOTES
    row["qa_status"] = "static_consumer_verified"
    row["overlay_batch_id"] = BATCH_ID
    row["pointer_recalc_required"] = True
    update_payload_hash(row)


def splice_same_length(
    before: str,
    after: str,
    live: bytes,
    recovered: dict[str, int],
    verified: dict[str, int],
) -> bytes | None:
    from patch_ggen_advance_dialogue_idcmd_fit_20260909 import read_tokens

    if len(before) != len(after):
        return None
    tokens = read_tokens(live)
    if len(tokens) != len(before):
        return None
    out = bytearray()
    for old_ch, new_ch, token in zip(before, after, tokens):
        if old_ch == new_ch:
            out.extend(token)
            continue
        piece = encode_overlay(new_ch, recovered, verified, {})
        gate(piece.endswith(b"\x00") and piece[:-1], f"splice encode empty {new_ch!r}")
        out.extend(piece[:-1])
    out.append(0)
    return bytes(out)


def live_char_tokens_tolerant(text: str, blob: bytes) -> dict[str, bytes]:
    from patch_ggen_advance_dialogue_idcmd_fit_20260909 import read_tokens

    tokens = read_tokens(blob)
    if len(tokens) != len(text):
        return {}
    mapping: dict[str, bytes] = {}
    conflicts: set[str] = set()
    for char, token in zip(text, tokens):
        prior = mapping.get(char)
        if prior is not None and prior != token:
            conflicts.add(char)
            continue
        mapping[char] = token
    for char in conflicts:
        mapping.pop(char, None)
    return mapping


def encode_u32_payload(
    before: str,
    after: str,
    live: bytes,
    recovered12: dict[str, int],
    recovered8: dict[str, int],
    verified12: dict[str, int],
    verified8: dict[str, int],
    *,
    prefer: str,
) -> tuple[str, bytes, bytes]:
    order = [prefer, "8x16" if prefer != "8x16" else "12x12"]
    rec_by = {"12x12": (recovered12, verified12), "8x16": (recovered8, verified8)}
    spliced: list[tuple[str, bytes, bytes]] = []
    for font in order:
        recovered, verified = rec_by[font]
        payload = splice_same_length(before, after, live, recovered, verified)
        if payload is not None:
            spliced.append((font, live, payload))
    if spliced:
        return spliced[0]

    encoded12_old, miss12_old = unified.encode_korean_text(
        before, recovered12, verified_charmap=verified12, strict_punctuation=True
    )
    encoded8_old, miss8_old = unified.encode_korean_text(
        before, recovered8, verified_charmap=verified8, strict_punctuation=True
    )
    live_tokens = live_char_tokens_tolerant(before, live)
    try12 = encode_overlay(before, recovered12, verified12, live_tokens)
    try8 = encode_overlay(before, recovered8, verified8, live_tokens)
    matches: list[tuple[str, bytes, bytes]] = []
    if (encoded12_old == live and not miss12_old) or try12 == live:
        matches.append(("12x12", live if try12 == live else encoded12_old, encode_overlay(after, recovered12, verified12, live_tokens)))
    if (encoded8_old == live and not miss8_old) or try8 == live:
        matches.append(("8x16", live if try8 == live else encoded8_old, encode_overlay(after, recovered8, verified8, live_tokens)))
    if not matches:
        raise SystemExit(
            f"gate failed: U32 live encode mismatch live={live.hex()} "
            f"12={None if encoded12_old is None else encoded12_old.hex()} "
            f"8={None if encoded8_old is None else encoded8_old.hex()} miss12={miss12_old} miss8={miss8_old}"
        )
    preferred = [item for item in matches if item[0] == prefer]
    return (preferred or matches)[0]


def parse_bark_container(rom: bytes, gba_addr: int) -> tuple[list[bytes], list[int], bytes]:
    cursor = gba_addr - ROM_BASE
    streams: list[bytes] = []
    markers: list[int] = []
    gate(0 <= cursor < len(rom), f"bark pointer out of range 0x{gba_addr:08X}")
    while True:
        nul = rom.find(0, cursor)
        gate(nul >= 0, f"bark stream missing NUL at 0x{cursor:08X}")
        streams.append(bytes(rom[cursor : nul + 1]))
        marker = rom[nul + 1]
        markers.append(marker)
        cursor = nul + 2
        if marker in (0x01, 0x02):
            break
        gate(cursor < len(rom), "bark container ran off ROM")
    return streams, markers, bytes(rom[gba_addr - ROM_BASE : cursor])


def find_u32_hits(rom: bytes, address: int) -> list[int]:
    needle = struct.pack("<I", address)
    hits: list[int] = []
    start = 0
    while True:
        pos = rom.find(needle, start)
        if pos < 0:
            break
        if pos % 4 == 0:
            hits.append(pos)
        start = pos + 1
    return hits


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    aps.CAVE_END = CAVE_END
    OUT.mkdir(parents=True, exist_ok=True)
    parent = MAIN_TIP_ROM.read_bytes()
    japan = ORIGINAL_ROM.read_bytes()
    manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(parent) == manifest["sha256"], "main TIP sha mismatch")
    gate(all(b == 0 for b in parent[CAVE_START:CAVE_END]), "followup-term cave is not empty")
    gate(MAIN_SAV.exists(), "current main SAV missing")

    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    barks = json.loads(BARKS.read_text(encoding="utf-8"))
    targets = [
        row
        for row in merged["records"]
        if needs_rewrite(str(row.get("translation_ko") or ""))
        or any(needs_rewrite(str(item)) for item in (row.get("translation_segments") or []))
        or str(row.get("record_id") or "") in FORCE_MAP_REENCODE
    ]
    gate(targets, "no followup-term rows found")
    leftover_scopes = {str(row.get("source_scope")) for row in targets} - ALLOWED_SCOPES
    gate(not leftover_scopes, f"unexpected scopes {sorted(leftover_scopes)}")

    planned: list[tuple[dict[str, Any], str, list[str], str, list[str]]] = []
    hangul8: set[str] = set()
    hangul12: set[str] = set()
    for row in targets:
        before = str(row.get("translation_ko") or "")
        old_segments = [str(item) for item in (row.get("translation_segments") or [])]
        after, new_segments = apply_row_text(row)
        gate(len(new_segments) == len(old_segments), f"segment count drift {row['record_id']}")
        force = str(row.get("record_id") or "") in FORCE_MAP_REENCODE
        gate(after != before or new_segments != old_segments or force, f"no-op {row['record_id']}")
        if str(row.get("source_scope")) in DIALOGUE_SCOPES:
            for text in visible_segments(new_segments) or after.split("\n"):
                gate(
                    "\n" not in text and len(text) <= MAX_DIALOGUE_CELLS,
                    f"dialogue width {row['record_id']} len={len(text)} text={text!r}",
                )
        if row.get("semantic_category") == "id_command_description":
            gate(len(after.replace("\n", "")) <= DESC_CAP, f"desc cap {row['record_id']} {after!r}")
        if row.get("semantic_category") == "id_command_effect_summary":
            gate(len(after.replace("\n", "")) <= EFFECT_CAP, f"effect cap {row['record_id']} {after!r}")
        if row.get("semantic_category") == "id_command_name":
            gate(len(after.replace("\n", "")) <= NAME_CAP, f"name cap {row['record_id']} {after!r}")
        hangul12.update(hangul_chars(before))
        hangul12.update(hangul_chars(after))
        hangul8.update(hangul_chars(before))
        hangul8.update(hangul_chars(after))
        for text in old_segments + new_segments:
            hangul12.update(hangul_chars(text))
            hangul8.update(hangul_chars(text))
        planned.append((row, before, old_segments, after, new_segments))

    bark_targets = [row for row in barks["records"] if needs_rewrite(str(row.get("translation_ko") or ""))]
    for row in bark_targets:
        hangul12.update(hangul_chars(str(row.get("translation_ko") or "")))
        hangul12.update(hangul_chars(rewrite_text(str(row.get("translation_ko") or ""))))

    extra_hangul = hangul_chars("발라에나물의한방울결정타꽂껍데기아군")
    hangul8.update(extra_hangul)
    hangul12.update(extra_hangul)
    live8, live12 = unified.collect_live_slots(japan, merged["records"])
    verified8 = unified.load_verified_charmap(unified.CHARMAP_8X16_PATH)
    verified12 = unified.load_verified_charmap(unified.CHARMAP_12X12_PATH)
    identified = load_identified_12x12()
    candidate = bytearray(parent)
    allowed: set[int] = set()
    painted: list[dict[str, str]] = []
    occupied8: set[int] = set()
    occupied12: set[int] = set()
    recovered8 = f2.recover_hangul(
        candidate, japan, hangul8, mode=8, live=live8, occupied=occupied8, allowed=allowed, painted=painted
    )
    recovered12 = f2.recover_hangul(
        candidate, japan, hangul12, mode=12, live=live12, occupied=occupied12, allowed=allowed, painted=painted
    )
    for char in extra_hangul:
        gate(char in recovered8, f"missing 8x16 {ascii(char)}")
        gate(char in recovered12, f"missing 12x12 {ascii(char)}")
    cave_cursor = CAVE_START
    evidence: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()

    relative_jobs: dict[str, list[tuple[dict[str, Any], str, str]]] = defaultdict(list)
    ownerless: list[tuple[dict[str, Any], str, str]] = []

    for row, before, old_segments, after, new_segments in planned:
        patch_merged_row(row, after, new_segments or None)
        scope = str(row.get("source_scope"))
        schema = str(row.get("relocation_schema") or "")

        if scope == "scenario_map_script":
            cave_cursor, written = patch_map_row_live(
                row,
                old_segments,
                new_segments,
                parent,
                candidate,
                recovered12,
                identified,
                verified12,
                allowed,
                cave_cursor,
            )
            counts["map_script"] += 1
            evidence.append({"record_id": row["record_id"], "path": "map_script", "before": before, "after": after, "segments": written})
            continue

        if scope in {"scenario_main", "battle_event_dialogue"} and old_segments:
            owners = owner_offsets(row)
            gate(owners, f"scenario owner missing {row['record_id']}")
            pointer = u32(parent, owners[0])
            live_from = bytes(parent[pointer - ROM_BASE :])
            identity_payload, consumed = rebuild_scenario_live(
                row, old_segments, old_segments, live_from, recovered12, verified12
            )
            old_payload = live_from[:consumed]
            gate(identity_payload == old_payload, f"live identity rebuild drift {row['record_id']}")
            new_payload, _new_consumed = rebuild_scenario_live(
                row, old_segments, new_segments, live_from, recovered12, verified12
            )
            cave_cursor, old_addresses, new_addr = aps.patch_owned_payload(
                row, old_payload, new_payload, parent, candidate, allowed, cave_cursor, require_nul=False
            )
            counts["scenario"] += 1
            evidence.append(
                {
                    "record_id": row["record_id"],
                    "path": "scenario",
                    "before": before,
                    "after": after,
                    "old_active_addresses": old_addresses,
                    "new_address": new_addr,
                }
            )
            continue

        if schema == "relative_pair_block":
            relative_jobs[str(row.get("container_id") or "")].append((row, before, after))
            continue

        if owner_offsets(row):
            owners = owner_offsets(row)
            pointer = u32(parent, owners[0])
            live = payload_at(parent, pointer)
            prefer = (
                "12x12"
                if scope == "scenario_dynamic" or str(row.get("consumer_font_mode") or "") == "12x12"
                else "8x16"
            )
            font_used, old_payload, new_payload = encode_u32_payload(
                before, after, live, recovered12, recovered8, verified12, verified8, prefer=prefer
            )
            cave_cursor, old_addresses, new_addr = aps.patch_owned_payload(
                row, old_payload, new_payload, parent, candidate, allowed, cave_cursor, require_nul=True
            )
            counts["u32"] += 1
            evidence.append(
                {
                    "record_id": row["record_id"],
                    "path": f"u32_{font_used}",
                    "before": before,
                    "after": after,
                    "old_active_addresses": old_addresses,
                    "new_address": new_addr,
                }
            )
            continue

        ownerless.append((row, before, after))

    by_id = {str(row["record_id"]): row for row in merged["records"]}
    for container_id, jobs in relative_jobs.items():
        gate(container_id, "relative container id missing")
        members = sorted(
            [row for row in merged["records"] if str(row.get("container_id") or "") == container_id],
            key=lambda item: int(item.get("line_index") or 0),
        )
        gate(len(members) == 2, f"relative pair member count {container_id}")
        owners = {owner_u16(item) for item in members}
        gate(len(owners) == 1 and None not in owners, f"relative pair owner drift {container_id}")
        owner = next(iter(owners))
        start, old_blob = live_pair_blob(bytes(candidate), owner)
        old_line1, old_line2 = split_pair(old_blob)
        after_by_id = {str(row["record_id"]): after for row, _before, after in jobs}
        live_tokens: dict[str, bytes] = {}
        for member, old_line in zip(members, (old_line1, old_line2)):
            before = str(member.get("translation_ko") or "")
            # translation_ko already rewritten for jobs; recover original from planned
            original = next((b for r, b, _a in jobs if r is member), before)
            if jobs and str(member["record_id"]) in after_by_id:
                original = next(b for r, b, _a in jobs if str(r["record_id"]) == str(member["record_id"]))
            text_for_tokens = original if original else before
            if text_for_tokens:
                for char, token in desc_live_char_tokens(text_for_tokens, old_line).items():
                    prior = live_tokens.get(char)
                    gate(prior is None or prior == token, f"live token conflict {char!r} in {container_id}")
                    live_tokens[char] = token
        new_lines: list[bytes] = []
        texts: list[str] = []
        for member, old_line in zip(members, (old_line1, old_line2)):
            rid = str(member["record_id"])
            original = next((b for r, b, _a in jobs if str(r["record_id"]) == rid), str(member.get("translation_ko") or ""))
            after = after_by_id.get(rid, str(member.get("translation_ko") or ""))
            if after == original:
                encoded_new = old_line
            else:
                encoded_new = encode_overlay(after, recovered12, verified12, live_tokens)
            new_lines.append(encoded_new)
            texts.append(after)
        packed = new_lines[0] + new_lines[1]
        write_padded(candidate, start, packed, old_blob, allowed)
        counts["relative_pair"] += len(jobs)
        evidence.append(
            {
                "container_id": container_id,
                "path": "relative_pair",
                "after": texts,
                "old_size": len(old_blob),
                "new_size": len(packed),
            }
        )

    for row, before, after in ownerless:
        old_payload = encode_overlay(before, recovered12, verified12, {})
        hits = []
        start = 0
        while True:
            pos = bytes(candidate).find(old_payload, start)
            if pos < 0:
                break
            hits.append(pos)
            start = pos + 1
        gate(hits, f"ownerless payload missing {row['record_id']} {before!r}")
        new_payload = encode_overlay(after, recovered12, verified12, {})
        for pos in hits:
            old_addr = ROM_BASE + pos
            live = bytes(candidate[pos : pos + len(old_payload)])
            gate(live == old_payload, f"ownerless drift {row['record_id']}")
            if len(new_payload) <= len(old_payload):
                written_addr, cave_cursor = aps.write_payload(
                    candidate, old_addr, new_payload, len(old_payload), allowed, cave_cursor, require_nul=True
                )
                gate(written_addr == old_addr, f"ownerless unexpectedly relocated {row['record_id']}")
            else:
                ptrs = find_u32_hits(bytes(candidate), old_addr)
                gate(ptrs, f"ownerless grew and has no pointer {row['record_id']}")
                written_addr, cave_cursor = aps.write_payload(
                    candidate, old_addr, new_payload, len(old_payload), allowed, cave_cursor, require_nul=True
                )
                if written_addr != old_addr:
                    for ptr in ptrs:
                        struct.pack_into("<I", candidate, ptr, written_addr)
                        allowed.update(range(ptr, ptr + 4))
        counts["ownerless"] += 1
        evidence.append({"record_id": row["record_id"], "path": "ownerless", "before": before, "after": after, "hits": len(hits)})

    bark_by_table: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in barks["records"]:
        table = str(row.get("table_entry_file_offset") or "")
        if any(str(item.get("table_entry_file_offset") or "") == table and needs_rewrite(str(item.get("translation_ko") or "")) for item in bark_targets):
            bark_by_table[table].append(row)
    for table, rows in bark_by_table.items():
        if not any(needs_rewrite(str(row.get("translation_ko") or "")) for row in rows):
            continue
        table_off = int(table, 16)
        live_ptr = u32(parent, table_off)
        streams, markers, old_container = parse_bark_container(parent, live_ptr)
        overlay_rows = [row for row in barks["records"] if str(row.get("table_entry_file_offset") or "") == table]
        by_index = {int(row.get("stream_index") or 0): row for row in overlay_rows}
        gate(by_index, f"bark overlay missing {table}")
        gate(max(by_index) < len(streams), f"bark stream index {table} {max(by_index)}>={len(streams)}")
        rebuilt = bytearray()
        changed = False
        rewritten = 0
        for index, (stream, marker) in enumerate(zip(streams, markers)):
            row = by_index.get(index)
            if row is not None:
                before = str(row.get("translation_ko") or "")
                after = rewrite_text(before)
                if before and after != before:
                    live_tokens = desc_live_char_tokens(before, stream)
                    encoded_old = encode_overlay(before, recovered12, verified12, live_tokens)
                    gate(encoded_old == stream, f"bark live mismatch {row['record_id']}")
                    rebuilt.extend(encode_overlay(after, recovered12, verified12, live_tokens))
                    row["translation_ko"] = after
                    row["translation_source"] = "user_verified"
                    row["review_status"] = "user_verified"
                    row["overlay_batch_id"] = BATCH_ID
                    changed = True
                    rewritten += 1
                else:
                    rebuilt.extend(stream)
                if needs_rewrite(str(row.get("parallel_command_A_translation_ko") or "")):
                    row["parallel_command_A_translation_ko"] = rewrite_text(str(row["parallel_command_A_translation_ko"]))
            else:
                rebuilt.extend(stream)
            rebuilt.append(marker)
        gate(changed, f"bark table {table} scheduled but unchanged")
        new_container = bytes(rebuilt)
        written_addr, cave_cursor = aps.write_payload(
            candidate, live_ptr, new_container, len(old_container), allowed, cave_cursor, require_nul=False
        )
        if written_addr != live_ptr:
            struct.pack_into("<I", candidate, table_off, written_addr)
            allowed.update(range(table_off, table_off + 4))
        counts["id_bark"] += rewritten
        evidence.append(
            {
                "path": "id_bark",
                "table": table,
                "old_ptr": f"0x{live_ptr:08X}",
                "new_ptr": f"0x{written_addr:08X}",
                "old_size": len(old_container),
                "new_size": len(new_container),
            }
        )

    leftover = [
        row["record_id"]
        for row in merged["records"]
        if leftover_hits(str(row.get("translation_ko") or ""))
        or any(leftover_hits(str(item)) for item in (row.get("translation_segments") or []))
    ]
    gate(not leftover, f"rewrite leftover: {leftover[:8]}")
    bark_left = [row["record_id"] for row in barks["records"] if leftover_hits(str(row.get("translation_ko") or ""))]
    gate(not bark_left, f"bark leftover: {bark_left[:8]}")
    changed = [index for index, (before, after) in enumerate(zip(parent, candidate)) if before != after]
    gate(set(changed) <= allowed, f"unexpected ROM byte change x{len(set(changed) - allowed)}")
    gate(bytes(candidate[MAP_BANK[0] : MAP_BANK[1]]) == parent[MAP_BANK[0] : MAP_BANK[1]], "original map-script bank changed")
    gate(sha256(MAIN_TIP_ROM.read_bytes()) == sha256(parent), "main TIP mutated during patch")
    gate(cave_cursor <= CAVE_END, "followup-term cave overflow")

    hangul_live12 = f2.hangul_slot_map(candidate, mode=12)
    hangul_live8 = f2.hangul_slot_map(candidate, mode=8)
    map12 = f2.slot_to_char_map(verified12, recovered12, hangul_live12)
    map8 = f2.slot_to_char_map(verified8, recovered8, hangul_live8)
    dict12 = load_dictionary(bytes(candidate), DICT_12X12_BASE, DICT_12X12_END)
    dict8 = load_dictionary(bytes(candidate), DICT_8X16_BASE, DICT_8X16_END)

    def live_u32(row: dict[str, Any], mode: int) -> str:
        owners = owner_offsets(row)
        return f2.decode_text(
            candidate,
            u32(candidate, owners[0]),
            dict12 if mode == 12 else dict8,
            map12 if mode == 12 else map8,
        )

    def live_has(row: dict[str, Any], needle: str) -> str:
        texts = (live_u32(row, 8), live_u32(row, 12))
        for text in texts:
            if needle in text:
                return text
        return " | ".join(ascii(text) for text in texts)

    def live_map(row: dict[str, Any]) -> str:
        cursor = int(str(row["target_file_offset"]), 16)
        raw = raw_hex_bytes(str((row.get("segments") or [{}])[0].get("raw_hex") or ""))
        orig = ROM_BASE + cursor
        lookups = aps.find_lookups(bytes(candidate), orig, orig + len(raw) - 1)
        gate(lookups, f"map lookup missing {row['record_id']}")
        return f2.decode_text(candidate, lookups[0][1], dict12, map12)

    proofs = {
        "balaena": live_has(by_id[BALAENA_ID], "발라에나"),
        "balaena_dyn": live_has(by_id[BALAENA_DYN_ID], "발라에나"),
        "ally_effect": live_has(by_id[ALLY_EFFECT_ID], "아군"),
        "domon": live_has(by_id[DOMON_ID], "물의 한 방울"),
        "bright": live_has(by_id[BRIGHT_ID], "결정타를 꽂아라"),
        "gihren_shell": live_map(by_id[GIHREN_SHELL_ID]),
        "kkeop_slot": hex(recovered12["껍"]),
        "kya_slot_still": map12.get(0x0146, "?"),
    }
    gate("발라에나" in proofs["balaena"] and "발레나" not in proofs["balaena"], ascii(proofs["balaena"]))
    gate("발라에나" in proofs["balaena_dyn"] and "발레나" not in proofs["balaena_dyn"], ascii(proofs["balaena_dyn"]))
    gate("아군" in proofs["ally_effect"] and "자군" not in proofs["ally_effect"], ascii(proofs["ally_effect"]))
    gate("물의 한 방울" in proofs["domon"] and "술의 한 방울" not in proofs["domon"], ascii(proofs["domon"]))
    gate("결정타를 꽂아라" in proofs["bright"] and "본명" not in proofs["bright"], ascii(proofs["bright"]))
    gate("껍데기" in proofs["gihren_shell"] and "꺄데기" not in proofs["gihren_shell"], ascii(proofs["gihren_shell"]))
    gate(recovered12["껍"] != 0x0146, f"껍 recovered onto 꺄 slot {proofs['kkeop_slot']}")
    gate(proofs["kya_slot_still"] == "꺄", f"0x0146 is no longer 꺄: {proofs['kya_slot_still']!r}")

    parent_identity = str(merged.get("identity", {}).get("translation_overlay_identity_sha256") or "")
    new_identity = digest(
        {
            "parent": parent_identity,
            "batch_id": BATCH_ID,
            "records": [row["record_id"] for row, *_rest in planned],
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
        "changed_records": [row["record_id"] for row, *_rest in planned],
        "notes": NOTES,
    }
    payload_json = json.dumps(merged, ensure_ascii=False, indent=2) + "\n"
    SNAPSHOT.write_text(payload_json, encoding="utf-8")
    TRANSLATION_MERGED_JSON.write_text(payload_json, encoding="utf-8")
    update_translation_manifest(merged, SNAPSHOT)
    BARKS.write_text(json.dumps(barks, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    WORK.write_bytes(bytes(candidate))
    shutil.copy2(MAIN_SAV, OUT / "ggen_followup_terms_20260912.sav")
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_followup_terms_20260912",
        "result": "PASS",
        "batch_id": BATCH_ID,
        "painted_glyphs": painted,
        "cave": {"start": hex(CAVE_START), "end": hex(cave_cursor), "capacity_end": hex(CAVE_END)},
        "counts": dict(counts),
        "changed_records": len(planned),
        "jobs": evidence,
        "proofs": proofs,
        "parent": {"path": advance_relative(MAIN_TIP_ROM), "sha256": sha256(parent)},
        "output": {"path": advance_relative(WORK), "sha256": sha256(candidate), "size": len(candidate)},
        "translation_source": {
            "path": advance_relative(TRANSLATION_MERGED_JSON),
            "sha256": sha256(payload_json.encode("utf-8")),
        },
        "verification": {
            "result": "PASS",
            "original_map_script_bank_unchanged": True,
            "no_old_token_leftover": True,
            "balaena_unified": True,
            "jagun_to_agun": True,
            "domon_water_drop": True,
            "bright_honmei_not_honmyou": True,
            "gihren_kkeopdegi_not_kyadegi": True,
            "runtime_emulator": "not run; static ROM verification only",
            "changed_bytes": len(changed),
        },
    }
    (OUT / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (ROOT / "analysis" / "ggen_advance_followup_terms_candidate_20260912.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "result": "PASS",
                "painted_glyphs": painted,
                "cave": report["cave"],
                "counts": report["counts"],
                "changed_records": len(planned),
                "output": report["output"],
                "proofs": proofs,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
