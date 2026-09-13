#!/usr/bin/env python3
"""Translate remaining Extra-session map scripts (pending after 20260910).

Parent is the nimbus/Exss4 candidate: lookup table already lives at
0x01360000, and 106 Extra-cluster lines are already hooked.  This batch
encodes the other Extra-bank rows that have real Japanese text.
Whitespace-only dummy prints stay pending.
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
from build_ggen_advance_map_script_sheet import recount  # noqa: E402
from ggen_advance_painted_glyph_identity import FONT12_RELOCATED, load_galmuri12, packed_12x12  # noqa: E402
from ggen_advance_project_paths import (  # noqa: E402
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
import patch_ggen_advance_ashi_kagari_idcmd_20260910 as ashi_mod  # noqa: E402
from patch_ggen_advance_ashi_kagari_idcmd_20260910 import patch_map_row_fresh  # noqa: E402
from patch_ggen_advance_intermission_text_consumers_20260904 import (  # noqa: E402
    gate,
    sha256,
    u32,
)
from patch_ggen_advance_kimi_jane_to_neo_20260904 import (  # noqa: E402
    update_payload_hash,
    update_translation_manifest,
)
from patch_ggen_advance_map_script_inline_poc import load_identified_12x12  # noqa: E402
from patch_ggen_advance_nimbus_exss4_20260910 import plan_visible  # noqa: E402

BATCH_ID = "extrabank-pending-ko-20260911"
IDENTITY_KEY = "extrabank_pending_ko_sha256"
REPORT_KIND = "ggen_advance_extrabank_pending_candidate_20260911"
KO_PATH = ROOT / "analysis" / "ggen_advance_extrabank_pending_ko_20260911.json"
SNAPSHOT = ROOT / "analysis" / "ggen_advance_translation_merged_20260911_extrabank_pending.json"
PARENT_ROM = (
    ROOT
    / "outputs"
    / "20260910_ggen_advance_nimbus_exss4"
    / "ggen_advance_nimbus_exss4_candidate_20260910.gba"
)
PARENT_SAV = PARENT_ROM.with_suffix(".sav")
PARENT_SHA = "8e83336954c7805b38ced77526e8e3c9c07cbf1aa5fe3e092ce2c5634c6da076"
OUT_DIR = ROOT / "outputs" / "20260911_ggen_advance_extrabank_pending"
OUTPUT = OUT_DIR / "ggen_advance_extrabank_pending_candidate_20260911.gba"
OUT_SAV = OUT_DIR / "ggen_advance_extrabank_pending_candidate_20260911.sav"
REPORT = ROOT / "analysis" / "ggen_advance_extrabank_pending_candidate_20260911.json"
MANIFEST = OUT_DIR / "manifest.json"
CAVE_START = 0x012B55A8
CAVE_END = 0x012BF000
MAP_BANK = (0x00F00000, 0x00FC0000)
EXTRA_BANK = (0x00FC0000, 0x00FD0000)
VISUAL_DIALOGUE_CELLS = 14
LIVE_LOOKUP_PTR_OFF = 0x01112588
LIVE_LOOKUP_PTR = 0x09360000
LIVE_LOOKUP_TABLE = 0x01360000
NOTES = (
    "Remaining Extra-session map scripts after the 20260910 Exss4 cluster. "
    "Blank 0x18 prints stay pending."
)


def mark_row(row: dict[str, Any], after: str, new_segments: list[str]) -> None:
    row["translation_ko"] = after
    row["translation_segments"] = new_segments
    row["translation_status"] = "translated"
    row["translation_source"] = "user_requested_batch"
    row["review_status"] = "user_verified"
    row["review_count"] = int(row.get("review_count") or 0) + 1
    row["reviewed_at"] = "2026-09-11"
    row["translator_notes"] = NOTES
    row["qa_status"] = "static_consumer_verified"
    row["overlay_batch_id"] = BATCH_ID
    update_payload_hash(row)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    apsaras_mod.CAVE_END = CAVE_END
    ashi_mod.LIVE_LOOKUP_TABLE = LIVE_LOOKUP_TABLE
    ashi_mod.LIVE_LOOKUP_PTR = LIVE_LOOKUP_PTR

    extra_ko: dict[str, list[str]] = json.loads(KO_PATH.read_text(encoding="utf-8"))
    for record_id, lines in extra_ko.items():
        for line in lines:
            gate("\n" not in line, f"newline in {record_id}: {line!r}")
            gate(len(line) <= VISUAL_DIALOGUE_CELLS, f"{record_id} {len(line)}>{VISUAL_DIALOGUE_CELLS}: {line!r}")

    original = ORIGINAL_ROM.read_bytes()
    current = PARENT_ROM.read_bytes()
    gate(len(current) == 32 * 1024 * 1024, "parent size drift")
    gate(sha256(current) == PARENT_SHA, "parent ROM hash drift")
    gate(u32(current, LIVE_LOOKUP_PTR_OFF) == LIVE_LOOKUP_PTR, "live lookup pointer drift")
    gate(all(value == 0 for value in current[CAVE_START:CAVE_END]), "pending cave is not zero-filled")
    gate(PARENT_SAV.exists(), "parent SAV missing")

    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    by_id = {str(row["record_id"]): row for row in merged["records"]}
    missing = sorted(set(extra_ko) - set(by_id))
    gate(not missing, f"extra KO ids missing {missing[:8]}")

    planned: list[tuple[str, dict[str, Any], str, list[str], list[str]]] = []
    hangul12: set[str] = set()
    for record_id, lines in extra_ko.items():
        row = by_id[record_id]
        gate(str(row.get("translation_status")) == "pending", f"not pending {record_id}")
        before, old_segments, new_segments = plan_visible(row, lines)
        hangul12.update(hangul_chars("\n".join(lines)))
        planned.append((record_id, row, before, old_segments, new_segments))

    identified = load_identified_12x12()
    verified12 = unified.load_verified_charmap(unified.CHARMAP_12X12_PATH)
    font12 = load_galmuri12()
    _live8, live12 = unified.collect_live_slots(original, merged["records"])
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

    cave_cursor = CAVE_START
    evidence: list[dict[str, Any]] = []
    for record_id, row, before, old_segments, new_segments in planned:
        after = "\n".join(visible_segments(new_segments))
        mark_row(row, after, new_segments)
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
        evidence.append(
            {
                "record_id": record_id,
                "kind": "fresh",
                "before": before,
                "after": after,
                "segments": written,
            }
        )

    leftover_text = [
        str(row["record_id"])
        for row in merged["records"]
        if str(row.get("record_id") or "").startswith("GGA-MAPSCRIPT-00FC")
        and row.get("translation_status") == "pending"
        and str(row.get("source_text") or "").strip()
    ]
    leftover_blank = [
        str(row["record_id"])
        for row in merged["records"]
        if str(row.get("record_id") or "").startswith("GGA-MAPSCRIPT-00FC")
        and row.get("translation_status") == "pending"
        and not str(row.get("source_text") or "").strip()
    ]
    gate(not leftover_text, f"pending extra text leftover {leftover_text[:8]}")
    gate(len(leftover_blank) == 12, f"blank leftover drift {len(leftover_blank)}")
    for record_id, lines in extra_ko.items():
        gate(str(by_id[record_id].get("translation_ko")) == "\n".join(lines), f"extra KO drift {record_id}")

    changed = [index for index, (before, after) in enumerate(zip(current, candidate)) if before != after]
    gate(set(changed) <= allowed, f"unexpected ROM byte change x{len(set(changed) - allowed)}")
    gate(bytes(candidate[MAP_BANK[0] : MAP_BANK[1]]) == current[MAP_BANK[0] : MAP_BANK[1]], "old map-script bank changed")
    gate(bytes(candidate[EXTRA_BANK[0] : EXTRA_BANK[1]]) == current[EXTRA_BANK[0] : EXTRA_BANK[1]], "extra map-script bank changed")
    gate(sha256(PARENT_ROM.read_bytes()) == sha256(current), "parent ROM mutated during patch")
    gate(cave_cursor <= CAVE_END, "pending cave overflow")

    recount(merged)
    parent_identity = str(merged.get("identity", {}).get("translation_overlay_identity_sha256") or "")
    new_identity = digest(
        {
            "parent": parent_identity,
            "batch_id": BATCH_ID,
            "extra": sorted(extra_ko),
            "ko_sha256": sha256(KO_PATH.read_bytes()),
        }
    )
    identity = merged.setdefault("identity", {})
    identity["parent_translation_overlay_identity_sha256"] = parent_identity
    identity[IDENTITY_KEY] = new_identity
    identity["translation_overlay_identity_sha256"] = new_identity
    status_counts = dict(sorted(Counter(str(row.get("translation_status") or "") for row in merged["records"]).items()))
    summary = merged.setdefault("summary", {})
    summary["merged_translation_status_counts"] = status_counts
    merged.setdefault("inputs", {})["map_script_extrabank_pending_20260911"] = {
        "file": KO_PATH.name,
        "file_sha256": sha256(KO_PATH.read_bytes()),
        "record_count": len(extra_ko),
        "blank_left_pending": leftover_blank,
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(bytes(candidate))
    shutil.copy2(PARENT_SAV, OUT_SAV)
    SNAPSHOT.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    TRANSLATION_MERGED_JSON.write_bytes(SNAPSHOT.read_bytes())
    update_translation_manifest(merged, SNAPSHOT)
    report = {
        "schema_version": 1,
        "kind": REPORT_KIND,
        "result": "PASS",
        "batch_id": BATCH_ID,
        "parent": {"path": advance_relative(PARENT_ROM), "sha256": PARENT_SHA},
        "translated": len(extra_ko),
        "blank_left_pending": leftover_blank,
        "painted_glyphs": painted,
        "cave": {"start": hex(CAVE_START), "end": hex(cave_cursor), "capacity_end": hex(CAVE_END)},
        "changed_records": len(evidence),
        "jobs": evidence,
        "diff": {"changed_byte_count": len(changed), "unexpected_changed_bytes": 0},
        "output": {
            "path": advance_relative(OUTPUT),
            "sha256": sha256(bytes(candidate)),
            "size": len(candidate),
            "sav": advance_relative(OUT_SAV),
        },
        "verification": {
            "result": "PASS",
            "extra_bank_unmodified": True,
            "blank_prints_unpatched": True,
        },
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    MANIFEST.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "result": "PASS",
                "translated": len(extra_ko),
                "blank_pending": len(leftover_blank),
                "painted": len(painted),
                "rom": advance_relative(OUTPUT),
                "sha256": report["output"]["sha256"],
                "changed_bytes": len(changed),
                "cave_used": cave_cursor - CAVE_START,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
