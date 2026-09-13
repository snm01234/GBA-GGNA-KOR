#!/usr/bin/env python3
"""Paraphrase three 報い map lines as revenge; keep Woody 出撃."""
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
import patch_ggen_advance_pending_readable_batch_20260907 as prev  # noqa: E402
from ggen_advance_painted_glyph_identity import (  # noqa: E402
    FONT12_RELOCATED,
    load_galmuri12,
    packed_12x12,
    recover_unique_12x12_slots,
    slot_raw,
)
from ggen_advance_project_paths import (  # noqa: E402
    MAIN_TIP_MANIFEST,
    MAIN_TIP_ROM,
    ORIGINAL_ROM,
    TRANSLATION_MERGED_JSON,
    advance_relative,
)
from merge_ggen_advance_translation_overlays import digest  # noqa: E402
from patch_ggen_advance_intermission_text_consumers_20260904 import gate, sha256  # noqa: E402
from patch_ggen_advance_kimi_jane_to_neo_20260904 import (  # noqa: E402
    find_lookup,
    payload_until_nul,
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

BATCH_ID = "mukui-revenge-paraphrase-20260907"
CHARMAP = ROOT / "analysis" / "ggen_advance_12x12_identified_charmap_20260828.json"
SNAPSHOT = ROOT / "analysis" / "ggen_advance_translation_merged_20260907_mukui_revenge.json"
OUT_DIR = ROOT / "outputs" / "20260907_ggen_advance_mukui_revenge"
OUTPUT = OUT_DIR / "ggen_advance_mukui_revenge_candidate_20260907.gba"
OUT_SAV = OUT_DIR / "ggen_advance_mukui_revenge_candidate_20260907.sav"
MAIN_SAV = ROOT / "SD Gundam GGeneration Advance (Korean).sav"
REPORT = ROOT / "analysis" / "ggen_advance_mukui_revenge_candidate_20260907.json"
MANIFEST = OUT_DIR / "manifest.json"
CAVE_START = 0x012B1800
CAVE_END = 0x012BF000
MAP_BANK = (0x00F00000, 0x00FC0000)
WOODY_KEEP = "GGA-MAPSCRIPT-00F6D808"

JOBS: dict[str, dict[str, Any]] = {
    "GGA-MAPSCRIPT-00F6CA52": {
        "source_text": "くそっ！\\nオルテガの報い合戦だ！！",
        "segments_jp": ["くそっ！", "オルテガの報い合戦だ！！"],
        "segments_ko": ["제기랄!", "오르테가의 복수전이다!!"],
        "notes": "0x04FD=報 leftover 報い合戦/報いだ. 복수전 의역. 우디 出撃 유지",
    },
    "GGA-MAPSCRIPT-00F71BC5": {
        "source_text": "……オルテガよ\\nマッシュの報い合戦だ",
        "segments_jp": ["……オルテガよ", "マッシュの報い合戦だ"],
        "segments_ko": ["……오르테가야", "마슈의 복수전이다"],
        "notes": "0x04FD=報 leftover 報い合戦. 마슈의 복수전 의역",
    },
    "GGA-MAPSCRIPT-00F9BE72": {
        "source_text": "ララァ・スンの報いだ\\n……戦えるな、シャア？",
        "segments_jp": ["ララァ・スンの報いだ", "……戦えるな、シャア？"],
        "segments_ko": ["이게 라라아 슨의 복수다", "……싸울 수 있겠나, 샤아?"],
        "notes": "0x04FD=報 leftover 報いだ. 라라아 복수 의역",
    },
}


def write_payload(
    candidate: bytearray,
    address: int,
    encoded: bytes,
    old_size: int,
    allowed: set[int],
    cursor: int,
) -> tuple[int, int]:
    gate(encoded.endswith(b"\x00"), "encoded map payload missing NUL")
    if len(encoded) <= old_size:
        start = address - ROM_BASE
        candidate[start : start + len(encoded)] = encoded
        if len(encoded) < old_size:
            candidate[start + len(encoded) : start + old_size] = b"\x00" * (old_size - len(encoded))
        allowed.update(range(start, start + old_size))
        return address, cursor
    cursor = (cursor + 15) & ~15
    gate(cursor + len(encoded) <= CAVE_END, "mukui revenge cave overflow")
    candidate[cursor : cursor + len(encoded)] = encoded
    allowed.update(range(cursor, cursor + len(encoded)))
    return ROM_BASE + cursor, cursor + len(encoded)


def promote_charmap() -> None:
    payload = json.loads(CHARMAP.read_text(encoding="utf-8"))
    verified = dict(payload["verified_charmap"])
    current = verified.get("0x04FD")
    gate(current in {"殴", "報"}, f"unexpected 0x04FD value {current!r}")
    verified["0x04FD"] = "報"
    payload["verified_charmap"] = {key: verified[key] for key in sorted(verified, key=lambda value: int(value, 16))}
    provenance = payload.setdefault("added_mukui_revenge_20260907", {})
    provenance["0x04FD"] = {
        "from": current,
        "to": "報",
        "basis": "12x12 leftover frames オルテガ/マッシュの報い合戦 and ララァ・スンの報いだ; 殴 is 0x0194",
    }
    CHARMAP.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    prev.BATCH_ID = BATCH_ID
    original = ORIGINAL_ROM.read_bytes()
    current = MAIN_TIP_ROM.read_bytes()
    main_manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(len(current) == 32 * 1024 * 1024, "main TIP size drift")
    gate(sha256(current) == main_manifest.get("sha256"), "main TIP/manifest hash drift")
    gate(all(value == 0 for value in current[CAVE_START:CAVE_END]), "next cave is not zero-filled")
    gate(MAIN_SAV.exists(), "current main SAV missing")

    promote_charmap()
    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    by_id = {row["record_id"]: row for row in merged["records"]}
    woody = by_id[WOODY_KEEP]
    gate("출격" in str(woody.get("translation_ko") or ""), "Woody 출격 disappeared")
    gate("出撃" in str(woody.get("source_text") or ""), "Woody 出撃 source drift")

    hangul: set[str] = set()
    for record_id, job in JOBS.items():
        row = by_id[record_id]
        for text in list(row.get("translation_segments") or []) + list(job["segments_ko"]):
            hangul.update(char for char in str(text) if "가" <= char <= "힣")
    font12 = load_galmuri12()
    live12, _live8 = unified.collect_live_slots(original, merged["records"])
    candidate = bytearray(current)
    allowed: set[int] = set()
    occupied: set[int] = set()
    recovered: dict[str, int] = {}
    painted: list[dict[str, str]] = []
    for char in sorted(hangul):
        slot = prev.try_recover(recover_unique_12x12_slots, candidate, font12, char)
        if slot is None:
            slot = prev.choose_free_12x12(candidate, original, live12, occupied)
            start = prev.paint_12x12(candidate, slot, char, font12)
            allowed.update(range(start, start + fontops.FONT_12X12_STRIDE))
            painted.append({"char": char, "slot": f"0x{slot:04X}"})
            live12.add(slot)
        occupied.add(slot)
        recovered[char] = slot
        gate(
            slot_raw(candidate, FONT12_RELOCATED, slot, fontops.FONT_12X12_STRIDE) == packed_12x12(char, font12),
            f"12x12 painted glyph for {char!r} is not at 0x{slot:04X}",
        )
    identified = load_identified_12x12()
    cave_cursor = CAVE_START
    evidence: list[dict[str, Any]] = []

    for record_id, job in JOBS.items():
        row = by_id[record_id]
        gate(row.get("source_scope") == "scenario_map_script", f"scope drift {record_id}")
        old_segments = [str(item) for item in (row.get("translation_segments") or [])]
        new_segments = list(job["segments_ko"])
        gate(len(old_segments) == len(new_segments), f"segment count drift {record_id}")
        segments = list(row.get("segments") or [])
        gate(len(segments) == len(new_segments), f"map segment framing drift {record_id}")
        before = str(row.get("translation_ko") or "")
        after = "\n".join(new_segments)
        row["source_text"] = job["source_text"]
        for index, segment in enumerate(segments):
            segment["source_text"] = job["segments_jp"][index]
        row["translation_ko"] = after
        row["translation_segments"] = new_segments
        row["translation_status"] = "translated"
        row["translation_source"] = "user_verified"
        row["review_status"] = "user_verified"
        row["review_count"] = int(row.get("review_count") or 0) + 1
        row["reviewed_at"] = "2026-09-07"
        row["translator_notes"] = job["notes"]
        row["qa_status"] = "static_consumer_verified"
        row["overlay_batch_id"] = BATCH_ID
        update_payload_hash(row)

        cursor = int(str(row["target_file_offset"]), 16)
        first_new_addr: int | None = None
        first_old_end: int | None = None
        written: list[dict[str, Any]] = []
        for index, (segment, old_text, new_text) in enumerate(zip(segments, old_segments, new_segments)):
            original_bytes = raw_hex_bytes(str(segment.get("raw_hex") or ""))
            gate(original_bytes.endswith(b"\x00"), f"map segment missing NUL {record_id}")
            orig_addr = ROM_BASE + cursor
            orig_end = orig_addr + len(original_bytes) - 1
            lookup_pos, neu, table_end = find_lookup(current, orig_addr, orig_end)
            gate(table_end == orig_end, f"orig_end mismatch {record_id}")
            old_payload = payload_until_nul(current, neu)
            encoded_old, missing_old = encode_map_korean_line(old_text, recovered, identified)
            gate(
                encoded_old == old_payload and not missing_old,
                f"live encode mismatch {record_id}#{index}: "
                f"{None if encoded_old is None else encoded_old.hex()} vs {old_payload.hex()} missing={missing_old}",
            )
            gate("\n" not in new_text and len(new_text) <= MAX_DIALOGUE_CELLS, f"width {record_id}#{index} len={len(new_text)}")
            encoded_new, missing_new = encode_map_korean_line(new_text, recovered, identified)
            gate(encoded_new is not None and not missing_new, f"encode failed {record_id}: {missing_new}")
            new_addr, cave_cursor = write_payload(candidate, neu, encoded_new, len(old_payload), allowed, cave_cursor)
            if new_addr != neu:
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
                }
            )
            cursor += len(original_bytes)
        opcode_text = str(row.get("opcode_18_file_offset") or "")
        if opcode_text and first_new_addr is not None and first_old_end is not None:
            opcode_addr = ROM_BASE + int(opcode_text, 16)
            if opcode_addr != ROM_BASE + int(str(row["target_file_offset"]), 16):
                alias_pos, alias_neu, _alias_end = find_lookup(current, opcode_addr, first_old_end)
                if alias_neu != first_new_addr:
                    struct.pack_into("<I", candidate, alias_pos + 4, first_new_addr)
                    allowed.update(range(alias_pos + 4, alias_pos + 8))
        evidence.append({"record_id": record_id, "before": before, "after": after, "segments": written})

    changed = [index for index, (before, after) in enumerate(zip(current, candidate)) if before != after]
    gate(set(changed) <= allowed, f"unexpected ROM byte change x{len(set(changed) - allowed)}")
    gate(bytes(candidate[MAP_BANK[0] : MAP_BANK[1]]) == current[MAP_BANK[0] : MAP_BANK[1]], "original map-script bank changed")
    gate("출격" in str(by_id[WOODY_KEEP].get("translation_ko") or ""), "Woody 출격 was rewritten")

    parent_identity = str(merged.get("identity", {}).get("translation_overlay_identity_sha256") or "")
    new_identity = digest({"parent": parent_identity, "batch_id": BATCH_ID, "records": sorted(JOBS)})
    identity = merged.setdefault("identity", {})
    identity["parent_translation_overlay_identity_sha256"] = parent_identity
    identity["mukui_revenge_paraphrase_identity_sha256"] = new_identity
    identity["translation_overlay_identity_sha256"] = new_identity
    counts = dict(sorted(Counter(str(row.get("translation_status") or "") for row in merged["records"]).items()))
    summary = merged.setdefault("summary", {})
    summary["merged_translation_status_counts"] = counts
    summary["translation_overlay_identity_sha256"] = new_identity
    merged["mukui_revenge_paraphrase_20260907"] = {
        "batch_id": BATCH_ID,
        "changed_records": sorted(JOBS),
        "woody_kept": WOODY_KEEP,
        "slot_0x04FD": "報",
    }
    payload_json = json.dumps(merged, ensure_ascii=False, indent=2) + "\n"
    SNAPSHOT.write_text(payload_json, encoding="utf-8")
    TRANSLATION_MERGED_JSON.write_text(payload_json, encoding="utf-8")
    update_translation_manifest(merged, SNAPSHOT)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(bytes(candidate))
    shutil.copy2(MAIN_SAV, OUT_SAV)
    report = {
        "result": "PASS",
        "batch_id": BATCH_ID,
        "painted_glyphs": painted,
        "cave": {"start": hex(CAVE_START), "end": hex(cave_cursor), "capacity_end": hex(CAVE_END)},
        "woody_kept": {"record_id": WOODY_KEEP, "translation_ko": woody.get("translation_ko"), "source_text": woody.get("source_text")},
        "jobs": evidence,
        "parent": {"path": advance_relative(MAIN_TIP_ROM), "sha256": sha256(current)},
        "output": {"path": advance_relative(OUTPUT), "sha256": sha256(candidate), "size": len(candidate)},
        "translation_source": {"path": advance_relative(TRANSLATION_MERGED_JSON), "sha256": sha256(payload_json.encode("utf-8"))},
        "verification": {
            "result": "PASS",
            "original_map_script_bank_unchanged": True,
            "woody_shutsuugeki_kept": True,
            "dialogue_width_limit": MAX_DIALOGUE_CELLS,
            "runtime_emulator": "not run; static ROM verification only",
        },
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    MANIFEST.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {key: report[key] for key in ("result", "painted_glyphs", "cave", "woody_kept", "jobs", "output")},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
