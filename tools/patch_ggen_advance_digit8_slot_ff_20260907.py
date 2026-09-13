#!/usr/bin/env python3
"""Retarget 12x12 Korean digit 8 from slot 0x00FE (glyph 7) to 0x00FF (glyph 8).

The identified 12x12 charmap labeled both 0x00FE and 0x00FF as "8".  Lowest-slot
encoding therefore emitted E01E, which draws the 7 glyph.  8x16 digit 8 (0x00E7)
and Japanese map-bank 7s (also E01E) are left untouched.
"""
from __future__ import annotations

import json
import shutil
import struct
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import build_ggen_advance_unified_rom_poc as unified  # noqa: E402
from ggen_advance_project_paths import (  # noqa: E402
    MAIN_TIP_MANIFEST,
    MAIN_TIP_ROM,
    ORIGINAL_ROM,
    TRANSLATION_MERGED_JSON,
    advance_relative,
)
from ggen_advance_text_codec import encode_tokens, read_tokens  # noqa: E402
from patch_ggen_advance_intermission_text_consumers_20260904 import gate, sha256, u32  # noqa: E402

BATCH_ID = "digit8-slot-ff-20260907"
CHARMAP = ROOT / "analysis" / "ggen_advance_12x12_identified_charmap_20260828.json"
OUT_DIR = ROOT / "outputs" / "20260907_ggen_advance_digit8_slot_ff"
OUTPUT = OUT_DIR / "ggen_advance_digit8_slot_ff_candidate_20260907.gba"
OUT_SAV = OUT_DIR / "ggen_advance_digit8_slot_ff_candidate_20260907.sav"
MAIN_SAV = ROOT / "SD Gundam GGeneration Advance (Korean).sav"
REPORT = ROOT / "analysis" / "ggen_advance_digit8_slot_ff_candidate_20260907.json"
MANIFEST = OUT_DIR / "manifest.json"
ROM_BASE = 0x08000000
MAP_BANK = (0x00F00000, 0x00FC0000)
WRONG_TOKEN = 0xE01E  # slot 0x00FE, 12x12 glyph 7
RIGHT_TOKEN = 0xE01F  # slot 0x00FF, 12x12 glyph 8
AMADA_INTRO = "GGA-MAPSCRIPT-00F717A7"
AMADA_SECOND_ORIG = 0x08F717BA
EZ8_8X16 = "GGA-TEXT-0017A023"


def iter_lookup_run(rom: bytes, pos: int) -> list[tuple[int, int, int, int]]:
    def valid(orig: int, neu: int, orig_end: int) -> bool:
        return (
            0x08F00000 <= orig < 0x08FC0000
            and 0x09000000 <= neu < 0x0A000000
            and orig <= orig_end <= orig + 96
        )

    while pos >= 12:
        orig, neu, orig_end = struct.unpack_from("<III", rom, pos - 12)
        if not valid(orig, neu, orig_end):
            break
        pos -= 12
    entries: list[tuple[int, int, int, int]] = []
    cursor = pos
    while cursor + 12 <= len(rom):
        orig, neu, orig_end = struct.unpack_from("<III", rom, cursor)
        if not valid(orig, neu, orig_end):
            break
        entries.append((cursor, orig, neu, orig_end))
        cursor += 12
    return entries


def load_lookup_entries(rom: bytes) -> list[tuple[int, int, int, int]]:
    key = struct.pack("<I", AMADA_SECOND_ORIG)
    runs: list[list[tuple[int, int, int, int]]] = []
    seen_starts: set[int] = set()
    cursor = 0
    while True:
        hit = rom.find(key, cursor)
        if hit < 0:
            break
        if hit % 4 == 0 and hit + 12 <= len(rom):
            orig, neu, orig_end = struct.unpack_from("<III", rom, hit)
            if orig == AMADA_SECOND_ORIG and 0x09000000 <= neu < 0x0A000000:
                run = iter_lookup_run(rom, hit)
                if run and run[0][0] not in seen_starts:
                    seen_starts.add(run[0][0])
                    runs.append(run)
        cursor = hit + 1
    gate(runs, "map-script lookup table not found")
    merged: dict[int, tuple[int, int, int, int]] = {}
    for run in runs:
        gate(len(run) >= 20000, f"lookup run too small: {len(run)} at 0x{run[0][0]:08X}")
        for entry in run:
            merged[entry[2]] = entry
    return list(merged.values())


