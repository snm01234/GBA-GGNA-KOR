#!/usr/bin/env python3
"""Fix Extra-session shout mistranslations, 캄라→카무라, and missing 0x11 prints."""
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
import extract_ggen_advance_map_script_dialogue as extract_mod  # noqa: E402
import patch_ggen_advance_apsaras_zentetsu_20260908 as apsaras_mod  # noqa: E402
from analyze_ggen_advance_pending_decode import CORRECTED_LOW_KANA, load_map  # noqa: E402
from build_ggen_advance_map_script_sheet import build_record, recount  # noqa: E402
from ggen_advance_painted_glyph_identity import FONT12_RELOCATED, load_galmuri12, packed_12x12  # noqa: E402
from ggen_advance_project_paths import (  # noqa: E402
    ORIGINAL_ROM,
    TRANSLATION_MERGED_JSON,
    advance_relative,
)
from ggen_advance_text_codec import DICT_12X12_BASE, DICT_12X12_END, load_dictionary  # noqa: E402
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
from patch_ggen_advance_intermission_text_consumers_20260904 import gate, sha256, u32  # noqa: E402
from patch_ggen_advance_kimi_jane_to_neo_20260904 import (  # noqa: E402
    update_payload_hash,
    update_translation_manifest,
)
from patch_ggen_advance_map_script_inline_poc import load_identified_12x12  # noqa: E402
from patch_ggen_advance_name_unify_20260909 import patch_map_row_live  # noqa: E402
from patch_ggen_advance_nimbus_exss4_20260910 import plan_visible  # noqa: E402

BATCH_ID = "kamura-shout-setup11-20260911"
IDENTITY_KEY = "kamura_shout_setup11_sha256"
REPORT_KIND = "ggen_advance_kamura_shout_setup11_candidate_20260911"
SNAPSHOT = ROOT / "analysis" / "ggen_advance_translation_merged_20260911_kamura_shout.json"
PARENT_ROM = (
    ROOT
    / "outputs"
    / "20260911_ggen_advance_extrabank_pending"
    / "ggen_advance_extrabank_pending_candidate_20260911.gba"
)
PARENT_SAV = PARENT_ROM.with_suffix(".sav")
PARENT_SHA = "d967f61e9628d2a082458fce7f1afbd74d961dc0bfff6220712961e5a5bb0ec0"
OUT_DIR = ROOT / "outputs" / "20260911_ggen_advance_kamura_shout"
OUTPUT = OUT_DIR / "ggen_advance_kamura_shout_candidate_20260911.gba"
OUT_SAV = OUT_DIR / "ggen_advance_kamura_shout_candidate_20260911.sav"
REPORT = ROOT / "analysis" / "ggen_advance_kamura_shout_candidate_20260911.json"
MANIFEST = OUT_DIR / "manifest.json"
CAVE_START = 0x012BB334
CAVE_END = 0x012BF000
MAP_BANK = (0x00F00000, 0x00FC0000)
EXTRA_BANK = (0x00FC0000, 0x00FD0000)
VISUAL_DIALOGUE_CELLS = 14
LIVE_LOOKUP_PTR_OFF = 0x01112588
LIVE_LOOKUP_PTR = 0x09360000
LIVE_LOOKUP_TABLE = 0x01360000
NOTES = (
    "カムラ→카무라. Setup 0x11 print 流派、東方不敗はぁっ was omitted. "
    "全新系列 not 完全勝利; 天破侠乱 not 天破活乱; elongated はぁっ → 느은."
)
LIVE_KO: dict[str, list[str]] = {
    "GGA-MAPSCRIPT-00FC0B93": ["카무라 대위도 참", "무리하긴……"],
    "GGA-MAPSCRIPT-00FC0FEF": ["카무라 대위……"],
    "GGA-MAPSCRIPT-00FC1084": ["……카무라 대위？"],
    "GGA-MAPSCRIPT-00FC17DF": ["전신계열！！"],
    "GGA-MAPSCRIPT-00FC180E": ["처, 천파협란！！"],
    "GGA-MAPSCRIPT-00FC1829": ["……보아라！！", "동방불패느은！？"],
    "GGA-MAPSCRIPT-00FC1846": ["아아아 붉게,", "타오르고 이이잇！！"],
}
FRESH_KO: dict[str, list[str]] = {
    "GGA-MAPSCRIPT-00FC17A2": ["유파 동방불패느은！？"],
    "GGA-MAPSCRIPT-00FCB636": ["이건……！"],
}
FRESH_OPCODES = {
    "GGA-MAPSCRIPT-00FC17A2": 0x00FC17A1,
    "GGA-MAPSCRIPT-00FCB636": 0x00FCB635,
}


