#!/usr/bin/env python3
"""Fit overflowing Doan Zaku II names by dropping two spaces.

ss7 unit-detail draws 8x16 names from x=0 into a 14-tile yellow box.
``자쿠 II 도안 전용기<S>`` is prefix + 12 body + 3-cell Super ``(S)`` = 16
and runs through the box edge.  Japanese ``ザクⅡ ドアン機`` has no space
inside ザクⅡ and none before 機, so Korean becomes ``자쿠II 도안전용기``.
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
    load_galmuri8,
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
from ggen_advance_text_codec import DICT_8X16_BASE, DICT_8X16_END, expand_to_slots, load_dictionary  # noqa: E402
from merge_ggen_advance_translation_overlays import digest  # noqa: E402
from patch_ggen_advance_apsaras_zentetsu_20260908 import (  # noqa: E402
    choose_free_8x16,
    hangul_chars,
    patch_owned_payload,
    recover_or_paint,
)
from patch_ggen_advance_dialogue_idcmd_fit_20260909 import live_char_tokens  # noqa: E402
from patch_ggen_advance_intermission_text_consumers_20260904 import (  # noqa: E402
    ROM_BASE,
    gate,
    payload_at,
    sha256,
)
from patch_ggen_advance_kimi_jane_to_neo_20260904 import (  # noqa: E402
    update_payload_hash,
    update_translation_manifest,
)
from patch_ggen_advance_name_unify_20260909 import encode_overlay  # noqa: E402

BATCH_ID = "doan-unit-name-fit-20260911"
IDENTITY_KEY = "doan_unit_name_fit_sha256"
BATCH_KEY = "doan_unit_name_fit_20260911"
REPORT_KIND = "ggen_advance_doan_unit_name_fit_candidate_20260911"
SNAPSHOT = ROOT / "analysis" / "ggen_advance_translation_merged_20260911_doan_unit_name.json"
OUT_DIR = ROOT / "outputs" / "20260911_ggen_advance_doan_unit_name"
OUTPUT = OUT_DIR / "ggen_advance_doan_unit_name_fit_candidate_20260911.gba"
OUT_SAV = OUT_DIR / "ggen_advance_doan_unit_name_fit_candidate_20260911.sav"
MAIN_SAV = ROOT / "SD Gundam GGeneration Advance (Korean).sav"
REPORT = ROOT / "analysis" / "ggen_advance_doan_unit_name_fit_candidate_20260911.json"
MANIFEST = OUT_DIR / "manifest.json"
CAVE_START = 0x012BB3C0
CAVE_END = 0x012BF000
MAP_BANK = (0x00F00000, 0x00FC0000)
NAME_BOX_CELLS = 14
OLD_BODY = "자쿠 II 도안 전용기"
NEW_BODY = "자쿠II 도안전용기"
UNIT_CATS = {"unit_name", "unit_name_alternate"}
NOTES = (
    "유닛 상세 8x16 이름칸 14. 자쿠II 도안전용기. Super (S) 3칸 포함 14칸"
)


def rewrite_name(text: str) -> str:
    if text.startswith(OLD_BODY):
        return NEW_BODY + text[len(OLD_BODY) :]
    return text


def slot_count(blob: bytes, dictionary) -> int:
    return len(expand_to_slots(unified.tokens_from_bytes(blob), dictionary))


def other_long_names(merged: dict[str, Any], rom: bytes, dictionary) -> list[dict[str, Any]]:
    seen: set[tuple[int, str]] = set()
    items: list[dict[str, Any]] = []
    for row in merged["records"]:
        if str(row.get("semantic_category") or "") not in UNIT_CATS:
            continue
        if str(row.get("translation_status") or "") != "translated":
            continue
        ko = str(row.get("translation_ko") or "")
        owners = [
            int(str(owner).removeprefix("OWNER-U32-"), 16)
            for owner in row.get("owner_ids") or []
            if str(owner).startswith("OWNER-U32-")
        ]
        if not owners:
            continue
        pointer = struct.unpack_from("<I", rom, owners[0])[0]
        live = payload_at(rom, pointer)
        cells = slot_count(live, dictionary)
        if cells < NAME_BOX_CELLS:
            continue
        key = (cells, ko)
        if key in seen:
            continue
        seen.add(key)
        items.append(
            {
                "record_id": row["record_id"],
                "semantic_category": row.get("semantic_category"),
                "translation_ko": ko,
                "source_text": row.get("source_text"),
                "live_cells": cells,
                "has_reserved_prefix": bool(unified.leading_reserved_prefix(live)),
            }
        )
    items.sort(key=lambda item: (-int(item["live_cells"]), str(item["translation_ko"])))
    return items


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    gate(len(NEW_BODY) == 10 and NEW_BODY.count(" ") == 1, f"shortened body drift {NEW_BODY!r}")

    original = ORIGINAL_ROM.read_bytes()
    current = MAIN_TIP_ROM.read_bytes()
    main_manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(len(current) == 32 * 1024 * 1024, "main TIP size drift")
    gate(sha256(current) == main_manifest.get("sha256"), "main TIP/manifest hash drift")
    gate(all(value == 0 for value in current[CAVE_START:CAVE_END]), "doan cave is not zero-filled")
    gate(MAIN_SAV.exists(), "current main SAV missing")

    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    dictionary = load_dictionary(original, DICT_8X16_BASE, DICT_8X16_END)
    long_before = other_long_names(merged, current, dictionary)

    targets = [
        row
        for row in merged["records"]
        if str(row.get("semantic_category") or "") in UNIT_CATS
        and OLD_BODY in str(row.get("translation_ko") or "")
    ]
    gate(len(targets) == 10, f"Doan unit-name row count drift: {len(targets)}")
    leftover_scopes = {str(row.get("source_scope")) for row in targets} - {
        "production",
        "non_scenario_ui",
    }
    gate(not leftover_scopes, f"unexpected scopes {sorted(leftover_scopes)}")

    planned: list[tuple[dict[str, Any], str, str]] = []
    hangul: set[str] = set()
    for row in targets:
        before = str(row.get("translation_ko") or "")
        after = rewrite_name(before)
        gate(after != before, f"no-op {row['record_id']}")
        gate(after.startswith(NEW_BODY), f"rewrite missed {row['record_id']}: {after!r}")
        hangul.update(hangul_chars(before))
        hangul.update(hangul_chars(after))
        planned.append((row, before, after))

    font8 = load_galmuri8()
    live8, _live12 = unified.collect_live_slots(original, merged["records"])
    candidate = bytearray(current)
    allowed: set[int] = set()
    occupied8: set[int] = set()
    painted: list[dict[str, str]] = []
    recovered8: dict[str, int] = {}
    apsaras_mod.CAVE_END = CAVE_END
    for char in sorted(hangul):
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
    gate(not painted, f"unexpected new Hangul paint {painted}")

    verified8 = unified.load_verified_charmap(unified.CHARMAP_8X16_PATH)
    cave_cursor = CAVE_START
    evidence: list[dict[str, Any]] = []
    for row, before, after in planned:
        owners = tuple(
            int(str(owner).removeprefix("OWNER-U32-"), 16)
            for owner in row.get("owner_ids") or []
            if str(owner).startswith("OWNER-U32-")
        )
        gate(owners, f"no U32 owners {row['record_id']}")
        pointer = struct.unpack_from("<I", current, owners[0])[0]
        live = payload_at(current, pointer)
        prefix = unified.leading_reserved_prefix(live)
        body = live[len(prefix) :]
        live_tokens = live_char_tokens(before, body)
        old_body = encode_overlay(before, recovered8, verified8, live_tokens)
        gate(prefix + old_body == live, f"live encode mismatch {row['record_id']}")
        new_body = encode_overlay(after, recovered8, verified8, live_tokens)
        new_payload = prefix + new_body
        cells = slot_count(new_payload, dictionary)
        gate(cells <= NAME_BOX_CELLS, f"{row['record_id']} still {cells}>{NAME_BOX_CELLS}: {after!r}")
        row["translation_ko"] = after
        row["translation_status"] = "translated"
        row["translation_source"] = "user_verified"
        row["review_status"] = "user_verified"
        row["review_count"] = int(row.get("review_count") or 0) + 1
        row["reviewed_at"] = "2026-09-11"
        row["translator_notes"] = NOTES
        row["qa_status"] = "static_consumer_verified"
        row["overlay_batch_id"] = BATCH_ID
        update_payload_hash(row)
        cave_cursor, old_addresses, new_addr = patch_owned_payload(
            row,
            live,
            new_payload,
            current,
            candidate,
            allowed,
            cave_cursor,
            require_nul=True,
        )
        evidence.append(
            {
                "record_id": row["record_id"],
                "source_scope": row.get("source_scope"),
                "before": before,
                "after": after,
                "before_cells": slot_count(live, dictionary),
                "after_cells": cells,
                "prefix_hex": prefix.hex(" "),
                "old_active_addresses": old_addresses,
                "new_address": new_addr,
                "encoded_size": len(new_payload),
                "in_place": new_addr == old_addresses[0],
            }
        )

    leftover = [
        row["record_id"]
        for row in merged["records"]
        if str(row.get("semantic_category") or "") in UNIT_CATS
        and OLD_BODY in str(row.get("translation_ko") or "")
    ]
    gate(not leftover, f"Doan body leftover {leftover}")
    changed = [index for index, (before, after) in enumerate(zip(current, candidate)) if before != after]
    gate(set(changed) <= allowed, f"unexpected ROM byte change x{len(set(changed) - allowed)}")
    gate(
        bytes(candidate[MAP_BANK[0] : MAP_BANK[1]]) == current[MAP_BANK[0] : MAP_BANK[1]],
        "original map-script bank changed",
    )
    gate(sha256(MAIN_TIP_ROM.read_bytes()) == sha256(current), "main TIP mutated during patch")
    gate(cave_cursor <= CAVE_END, "doan cave overflow")

    parent_identity = str(merged.get("identity", {}).get("translation_overlay_identity_sha256") or "")
    new_identity = digest(
        {
            "parent": parent_identity,
            "batch_id": BATCH_ID,
            "records": [row["record_id"] for row, _before, _after in planned],
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
        "changed_records": [row["record_id"] for row, _before, _after in planned],
    }
    payload_json = json.dumps(merged, ensure_ascii=False, indent=2) + "\n"
    SNAPSHOT.write_text(payload_json, encoding="utf-8")
    TRANSLATION_MERGED_JSON.write_text(payload_json, encoding="utf-8")
    update_translation_manifest(merged, SNAPSHOT)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(bytes(candidate))
    shutil.copy2(MAIN_SAV, OUT_SAV)

    long_after = other_long_names(merged, bytes(candidate), dictionary)
    report = {
        "schema_version": 1,
        "kind": REPORT_KIND,
        "result": "PASS",
        "batch_id": BATCH_ID,
        "name_box_cells": NAME_BOX_CELLS,
        "shortening": {"old": OLD_BODY, "new": NEW_BODY},
        "painted_glyphs": painted,
        "cave": {"start": hex(CAVE_START), "end": hex(cave_cursor), "capacity_end": hex(CAVE_END)},
        "changed_records": len(planned),
        "jobs": evidence,
        "other_unit_names_at_or_over_box": long_after,
        "other_unit_names_before": long_before,
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
            "no_new_hangul_paint": True,
            "doan_super_with_prefix_fits_14": True,
            "runtime_emulator": "not run; static ROM + ss7 box measurement only",
            "changed_bytes": len(changed),
        },
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    MANIFEST.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "result": "PASS",
                "changed_records": len(planned),
                "jobs": [
                    {
                        "record_id": item["record_id"],
                        "before": item["before"],
                        "after": item["after"],
                        "before_cells": item["before_cells"],
                        "after_cells": item["after_cells"],
                    }
                    for item in evidence
                ],
                "other_unit_names_at_or_over_box": long_after,
                "output": report["output"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
