#!/usr/bin/env python3
"""Fix Shiro's 兄が妹を殺す line to 오빠 (Ginias/Aina).

The Aina-speaker 兄 pass left third-party 형. This line names the
Sahalin siblings, so Korean uses 오빠 not 형.
"""
from __future__ import annotations

import json
import shutil
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
    FONT12_RELOCATED,
    load_galmuri12,
    packed_12x12,
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
    hangul_chars,
    paint_12x12,
    recover_or_paint,
    visible_segments,
)
from patch_ggen_advance_intermission_text_consumers_20260904 import gate, sha256  # noqa: E402
from patch_ggen_advance_kimi_jane_to_neo_20260904 import (  # noqa: E402
    update_payload_hash,
    update_translation_manifest,
)
from patch_ggen_advance_map_script_inline_poc import load_identified_12x12  # noqa: E402
from patch_ggen_advance_name_unify_20260909 import patch_map_row_live  # noqa: E402

BATCH_ID = "shiro-oppa-sibling-20260910"
IDENTITY_KEY = "shiro_oppa_sibling_sha256"
BATCH_KEY = "shiro_oppa_sibling_20260910"
REPORT_KIND = "ggen_advance_shiro_oppa_sibling_candidate_20260910"
SNAPSHOT = ROOT / "analysis" / "ggen_advance_translation_merged_20260910_shiro_oppa_sibling.json"
OUT_DIR = ROOT / "outputs" / "20260910_ggen_advance_shiro_oppa_sibling"
OUTPUT = OUT_DIR / "ggen_advance_shiro_oppa_sibling_candidate_20260910.gba"
OUT_SAV = OUT_DIR / "ggen_advance_shiro_oppa_sibling_candidate_20260910.sav"
MAIN_SAV = ROOT / "SD Gundam GGeneration Advance (Korean).sav"
REPORT = ROOT / "analysis" / "ggen_advance_shiro_oppa_sibling_candidate_20260910.json"
MANIFEST = OUT_DIR / "manifest.json"
CAVE_START = 0x012B23D0
CAVE_END = 0x012B3000
MAP_BANK = (0x00F00000, 0x00FC0000)
VISUAL_DIALOGUE_CELLS = 14
NOTES = "시로 兄が妹を殺す……는 기니어스·아이나 남매이므로 오빠가 동생을 죽인다"
STALE = "형이 동생을 죽인다"
MAP_JOBS: dict[str, list[str]] = {
    "GGA-MAPSCRIPT-00F80F56": ["오빠가 동생을 죽인다……"],
}


def leftover_rows(records: list[dict[str, Any]]) -> list[str]:
    found: list[str] = []
    for row in records:
        if row.get("scope_status") == "alias":
            continue
        blob = str(row.get("translation_ko") or "")
        blob += "\n".join(str(item) for item in (row.get("translation_segments") or []))
        if STALE in blob:
            found.append(str(row["record_id"]))
    return found


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    apsaras_mod.CAVE_END = CAVE_END
    for record_id, lines in MAP_JOBS.items():
        for line in lines:
            gate("\n" not in line, f"newline in {record_id}: {line!r}")
            gate(len(line) <= VISUAL_DIALOGUE_CELLS, f"{record_id} {len(line)}>{VISUAL_DIALOGUE_CELLS}: {line!r}")
    original = ORIGINAL_ROM.read_bytes()
    current = MAIN_TIP_ROM.read_bytes()
    main_manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(len(current) == 32 * 1024 * 1024, "main TIP size drift")
    gate(sha256(current) == main_manifest.get("sha256"), "main TIP/manifest hash drift")
    gate(all(value == 0 for value in current[CAVE_START:CAVE_END]), "sibling cave is not zero-filled")
    gate(MAIN_SAV.exists(), "current main SAV missing")

    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    by_id = {str(row["record_id"]): row for row in merged["records"]}
    missing = sorted(set(MAP_JOBS) - set(by_id))
    gate(not missing, f"records missing {missing}")

    planned: list[tuple[dict[str, Any], str, list[str], list[str]]] = []
    hangul: set[str] = set()
    for record_id, new_visible in MAP_JOBS.items():
        row = by_id[record_id]
        before = str(row.get("translation_ko") or "")
        old_segments = [str(item) for item in (row.get("translation_segments") or [])]
        old_visible = visible_segments(old_segments) if old_segments else [part for part in before.split("\n") if part]
        gate(len(old_visible) == len(new_visible), f"visible count {record_id}")
        gate(STALE in before, f"expected stale 형 line {record_id}: {before!r}")
        if old_segments:
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
            new_segments = list(new_visible)
        after = "\n".join(new_visible)
        hangul.update(hangul_chars(before))
        hangul.update(hangul_chars(after))
        for text in old_segments + new_segments:
            hangul.update(hangul_chars(text))
        planned.append((row, before, old_segments, new_segments))

    font12 = load_galmuri12()
    live8, live12 = unified.collect_live_slots(original, merged["records"])
    del live8
    candidate = bytearray(current)
    allowed: set[int] = set()
    occupied12: set[int] = set()
    painted: list[dict[str, str]] = []
    recovered12: dict[str, int] = {}
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

    identified = load_identified_12x12()
    verified12 = unified.load_verified_charmap(unified.CHARMAP_12X12_PATH)
    cave_cursor = CAVE_START
    evidence: list[dict[str, Any]] = []

    for row, before, old_segments, new_segments in planned:
        record_id = str(row["record_id"])
        after = "\n".join(visible_segments(new_segments))
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
        gate(str(row.get("source_scope")) == "scenario_map_script", f"scope drift {record_id}")
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
        evidence.append(
            {
                "record_id": record_id,
                "source_scope": row.get("source_scope"),
                "speaker_id": row.get("speaker_id"),
                "before": before,
                "after": after,
                "cells": [len(line) for line in visible_segments(new_segments)],
                "segments": written,
            }
        )

    stale = leftover_rows(merged["records"])
    gate(not stale, f"stale 형이 동생을 죽인다 leftover {stale}")

    changed = [index for index, (before, after) in enumerate(zip(current, candidate)) if before != after]
    gate(set(changed) <= allowed, f"unexpected ROM byte change x{len(set(changed) - allowed)}")
    gate(bytes(candidate[MAP_BANK[0] : MAP_BANK[1]]) == current[MAP_BANK[0] : MAP_BANK[1]], "original map-script bank changed")
    gate(sha256(MAIN_TIP_ROM.read_bytes()) == sha256(current), "main TIP mutated during patch")
    gate(cave_cursor <= CAVE_END, "sibling cave overflow")

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
        "visual_dialogue_cells": VISUAL_DIALOGUE_CELLS,
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
            "visual_dialogue_cells": VISUAL_DIALOGUE_CELLS,
            "stale_hyung_sibling_leftover": 0,
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
                "changed_records": report["changed_records"],
                "output": report["output"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