def mark_row(row: dict[str, Any], after: str, new_segments: list[str]) -> None:
    row["translation_ko"] = after
    row["translation_segments"] = new_segments
    row["translation_status"] = "translated"
    row["translation_source"] = "user_verified"
    row["review_status"] = "user_verified"
    row["review_count"] = int(row.get("review_count") or 0) + 1
    row["reviewed_at"] = "2026-09-11"
    row["translator_notes"] = NOTES
    row["qa_status"] = "static_consumer_verified"
    row["overlay_batch_id"] = BATCH_ID
    update_payload_hash(row)


def extract_fresh_row(japan: bytes, opcode_18: int, mapping: dict[int, str], dictionary: list[list[int]]) -> dict[str, Any]:
    extract_mod.BANK_END = 0x00FD0000
    parsed, _cursor = extract_mod.parse_print(japan, opcode_18, dictionary, mapping)
    speaker = extract_mod.recent_speaker(japan, opcode_18)
    parsed["record_id"] = f"GGA-MAPSCRIPT-{opcode_18 + 1:08X}"
    parsed["print_setup"] = "0x0011"
    parsed["chained_box"] = False
    parsed["speaker_id"] = f"0x{speaker:04X}" if speaker is not None else ""
    return parsed


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    apsaras_mod.CAVE_END = CAVE_END
    ashi_mod.LIVE_LOOKUP_TABLE = LIVE_LOOKUP_TABLE
    ashi_mod.LIVE_LOOKUP_PTR = LIVE_LOOKUP_PTR
    for table in (LIVE_KO, FRESH_KO):
        for record_id, lines in table.items():
            for line in lines:
                gate("\n" not in line, f"newline {record_id}")
                gate(len(line) <= VISUAL_DIALOGUE_CELLS, f"{record_id} {len(line)}>{VISUAL_DIALOGUE_CELLS}: {line!r}")

    original = ORIGINAL_ROM.read_bytes()
    current = PARENT_ROM.read_bytes()
    gate(len(current) == 32 * 1024 * 1024, "parent size drift")
    gate(sha256(current) == PARENT_SHA, "parent ROM hash drift")
    gate(u32(current, LIVE_LOOKUP_PTR_OFF) == LIVE_LOOKUP_PTR, "live lookup pointer drift")
    gate(all(value == 0 for value in current[CAVE_START:CAVE_END]), "shout cave is not zero-filled")
    gate(PARENT_SAV.exists(), "parent SAV missing")

    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    mapping = load_map(ROOT / "analysis/ggen_advance_12x12_identified_charmap_20260828.json")
    mapping.update(CORRECTED_LOW_KANA)
    dictionary = load_dictionary(original, DICT_12X12_BASE, DICT_12X12_END)
    rom_sha = str(merged["source"]["sha256"]).lower()
    existing_ids = {str(row["record_id"]) for row in merged["records"]}
    existing_owners = {str(owner["owner_id"]) for owner in merged["owners"]}
    new_records: list[dict[str, Any]] = []
    new_owners: list[dict[str, Any]] = []
    for record_id, opcode_18 in FRESH_OPCODES.items():
        parsed = extract_fresh_row(original, opcode_18, mapping, dictionary)
        gate(parsed["record_id"] == record_id, f"fresh id drift {parsed['record_id']}")
        record, owner = build_record(parsed, rom_sha)
        gate(record["record_id"] not in existing_ids, f"duplicate {record_id}")
        gate(owner["owner_id"] not in existing_owners, f"owner collision {owner['owner_id']}")
        existing_ids.add(record["record_id"])
        existing_owners.add(owner["owner_id"])
        new_records.append(record)
        new_owners.append(owner)
    merged["records"].extend(new_records)
    merged["owners"].extend(new_owners)
    recount(merged)
    by_id = {str(row["record_id"]): row for row in merged["records"]}

    planned_live: list[tuple[str, dict[str, Any], str, list[str], list[str]]] = []
    planned_fresh: list[tuple[str, dict[str, Any], str, list[str], list[str]]] = []
    hangul12: set[str] = set()
    for record_id, lines in LIVE_KO.items():
        row = by_id[record_id]
        before, old_segments, new_segments = plan_visible(row, lines)
        hangul12.update(hangul_chars(before))
        hangul12.update(hangul_chars("\n".join(lines)))
        planned_live.append((record_id, row, before, old_segments, new_segments))
    for record_id, lines in FRESH_KO.items():
        row = by_id[record_id]
        before, old_segments, new_segments = plan_visible(row, lines)
        hangul12.update(hangul_chars("\n".join(lines)))
        planned_fresh.append((record_id, row, before, old_segments, new_segments))

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
    counts: Counter[str] = Counter()
    for record_id, row, before, old_segments, new_segments in planned_live:
        after = "\n".join(visible_segments(new_segments))
        mark_row(row, after, new_segments)
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
        counts["map_live"] += 1
        evidence.append({"record_id": record_id, "kind": "live", "before": before, "after": after, "segments": written})
    for record_id, row, before, old_segments, new_segments in planned_fresh:
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
        counts["map_fresh"] += 1
        evidence.append({"record_id": record_id, "kind": "fresh", "before": before, "after": after, "segments": written})

    leftover = [
        str(row["record_id"])
        for row in merged["records"]
        if "캄라" in str(row.get("translation_ko") or "")
    ]
    gate(not leftover, f"캄라 leftover {leftover}")
    gate("전신계열" in str(by_id["GGA-MAPSCRIPT-00FC17DF"].get("translation_ko")), "series line drift")
    gate("천파협란" in str(by_id["GGA-MAPSCRIPT-00FC180E"].get("translation_ko")), "tenpa line drift")
    gate("동방불패느은" in str(by_id["GGA-MAPSCRIPT-00FC1829"].get("translation_ko")), "fuhai line drift")
    gate("유파 동방불패느은" in str(by_id["GGA-MAPSCRIPT-00FC17A2"].get("translation_ko")), "setup11 line drift")

    changed = [index for index, (before, after) in enumerate(zip(current, candidate)) if before != after]
    gate(set(changed) <= allowed, f"unexpected ROM byte change x{len(set(changed) - allowed)}")
    gate(bytes(candidate[MAP_BANK[0] : MAP_BANK[1]]) == current[MAP_BANK[0] : MAP_BANK[1]], "old map-script bank changed")
    gate(bytes(candidate[EXTRA_BANK[0] : EXTRA_BANK[1]]) == current[EXTRA_BANK[0] : EXTRA_BANK[1]], "extra map-script bank changed")
    gate(sha256(PARENT_ROM.read_bytes()) == sha256(current), "parent ROM mutated during patch")
    gate(cave_cursor <= CAVE_END, "shout cave overflow")

    recount(merged)
    parent_identity = str(merged.get("identity", {}).get("translation_overlay_identity_sha256") or "")
    new_identity = digest({"parent": parent_identity, "batch_id": BATCH_ID, "live": sorted(LIVE_KO), "fresh": sorted(FRESH_KO)})
    identity = merged.setdefault("identity", {})
    identity["parent_translation_overlay_identity_sha256"] = parent_identity
    identity[IDENTITY_KEY] = new_identity
    identity["translation_overlay_identity_sha256"] = new_identity
    status_counts = dict(sorted(Counter(str(row.get("translation_status") or "") for row in merged["records"]).items()))
    merged.setdefault("summary", {})["merged_translation_status_counts"] = status_counts

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
        "painted_glyphs": painted,
        "cave": {"start": hex(CAVE_START), "end": hex(cave_cursor), "capacity_end": hex(CAVE_END)},
        "counts": dict(counts),
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
            "kamura_not_kamra": True,
            "setup11_in_sheet": True,
            "extra_bank_unmodified": True,
        },
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    MANIFEST.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "result": "PASS",
                "live": len(LIVE_KO),
                "fresh": len(FRESH_KO),
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
