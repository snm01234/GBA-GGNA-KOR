#!/usr/bin/env python3
"""Fit Aina ss1-ss4 portrait lines to 14 cells and fix female-speaker 兄.

ss1-ss4 show the 15th 12x12 cell drawing into the yellow box frame. Japanese
in this box is <=14. Apsaras 앱살라스(4)->아프사라스(5) plus the old 15-cell
gate packed several lines to the frame. Aina (speaker 0x000A) also rendered
bare 兄 as 형; お兄さま was already 오빠/오라버니.
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

BATCH_ID = "aina-overflow-honorific-20260910"
IDENTITY_KEY = "aina_overflow_honorific_sha256"
BATCH_KEY = "aina_overflow_honorific_20260910"
REPORT_KIND = "ggen_advance_aina_overflow_honorific_candidate_20260910"
SNAPSHOT = ROOT / "analysis" / "ggen_advance_translation_merged_20260910_aina_overflow_honorific.json"
OUT_DIR = ROOT / "outputs" / "20260910_ggen_advance_aina_overflow_honorific"
OUTPUT = OUT_DIR / "ggen_advance_aina_overflow_honorific_candidate_20260910.gba"
OUT_SAV = OUT_DIR / "ggen_advance_aina_overflow_honorific_candidate_20260910.sav"
MAIN_SAV = ROOT / "SD Gundam GGeneration Advance (Korean).sav"
REPORT = ROOT / "analysis" / "ggen_advance_aina_overflow_honorific_candidate_20260910.json"
MANIFEST = OUT_DIR / "manifest.json"
CAVE_START = 0x012B2240
CAVE_END = 0x012B3000
MAP_BANK = (0x00F00000, 0x00FC0000)
VISUAL_DIALOGUE_CELLS = 14
NOTES = (
    "아이나 兄→오빠. 초상 대사 15번째 칸이 상자 테두리에 들어가 "
    "시각 한도를 14칸으로 맞춤"
)
AINA_SPEAKER = "0x000A"

# Keep two (or one) map segments. 14-cell visual inner width.
MAP_JOBS: dict[str, list[str]] = {
    "GGA-MAPSCRIPT-00F7F6ED": ["아프사라스가 나서면 당신들", "싸우게 할 일도 없는데……"],
    "GGA-MAPSCRIPT-00F7F729": ["오빠는 아프사라스를 지키려", "병사를 희생시키려 합니다"],
    "GGA-MAPSCRIPT-00F7F747": ["모처럼 아프사라스 완성돼,", "자브로도 떨어뜨렸는데……"],
    "GGA-MAPSCRIPT-00F7F766": ["오빠는 그 아프사라스에,", "자신의 꿈에 사로잡혔다"],
    "GGA-MAPSCRIPT-00F7F7C3": ["병사들을 오빠의 망집과", "함께 죽게 할 순 없습니다"],
    "GGA-MAPSCRIPT-00F7F875": ["나는…… 부모 대신인", "노리스를 아무것도 몰라"],
    "GGA-MAPSCRIPT-00F8101E": ["시로……", "설계자인 오빠가……"],
    "GGA-MAPSCRIPT-00F81222": ["우리는", "아이나의 오빠를……"],
    "GGA-MAPSCRIPT-00F8128E": ["오빠가 준 시계가,", "내 목숨을 이어 주었습니다"],
    "GGA-MAPSCRIPT-00F812B4": ["……미안하다, 아이나", "우리는 네 오빠를……"],
    "GGA-MAPSCRIPT-00F812E6": ["이미, 한참 전부터", "오빠와는 말이 통하질 않아"],
    "GGA-MAPSCRIPT-00F85124": ["그건 오빠와 함께……"],
    "GGA-MAPSCRIPT-00F8513C": ["아이나, 진정해!!", "저건 네 오빠가 아니야!"],
    "GGA-MAPSCRIPT-00F85C86": ["아이나의 오빠와 함께", "자브로에서 사라졌을 텐데"],
    "GGA-MAPSCRIPT-00FACEF3": ["이제 오빠에겐 지온도", "연방도 아무래도 좋겠지요"],
    "GGA-MAPSCRIPT-00FACF2E": ["자신과 그롬린밖에", "오빠 눈엔 들어오지 않아요"],
    "GGA-MAPSCRIPT-00FACF4A": ["그 밖의 모든 것을", "오빠는 거부하려 해요……"],
    "GGA-MAPSCRIPT-00FACF87": ["지금 오빠를 막지 않으면", "무서운 일이 되고 말아요"],
    "GGA-MAPSCRIPT-00FB1B30": ["오빠는 어찌 된 겁니까!?", "숨어 있는 겁니까!?"],
    "GGA-MAPSCRIPT-00FB1DA8": ["하지만, 그롬린은……", "오빠는 안 나타났어……"],
    "GGA-MAPSCRIPT-00FB293E": ["힘에 미친 당신을", "오빠로 생각하지 않아요!"],
}
UI_JOBS: dict[str, str] = {
    "GGA-UI-001860A7": "오빠 기니어스가 추진한 아프사라스 개발 계",
}


def kin_hyung(text: str) -> bool:
    return any(
        token in text
        for token in ("형은", "형이", "형을", "형과", "형의", "형에게", "형께", "형님", "형 ")
    ) or text.startswith("형") or " 형" in text


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    for record_id, lines in MAP_JOBS.items():
        for line in lines:
            gate("\n" not in line, f"newline in {record_id}: {line!r}")
            gate(len(line) <= VISUAL_DIALOGUE_CELLS, f"{record_id} {len(line)}>{VISUAL_DIALOGUE_CELLS}: {line!r}")
    original = ORIGINAL_ROM.read_bytes()
    current = MAIN_TIP_ROM.read_bytes()
    main_manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(len(current) == 32 * 1024 * 1024, "main TIP size drift")
    gate(sha256(current) == main_manifest.get("sha256"), "main TIP/manifest hash drift")
    gate(all(value == 0 for value in current[CAVE_START:CAVE_END]), "honorific cave is not zero-filled")
    gate(MAIN_SAV.exists(), "current main SAV missing")

    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    by_id = {str(row["record_id"]): row for row in merged["records"]}
    wanted = set(MAP_JOBS) | set(UI_JOBS)
    missing = sorted(wanted - set(by_id))
    gate(not missing, f"records missing {missing}")

    planned: list[tuple[dict[str, Any], str, list[str], list[str]]] = []
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
        planned.append((row, before, old_segments, new_segments))

    for record_id, after in UI_JOBS.items():
        row = by_id[record_id]
        before = str(row.get("translation_ko") or "")
        old_segments = [str(item) for item in (row.get("translation_segments") or [])]
        gate(not old_segments, f"UI unexpectedly segmented {record_id}")
        gate(after != before, f"UI no-op {record_id}")
        hangul.update(hangul_chars(before))
        hangul.update(hangul_chars(after))
        planned.append((row, before, old_segments, []))

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
        record_id = str(row["record_id"])
        after = "\n".join(visible_segments(new_segments)) if new_segments else UI_JOBS[record_id]
        row["translation_ko"] = after
        if old_segments:
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
                    "record_id": record_id,
                    "source_scope": scope,
                    "before": before,
                    "after": after,
                    "cells": [len(line) for line in visible_segments(new_segments)],
                    "segments": written,
                }
            )
            continue

        gate(scope == "non_scenario_ui", f"unexpected scope {record_id}")
        owners = tuple(
            int(owner.removeprefix("OWNER-U32-"), 16)
            for owner in row.get("owner_ids", [])
            if str(owner).startswith("OWNER-U32-")
        )
        gate(owners, f"UI has no U32 owners {record_id}")
        pointer = struct.unpack_from("<I", current, owners[0])[0]
        live = payload_at(current, pointer)
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
                f"gate failed: UI live encode mismatch {record_id} live={live.hex()} "
                f"12={try12.hex()} 8={try8.hex()}"
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
                "record_id": record_id,
                "source_scope": scope,
                "font": font_used,
                "before": before,
                "after": after,
                "old_active_addresses": old_addresses,
                "new_address": new_addr,
                "encoded_size": len(new_payload),
            }
        )

    aina_hyung = [
        row["record_id"]
        for row in merged["records"]
        if row.get("scope_status") != "alias"
        and row.get("speaker_id") == AINA_SPEAKER
        and kin_hyung(str(row.get("translation_ko") or ""))
    ]
    gate(not aina_hyung, f"Aina 형 leftover {aina_hyung}")
    chained_ss2 = str(by_id["GGA-MAPSCRIPT-00F7F766"].get("translation_ko") or "")
    gate("오빠" in chained_ss2 and "형" not in chained_ss2, "ss2 형 leftover")
    gate(str(by_id["GGA-UI-001860A7"].get("translation_ko")) == UI_JOBS["GGA-UI-001860A7"], "UI bio drift")

    changed = [index for index, (before, after) in enumerate(zip(current, candidate)) if before != after]
    gate(set(changed) <= allowed, f"unexpected ROM byte change x{len(set(changed) - allowed)}")
    gate(bytes(candidate[MAP_BANK[0] : MAP_BANK[1]]) == current[MAP_BANK[0] : MAP_BANK[1]], "original map-script bank changed")
    gate(sha256(MAIN_TIP_ROM.read_bytes()) == sha256(current), "main TIP mutated during patch")
    gate(cave_cursor <= CAVE_END, "honorific cave overflow")

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
            "aina_speaker_hyung_leftover": 0,
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
