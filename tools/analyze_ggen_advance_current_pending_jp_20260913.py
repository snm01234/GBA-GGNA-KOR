#!/usr/bin/env python3
"""Classify current-main remaining Japanese display paths.

Sheet ``pending`` is not the same as on-screen Japanese.  This audit walks the
canonical translation sheet against the live 32 MiB main TIP and reports which
pending/preserve/needs_review rows still have a live draw path to original JP
bytes, versus blank/unreferenced/intentionally preserved rows.
"""
from __future__ import annotations

import hashlib
import json
import re
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from analyze_ggen_advance_pending_decode import CORRECTED_LOW_KANA  # noqa: E402
from build_ggen_advance_unified_rom_poc import (  # noqa: E402
    CHARMAP_12X12_PATH,
    CHARMAP_8X16_PATH,
    DICT_12X12_BASE,
    DICT_12X12_END,
    DICT_8X16_BASE,
    DICT_8X16_END,
    SCENARIO_12X12_SCOPES,
    load_dictionary,
    load_identified_slot_to_char,
    raw_hex_bytes,
    tokens_from_bytes,
    uses_12x12,
)
from ggen_advance_project_paths import (  # noqa: E402
    MAIN_TIP_MANIFEST,
    MAIN_TIP_ROM,
    ORIGINAL_ROM,
    TRANSLATION_MANIFEST,
    TRANSLATION_MERGED_JSON,
    advance_relative,
)
from ggen_advance_text_codec import expand_to_slots  # noqa: E402

ROM_BASE = 0x08000000
LIVE_LOOKUP_PTR_OFF = 0x01112588
LIVE_LOOKUP_COUNT_OFF = 0x0111258C
ENTRY_SIZE = 12
OUTPUT = ROOT / "analysis" / "ggen_advance_current_pending_jp_20260913.json"
KANA_RE = re.compile(r"[\u3040-\u30ff]")
KANJI_RE = re.compile(r"[\u4e00-\u9fff]")
HANGUL_RE = re.compile(r"[\uac00-\ud7a3]")
BLANK_RE = re.compile(r"^[\s　]*$")
CONTROL_ONLY_RE = re.compile(r"^(?:<[^>]+>|\s|　)*$")

