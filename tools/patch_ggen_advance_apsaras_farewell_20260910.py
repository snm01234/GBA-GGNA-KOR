#!/usr/bin/env python3
"""Fix leftover Apsaras spellings and Genius farewell to Aina.

JSON scenario 1 (GGA-SCENARIO-001F669C) is already 아프사라스. Remaining
in-game leftovers came from other writers:

- pending-readable 8x16 scroll ``압사라스등장``
- alt-setup map ``저 압살라스는``
- Genius 兄の手向けだ still said 형의 작별이다
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
    token_from_slot,
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
    choose_free_8x16,
    hangul_chars,
    paint_12x12,
    patch_owned_payload,
    recover_or_paint,
    visible_segments,
)
from patch_ggen_advance_dialogue_idcmd_fit_20260909 import live_char_tokens  # noqa: E402
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
    ROM_BASE,
    load_identified_12x12,
)
from patch_ggen_advance_name_unify_20260909 import (  # noqa: E402
    encode_overlay,
    patch_map_row_live,
)

BATCH_ID = "apsaras-farewell-leftover-20260910"
IDENTITY_KEY = "apsaras_farewell_leftover_sha256"
BATCH_KEY = "apsaras_farewell_leftover_20260910"
REPORT_KIND = "ggen_advance_apsaras_farewell_candidate_20260910"
SNAPSHOT = ROOT / "analysis" / "ggen_advance_translation_merged_20260910_apsaras_farewell.json"
OUT_DIR = ROOT / "outputs" / "20260910_ggen_advance_apsaras_farewell"
OUTPUT = OUT_DIR / "ggen_advance_apsaras_farewell_candidate_20260910.gba"
OUT_SAV = OUT_DIR / "ggen_advance_apsaras_farewell_candidate_20260910.sav"
MAIN_SAV = ROOT / "SD Gundam GGeneration Advance (Korean).sav"
REPORT = ROOT / "analysis" / "ggen_advance_apsaras_farewell_candidate_20260910.json"
MANIFEST = OUT_DIR / "manifest.json"
CAVE_START = 0x012B2380
CAVE_END = 0x012B3000
MAP_BANK = (0x00F00000, 0x00FC0000)
VISUAL_DIALOGUE_CELLS = 14
SCROLL_PREFIX = bytes.fromhex("E019E01FE01A")
STALE_NAMES = ("압사라스", "압살라스", "앱살라스", "앱살러스")
NOTES = (
    "전투 스크롤/맵 leftover 압사라스·압살라스→아프사라스. "
    "기니어스 兄の手向けだ는 오빠의 작별 선물"
)
KEPT_SCENARIO = "GGA-SCENARIO-001F669C"
KEPT_SCENARIO_KO = "너희 따위의 힘으로\n아프사라스를 쓰러뜨릴까보냐！"

MAP_JOBS: dict[str, list[str]] = {
    "GGA-MAPSCRIPT-00F85C72": ["저 아프사라스는", "대체 어디 누가?"],
    "GGA-MAPSCRIPT-00F80EF9": ["오빠의 작별 선물이다", "적어도 함께 보내주마……!"],
}
SCROLL_JOBS: dict[str, dict[str, str]] = {
    "GGA-TEXT-001C9A58": {"before": "압사라스등장", "after": "아프사라스등장"},
}
JSON_ONLY_JOBS: dict[str, str] = {
    "GGA-TEXT-001BF2C7": "승리조건：아프사라스Ⅲ 격파",
}


def emit_hangul(text: str, recovered: dict[str, int]) -> bytes:
    out = bytearray()
    for char in text:
        token = token_from_slot(recovered[char])
        if token <= 0xDF:
            out.append(token)
        else:
            out.extend((token >> 8, token & 0xFF))
    return bytes(out)


def leftover_rows(records: list[dict[str, Any]]) -> list[str]:
    found: list[str] = []
    for row in records:
        if row.get("scope_status") == "alias":
            continue
        blob = str(row.get("translation_ko") or "")
        blob += "\n".join(str(item) for item in (row.get("translation_segments") or []))
        if any(token in blob for token in STALE_NAMES) or "형의 작별이다" in blob:
            found.append(str(row["record_id"]))
    return found


def mark_row(row: dict[str, Any], after: str, new_segments: list[str]) -> None:
    row["translation_ko"] = after
    if new_segments:
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
    gate(all(value == 0 for value in current[CAVE_START:CAVE_END]), "farewell cave is not zero-filled")
    gate(MAIN_SAV.exists(), "current main SAV missing")

    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    by_id = {str(row["record_id"]): row for row in merged["records"]}
    wanted = set(MAP_JOBS) | set(SCROLL_JOBS) | set(JSON_ONLY_JOBS) | {KEPT_SCENARIO}
    missing = sorted(wanted - set(by_id))
    gate(not missing, f"records missing {missing}")
    gate(str(by_id[KEPT_SCENARIO].get("translation_ko") or "") == KEPT_SCENARIO_KO, "scenario 1 아프사라스 drift")

    planned: list[tuple[str, dict[str, Any], str, list[str], list[str]]] = []
    hangul: set[str] = set()
    for record_id, new_visible in MAP_JOBS.items():
        row = by_id[record_id]
        before = str(row.get("translation_ko") or "")
        old_segments = [str(item) for item in (row.get("translation_segments") or [])]
        old_visible = visible_segments(old_segments) if old_segments else [part for part in before.split("\n") if part]
        gate(len(old_visible) == len(new_visible), f"visible count {record_id}")
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
        gate(after != before or new_segments != old_segments, f"no-op {record_id}")
        hangul.update(hangul_chars(before))
        hangul.update(hangul_chars(after))
        for text in old_segments + new_segments:
            hangul.update(hangul_chars(text))
        planned.append(("map", row, before, old_segments, new_segments))

    for record_id, job in SCROLL_JOBS.items():
        row = by_id[record_id]
        before = str(row.get("translation_ko") or "")
        gate(before == job["before"], f"scroll JSON drift {record_id}: {before!r}")
        gate(not (row.get("translation_segments") or []), f"scroll unexpectedly segmented {record_id}")
        after = job["after"]
        hangul.update(hangul_chars(before))
        hangul.update(hangul_chars(after))
        planned.append(("scroll", row, before, [], []))

    for record_id, after in JSON_ONLY_JOBS.items():
        row = by_id[record_id]
        before = str(row.get("translation_ko") or "")
        gate(after != before, f"json-only no-op {record_id}")
        planned.append(("json_only", row, before, [], []))

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

    condition = by_id["GGA-TEXT-001BF2C7"]
    condition_owners = owner_offsets(condition)
    gate(condition_owners, "condition has no U32 owners")
    condition_ptr = struct.unpack_from("<I", current, condition_owners[0])[0]
    condition_live = payload_at(current, condition_ptr)
    gate(condition_live[:1] == b"\x1c", f"condition length prefix drift {condition_live[:1].hex()}")
    body_live = condition_live[1:]
    gate(emit_hangul("아프사라스", recovered12) in body_live, "condition ROM missing 아프사라스")
    gate(emit_hangul("압사라스", recovered12) not in body_live, "condition ROM still has 압사라스")

    identified = load_identified_12x12()
    verified12 = unified.load_verified_charmap(unified.CHARMAP_12X12_PATH)
    verified8 = unified.load_verified_charmap(unified.CHARMAP_8X16_PATH)
    cave_cursor = CAVE_START
    evidence: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()

    for kind, row, before, old_segments, new_segments in planned:
        record_id = str(row["record_id"])
        if kind == "map":
            after = "\n".join(visible_segments(new_segments))
        elif kind == "scroll":
            after = SCROLL_JOBS[record_id]["after"]
        else:
            after = JSON_ONLY_JOBS[record_id]
        mark_row(row, after, new_segments)

        if kind == "json_only":
            counts["json_only"] += 1
            evidence.append(
                {
                    "record_id": record_id,
                    "source_scope": row.get("source_scope"),
                    "rom": "unchanged",
                    "before": before,
                    "after": after,
                }
            )
            continue

        if kind == "map":
            gate(str(row.get("source_scope")) == "scenario_map_script", f"map scope drift {record_id}")
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
                    "source_scope": row.get("source_scope"),
                    "before": before,
                    "after": after,
                    "cells": [len(line) for line in visible_segments(new_segments)],
                    "segments": written,
                }
            )
            continue

        gate(kind == "scroll", f"unknown job kind {kind}")
        gate(str(row.get("source_scope")) == "production", f"scroll scope drift {record_id}")
        owners = owner_offsets(row)
        gate(owners, f"scroll has no U32 owners {record_id}")
        pointer = struct.unpack_from("<I", current, owners[0])[0]
        live = payload_at(current, pointer)
        gate(live.startswith(SCROLL_PREFIX), f"scroll prefix drift {record_id} {live[:6].hex()}")
        body = live[len(SCROLL_PREFIX) :]
        live_tokens = live_char_tokens(before, body)
        encoded_old = encode_overlay(before, recovered8, verified8, live_tokens)
        gate(encoded_old == body, f"scroll live encode mismatch {record_id}")
        new_body = encode_overlay(after, recovered8, verified8, live_tokens)
        verify_payload_painted(candidate, new_body, after, font8)
        new_payload = SCROLL_PREFIX + new_body
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
        counts["scroll"] += 1
        evidence.append(
            {
                "record_id": record_id,
                "source_scope": row.get("source_scope"),
                "font": "8x16",
                "before": before,
                "after": after,
                "old_active_addresses": old_addresses,
                "new_address": new_addr,
                "encoded_size": len(new_payload),
            }
        )

    stale = leftover_rows(merged["records"])
    gate(not stale, f"stale Apsaras/farewell leftover {stale}")

    changed = [index for index, (before, after) in enumerate(zip(current, candidate)) if before != after]
    gate(set(changed) <= allowed, f"unexpected ROM byte change x{len(set(changed) - allowed)}")
    gate(bytes(candidate[MAP_BANK[0] : MAP_BANK[1]]) == current[MAP_BANK[0] : MAP_BANK[1]], "original map-script bank changed")
    gate(sha256(MAIN_TIP_ROM.read_bytes()) == sha256(current), "main TIP mutated during patch")
    gate(cave_cursor <= CAVE_END, "farewell cave overflow")

    parent_identity = str(merged.get("identity", {}).get("translation_overlay_identity_sha256") or "")
    new_identity = digest(
        {
            "parent": parent_identity,
            "batch_id": BATCH_ID,
            "records": [row["record_id"] for _kind, row, _before, _old, _new in planned],
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
        "changed_records": [row["record_id"] for _kind, row, _before, _old, _new in planned],
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
            "visual_dialogue_cells": VISUAL_DIALOGUE_CELLS,
            "stale_name_leftover": 0,
            "kept_scenario": KEPT_SCENARIO,
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