def rewrite_stream(buf: bytearray, file_off: int, allowed: set[int]) -> int:
    try:
        tokens, raw = read_tokens(buf, file_off, limit=256)
    except ValueError:
        return 0
    hits = sum(1 for token in tokens if token == WRONG_TOKEN)
    if hits == 0:
        return 0
    encoded = encode_tokens([RIGHT_TOKEN if token == WRONG_TOKEN else token for token in tokens])
    gate(len(encoded) == len(raw), f"token rewrite size drift at 0x{file_off:08X}")
    buf[file_off : file_off + len(encoded)] = encoded
    allowed.update(range(file_off, file_off + len(encoded)))
    return hits


def owner_u32_offsets(row: dict[str, Any]) -> list[int]:
    return [
        int(str(owner).removeprefix("OWNER-U32-"), 16)
        for owner in row.get("owner_ids") or []
        if str(owner).startswith("OWNER-U32-")
    ]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    original = ORIGINAL_ROM.read_bytes()
    current = MAIN_TIP_ROM.read_bytes()
    main_manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(len(current) == 32 * 1024 * 1024, "main TIP size drift")
    gate(sha256(current) == main_manifest.get("sha256"), "main TIP/manifest hash drift")
    gate(MAIN_SAV.exists(), "current main SAV missing")

    payload = json.loads(CHARMAP.read_text(encoding="utf-8"))
    gate(payload["verified_charmap"].get("0x00FE") == "7", "charmap 0x00FE was not promoted to 7")
    gate(payload["verified_charmap"].get("0x00FF") == "8", "charmap 0x00FF is not 8")
    verified = unified.load_verified_charmap(CHARMAP)
    gate(verified.get("8") == 0x00FF, f"encoder still picks wrong 8 slot {verified.get('8')!r}")
    gate(verified.get("7") == 0x00FE, f"encoder 7 slot drift {verified.get('7')!r}")

    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    by_id = {row["record_id"]: row for row in merged["records"]}
    intro = by_id[AMADA_INTRO]
    gate("제08MS소대" in str(intro.get("translation_ko") or ""), "Amada intro sheet lost 08")
    gate("第08MS小隊" in str(intro.get("source_text") or ""), "Amada intro source lost 08")

    candidate = bytearray(current)
    allowed: set[int] = set()
    lookup = load_lookup_entries(current)
    map_streams = 0
    map_tokens = 0
    for _pos, orig, neu, _orig_end in lookup:
        file_off = neu - ROM_BASE
        hits = rewrite_stream(candidate, file_off, allowed)
        if hits:
            map_streams += 1
            map_tokens += hits

    u32_records = 0
    u32_tokens = 0
    for row in merged["records"]:
        if row.get("scope_status") != "included" or row.get("translation_status") != "translated":
            continue
        if not unified.uses_12x12(row):
            continue
        for owner in owner_u32_offsets(row):
            addr = u32(current, owner)
            file_off = addr - ROM_BASE
            if not (0 <= file_off < len(current)):
                continue
            hits = rewrite_stream(candidate, file_off, allowed)
            if hits:
                u32_records += 1
                u32_tokens += hits
            if row.get("source_scope") not in {"scenario_main", "scenario_dynamic"}:
                continue
            segments = list(row.get("translation_segments") or [])
            if len(segments) <= 1:
                continue
            cursor = file_off
            for _ in range(len(segments) - 1):
                try:
                    _tokens, raw = read_tokens(candidate, cursor, limit=256)
                except ValueError:
                    break
                cursor += len(raw)
                while cursor < len(candidate) and candidate[cursor] in {0x01, 0x18}:
                    cursor += 1
                if cursor >= len(candidate) or candidate[cursor] == 0:
                    break
                extra = rewrite_stream(candidate, cursor, allowed)
                if extra:
                    u32_tokens += extra
                    u32_records += 1

    gate(map_tokens > 0, "no 12x12 map-script digit-8 tokens found")
    changed = [index for index, (before, after) in enumerate(zip(current, candidate)) if before != after]
    gate(set(changed) <= allowed, f"unexpected ROM byte change x{len(set(changed) - allowed)}")
    gate(bytes(candidate[MAP_BANK[0] : MAP_BANK[1]]) == current[MAP_BANK[0] : MAP_BANK[1]], "map-script bank changed")
    gate(original[MAP_BANK[0] : MAP_BANK[1]] == bytes(candidate[MAP_BANK[0] : MAP_BANK[1]]), "map-script bank drifted from JP")
    amada_hits = [entry for entry in lookup if entry[1] == AMADA_SECOND_ORIG]
    gate(len(amada_hits) == 1, f"Amada intro lookup drift {len(amada_hits)}")
    _pos, _orig, neu, _end = amada_hits[0]
    tokens, raw = read_tokens(candidate, neu - ROM_BASE)
    gate(WRONG_TOKEN not in tokens, "Amada intro still encodes 8 as 0x00FE")
    gate(RIGHT_TOKEN in tokens, "Amada intro lost slot 0x00FF")
    parent_raw = bytes(current[neu - ROM_BASE : neu - ROM_BASE + len(raw)])
    gate(parent_raw != raw, "Amada intro payload was not rewritten")
    gate(parent_raw.replace(bytes.fromhex("E01E"), bytes.fromhex("E01F")) == raw, "Amada intro rewrite is not FE→FF")

    ez8 = by_id[EZ8_8X16]
    gate(not unified.uses_12x12(ez8), "Ez8 record classified as 12x12")
    ez8_owners = owner_u32_offsets(ez8)
    gate(ez8_owners, "Ez8 missing U32 owner")
    ez8_addr = u32(candidate, ez8_owners[0])
    ez8_tokens, _ez8_raw = read_tokens(candidate, ez8_addr - ROM_BASE)
    ez8_parent_tokens, _ = read_tokens(current, u32(current, ez8_owners[0]) - ROM_BASE)
    gate(ez8_tokens == ez8_parent_tokens, "8x16 Ez8 payload mutated")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(bytes(candidate))
    shutil.copy2(MAIN_SAV, OUT_SAV)
    report = {
        "result": "PASS",
        "batch_id": BATCH_ID,
        "charmap": {
            "path": advance_relative(CHARMAP),
            "slot_0x00FE": "7",
            "slot_0x00FF": "8",
            "encoder_8": hex(verified["8"]),
            "encoder_7": hex(verified["7"]),
        },
        "lookup_entries": len(lookup),
        "rewritten": {
            "map_script_streams": map_streams,
            "map_script_tokens": map_tokens,
            "u32_12x12_records": u32_records,
            "u32_12x12_tokens": u32_tokens,
            "rom_bytes": len(changed),
        },
        "amada_intro": {
            "record_id": AMADA_INTRO,
            "source_text": intro.get("source_text"),
            "translation_ko": intro.get("translation_ko"),
            "payload": hex(neu),
            "tokens": [hex(token) for token in tokens],
        },
        "parent": {"path": advance_relative(MAIN_TIP_ROM), "sha256": sha256(current)},
        "output": {"path": advance_relative(OUTPUT), "sha256": sha256(candidate), "size": len(candidate)},
        "translation_source": {
            "path": advance_relative(TRANSLATION_MERGED_JSON),
            "sha256": sha256(TRANSLATION_MERGED_JSON.read_bytes()),
        },
        "verification": {
            "result": "PASS",
            "original_map_script_bank_unchanged": True,
            "amada_intro_uses_slot_00FF": True,
            "ez8_8x16_unchanged": True,
            "encoder_lowest_8_is_00FF": True,
            "runtime_emulator": "not run; static ROM token/glyph verification only",
        },
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    MANIFEST.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {key: report[key] for key in ("result", "charmap", "rewritten", "amada_intro", "output", "verification")},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