VISIBLE_SCOPES = {
    "production",
    "non_scenario_ui",
    "scenario_main",
    "scenario_dynamic",
    "scenario_map_script",
    "id_command_battle_bark",
    "battle_event_dialogue",
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def payload_at(rom: bytes, address: int, limit: int = 0x180) -> bytes | None:
    offset = address - ROM_BASE
    if not 0 <= offset < len(rom):
        return None
    end = rom.find(0, offset, min(len(rom), offset + limit))
    if end < 0:
        return None
    return bytes(rom[offset : end + 1])


def owner_offsets(row: dict[str, Any]) -> list[int]:
    return [
        int(str(owner_id).removeprefix("OWNER-U32-"), 16)
        for owner_id in row.get("owner_ids") or []
        if str(owner_id).startswith("OWNER-U32-")
    ]


def source_kind(text: str) -> str:
    stripped = text.replace("\n", "").strip()
    if not stripped or BLANK_RE.match(stripped):
        return "blank"
    if CONTROL_ONLY_RE.match(stripped):
        return "control_or_marker"
    if HANGUL_RE.search(stripped) and not KANA_RE.search(stripped):
        return "hangul_source"
    if KANA_RE.search(stripped) or KANJI_RE.search(stripped):
        return "japanese_source"
    return "other"


def decode_payload(raw: bytes, dictionary, charmap: dict[int, str]) -> tuple[str, int]:
    slots = expand_to_slots(tokens_from_bytes(raw), dictionary)
    chars: list[str] = []
    missing = 0
    for slot in slots:
        char = charmap.get(slot)
        if char is None:
            chars.append(f"<{slot:04X}>")
            missing += 1
        else:
            chars.append(char)
    return "".join(chars), missing


def load_lookup(rom: bytes) -> dict[int, int]:
    table_addr = u32(rom, LIVE_LOOKUP_PTR_OFF)
    count = u32(rom, LIVE_LOOKUP_COUNT_OFF)
    offset = table_addr - ROM_BASE
    table: dict[int, int] = {}
    if not (0 <= offset < len(rom)) or count <= 0 or count > 80_000:
        return table
    end = offset + count * ENTRY_SIZE
    if end > len(rom):
        return table
    for index in range(count):
        pos = offset + index * ENTRY_SIZE
        orig, neu, _orig_end = struct.unpack_from("<III", rom, pos)
        table[orig] = neu
    return table


def mapscript_keys(row: dict[str, Any]) -> list[int]:
    keys: list[int] = []
    target = int(str(row.get("target_address") or "0"), 16)
    if target:
        keys.append(target)
    for item in row.get("segments") or []:
        if not isinstance(item, dict):
            continue
        for field in ("opcode_alias", "original_address", "source_address"):
            value = item.get(field)
            if value:
                keys.append(int(str(value), 16))
    return sorted(set(keys))


def classify_live(
    row: dict[str, Any],
    main: bytes,
    orig_raw: bytes,
    lookup: dict[int, int],
) -> str:
    scope = str(row.get("source_scope") or "")
    owners = owner_offsets(row)
    if scope == "scenario_map_script":
        keys = mapscript_keys(row)
        redirected = [key for key in keys if key in lookup]
        if redirected:
            return "map_redirected_korean"
        if not keys:
            return "map_no_address"
        return "map_no_lookup_original_jp"
    if not owners:
        live = payload_at(main, int(str(row.get("target_address") or "0"), 16))
        if live is None:
            return "no_owner_unreadable"
        if live == orig_raw:
            return "no_owner_original_bytes"
        return "no_owner_payload_changed"
    still = 0
    moved = 0
    for offset in owners:
        if offset + 4 > len(main):
            continue
        pointer = u32(main, offset)
        live = payload_at(main, pointer)
        if live == orig_raw:
            still += 1
        else:
            moved += 1
    if still and not moved:
        return "u32_still_original_jp"
    if moved and not still:
        return "u32_retargeted"
    if still and moved:
        return "u32_mixed_owners"
    return "u32_unreadable"


def bucket_visibility(status: str, live: str, kind: str) -> str:
    if status == "preserve":
        return "intentional_preserve"
    if status == "needs_review" and kind in {"blank", "control_or_marker"}:
        return "blank_or_empty_box"
    if kind in {"blank", "control_or_marker"} and live in {
        "map_no_lookup_original_jp",
        "u32_still_original_jp",
        "no_owner_original_bytes",
    }:
        return "blank_or_empty_box"
    if live in {"map_redirected_korean", "u32_retargeted"}:
        return "sheet_pending_but_live_korean"
    if live in {"map_no_lookup_original_jp", "u32_still_original_jp", "u32_mixed_owners"}:
        if kind == "japanese_source":
            return "live_original_japanese"
        return "live_original_bytes_non_jp_or_partial"
    if live in {"no_owner_original_bytes", "no_owner_unreadable", "map_no_address"}:
        return "unproven_or_unreferenced"
    return "other"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    tip_manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    translation_manifest = json.loads(TRANSLATION_MANIFEST.read_text(encoding="utf-8"))
    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    main = MAIN_TIP_ROM.read_bytes()
    original = ORIGINAL_ROM.read_bytes()
    tip_sha = sha256(main)
    lookup = load_lookup(main)
    dict8 = load_dictionary(original, DICT_8X16_BASE, DICT_8X16_END)
    dict12 = load_dictionary(original, DICT_12X12_BASE, DICT_12X12_END)
    map8 = load_identified_slot_to_char(CHARMAP_8X16_PATH)
    map8.update(CORRECTED_LOW_KANA)
    map12 = load_identified_slot_to_char(CHARMAP_12X12_PATH)
    map12.update(CORRECTED_LOW_KANA)

    status_counts = Counter(str(row.get("translation_status") or "") for row in merged["records"])
    interesting = [
        row
        for row in merged["records"]
        if str(row.get("translation_status") or "") in {"pending", "preserve", "needs_review"}
        and str(row.get("scope_status") or "") == "included"
    ]

    rows_out: list[dict[str, Any]] = []
    visibility = Counter()
    by_status_scope = defaultdict(Counter)
    by_status_cat = defaultdict(Counter)
    by_status_live = defaultdict(Counter)
    by_status_kind = defaultdict(Counter)
    live_jp_samples: list[dict[str, Any]] = []

    for row in interesting:
        status = str(row.get("translation_status") or "")
        scope = str(row.get("source_scope") or "")
        cat = str(row.get("semantic_category") or "unknown")
        text = str(row.get("source_text") or "")
        kind = source_kind(text)
        orig_raw = raw_hex_bytes(str(row.get("raw_hex") or ""))
        live = classify_live(row, main, orig_raw, lookup)
        vis = bucket_visibility(status, live, kind)
        decoded = ""
        missing = 0
        if orig_raw:
            dictionary = dict12 if uses_12x12(row) else dict8
            charmap = map12 if uses_12x12(row) else map8
            decoded, missing = decode_payload(orig_raw, dictionary, charmap)
        item = {
            "record_id": row.get("record_id"),
            "translation_status": status,
            "source_scope": scope,
            "semantic_category": cat,
            "source_decode_status": row.get("source_decode_status"),
            "translation_policy": row.get("translation_policy"),
            "source_kind": kind,
            "live_path": live,
            "visibility": vis,
            "owner_count": len(owner_offsets(row)),
            "source_text": text,
            "decoded_jp": decoded,
            "unresolved_slots": missing,
            "translation_ko": row.get("translation_ko") or "",
        }
        rows_out.append(item)
        visibility[vis] += 1
        by_status_scope[status][scope] += 1
        by_status_cat[status][cat] += 1
        by_status_live[status][live] += 1
        by_status_kind[status][kind] += 1
        if vis == "live_original_japanese":
            live_jp_samples.append(item)

    live_jp_by_scope = Counter(item["source_scope"] for item in live_jp_samples)
    live_jp_by_cat = Counter(item["semantic_category"] for item in live_jp_samples)
    live_jp_by_decode = Counter(str(item.get("source_decode_status") or "") for item in live_jp_samples)

    still_original = [item for item in rows_out if item["live_path"] in {
        "u32_still_original_jp",
        "map_no_lookup_original_jp",
        "no_owner_original_bytes",
        "u32_mixed_owners",
    }]
    still_by_cat_kind = Counter(
        (item["translation_status"], item["semantic_category"], item["source_kind"], item["live_path"])
        for item in still_original
    )
    still_jp_readable = [
        item for item in still_original
        if item["source_kind"] == "japanese_source"
    ]

    dialogue_scopes = {
        "scenario_main",
        "scenario_dynamic",
        "scenario_map_script",
        "id_command_battle_bark",
        "battle_event_dialogue",
    }
    translated_still_jp: list[dict[str, Any]] = []
    translated_map_missing_lookup: list[dict[str, Any]] = []
    translated_checked = 0
    for row in merged["records"]:
        if str(row.get("scope_status") or "") != "included":
            continue
        if str(row.get("translation_status") or "") != "translated":
            continue
        scope = str(row.get("source_scope") or "")
        if scope not in dialogue_scopes and str(row.get("semantic_category") or "") not in {
            "id_command_name",
            "id_command_description",
            "id_command_effect_summary",
            "weapon_name",
            "unit_name",
            "character_name",
        }:
            continue
        translated_checked += 1
        orig_raw = raw_hex_bytes(str(row.get("raw_hex") or ""))
        live = classify_live(row, main, orig_raw, lookup)
        kind = source_kind(str(row.get("source_text") or ""))
        if live in {"map_no_lookup_original_jp", "u32_still_original_jp", "u32_mixed_owners"} and kind == "japanese_source":
            item = {
                "record_id": row.get("record_id"),
                "source_scope": scope,
                "semantic_category": row.get("semantic_category"),
                "live_path": live,
                "source_text": row.get("source_text"),
                "translation_ko": row.get("translation_ko") or "",
            }
            translated_still_jp.append(item)
            if live == "map_no_lookup_original_jp":
                translated_map_missing_lookup.append(item)

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_current_pending_jp_20260913",
        "main_tip": {
            "path": advance_relative(MAIN_TIP_ROM),
            "sha256": tip_sha,
            "manifest_sha256": tip_manifest.get("sha256"),
            "sha_matches_manifest": tip_sha == str(tip_manifest.get("sha256") or "").lower(),
            "promotion_reason": tip_manifest.get("promotion_reason"),
            "approved_at_utc": tip_manifest.get("approved_at_utc"),
            "size": len(main),
        },
        "translation": {
            "path": advance_relative(TRANSLATION_MERGED_JSON),
            "record_count": len(merged["records"]),
            "status_counts": dict(status_counts),
            "manifest_status_counts": translation_manifest.get("record_translation_status_counts"),
        },
        "map_lookup": {
            "pointer": hex(u32(main, LIVE_LOOKUP_PTR_OFF)),
            "count": u32(main, LIVE_LOOKUP_COUNT_OFF),
            "loaded_entries": len(lookup),
        },
        "visibility_counts": dict(visibility),
        "pending_by_scope": dict(by_status_scope["pending"]),
        "pending_by_category": dict(by_status_cat["pending"]),
        "pending_by_live_path": dict(by_status_live["pending"]),
        "pending_by_source_kind": dict(by_status_kind["pending"]),
        "preserve_by_scope": dict(by_status_scope["preserve"]),
        "preserve_by_category": dict(by_status_cat["preserve"]),
        "needs_review_by_scope": dict(by_status_scope["needs_review"]),
        "needs_review_by_kind": dict(by_status_kind["needs_review"]),
        "live_original_japanese": {
            "count": len(live_jp_samples),
            "by_scope": dict(live_jp_by_scope),
            "by_category": dict(live_jp_by_cat),
            "by_decode_status": dict(live_jp_by_decode),
            "all": live_jp_samples,
        },
        "still_original_payload_rows": {
            "count": len(still_original),
            "japanese_source_count": len(still_jp_readable),
            "by_status_category_kind_path": [
                {
                    "status": key[0],
                    "category": key[1],
                    "source_kind": key[2],
                    "live_path": key[3],
                    "count": count,
                }
                for key, count in sorted(still_by_cat_kind.items(), key=lambda item: (-item[1], item[0]))
            ],
            "japanese_source_rows": still_jp_readable,
        },
        "translated_dialogue_or_name_still_original_jp": {
            "checked": translated_checked,
            "count": len(translated_still_jp),
            "map_missing_lookup": len(translated_map_missing_lookup),
            "by_scope": dict(Counter(item["source_scope"] for item in translated_still_jp)),
            "by_category": dict(Counter(item["semantic_category"] for item in translated_still_jp)),
            "samples": translated_still_jp[:80],
        },
        "scenario_12x12_scopes": sorted(SCENARIO_12X12_SCOPES),
        "visible_scopes": sorted(VISIBLE_SCOPES),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "report": advance_relative(OUTPUT),
                "main_tip_sha256": tip_sha,
                "sha_matches_manifest": report["main_tip"]["sha_matches_manifest"],
                "promotion_reason": tip_manifest.get("promotion_reason"),
                "sheet_status_counts": dict(status_counts),
                "map_lookup_count": report["map_lookup"]["count"],
                "visibility_counts": dict(visibility),
                "live_original_japanese": {
                    "count": len(live_jp_samples),
                    "by_scope": dict(live_jp_by_scope),
                    "by_category": dict(live_jp_by_cat),
                    "by_decode_status": dict(live_jp_by_decode),
                    "sample_ids": [
                        {
                            "record_id": item["record_id"],
                            "scope": item["source_scope"],
                            "category": item["semantic_category"],
                            "text": item["source_text"],
                        }
                        for item in live_jp_samples[:40]
                    ],
                },
                "pending_by_scope": dict(by_status_scope["pending"]),
                "pending_by_category": dict(by_status_cat["pending"]),
                "pending_by_live_path": dict(by_status_live["pending"]),
                "pending_by_source_kind": dict(by_status_kind["pending"]),
                "preserve_by_category": dict(by_status_cat["preserve"]),
                "needs_review_by_kind": dict(by_status_kind["needs_review"]),
                "still_original_japanese_source": len(still_jp_readable),
                "still_original_breakdown": [
                    {
                        "status": key[0],
                        "category": key[1],
                        "source_kind": key[2],
                        "live_path": key[3],
                        "count": count,
                    }
                    for key, count in sorted(still_by_cat_kind.items(), key=lambda item: (-item[1], item[0]))[:40]
                ],
                "translated_dialogue_or_name_still_original_jp": {
                    "checked": translated_checked,
                    "count": len(translated_still_jp),
                    "by_scope": dict(Counter(item["source_scope"] for item in translated_still_jp)),
                    "by_category": dict(Counter(item["semantic_category"] for item in translated_still_jp)),
                    "samples": [
                        {
                            "record_id": item["record_id"],
                            "scope": item["source_scope"],
                            "category": item["semantic_category"],
                            "text": item["source_text"],
                            "ko": item["translation_ko"],
                        }
                        for item in translated_still_jp[:30]
                    ],
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
