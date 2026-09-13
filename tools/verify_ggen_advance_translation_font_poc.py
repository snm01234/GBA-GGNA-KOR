#!/usr/bin/env python3
"""Independently verify the font-enabled translation-display PoC."""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path
from typing import Any


ROM_BASE = 0x08000000
ORIGINAL_SIZE = 16 * 1024 * 1024
EXPANDED_SIZE = 32 * 1024 * 1024
FONT12_BASE = 0x0008AC40
FONT12_STRIDE = 18
FONT12_COUNT = 1992
FONT8_BASE = 0x00094028
FONT8_STRIDE = 32
FONT8_COUNT = 2068
FONT8_LITERAL_FILE = 0x00001350
FONT12_LITERAL_FILE = 0x00001388
STRONG_TAIL = 0x00FCED40
READY = {"translated", "translated_same", "translated_partial_charmap_preserved"}


def hx(value: str) -> int:
    return int(value, 16)


def raw(value: str) -> bytes:
    return bytes.fromhex(value.replace(" ", ""))


def u32(blob: bytes, offset: int) -> int:
    return struct.unpack_from("<I", blob, offset)[0]


def check(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("original", type=Path)
    ap.add_argument("candidate", type=Path)
    ap.add_argument("font_manifest", type=Path)
    ap.add_argument("translation_report", type=Path)
    args = ap.parse_args()

    original = args.original.read_bytes()
    candidate = args.candidate.read_bytes()
    manifest: dict[str, Any] = json.loads(args.font_manifest.read_text(encoding="utf-8"))
    report: dict[str, Any] = json.loads(args.translation_report.read_text(encoding="utf-8"))
    check(len(original) == ORIGINAL_SIZE, "original ROM size drift")
    check(len(candidate) == EXPANDED_SIZE, "font PoC size drift")
    check(sha(original) == report["source"]["sha256"], "original SHA mismatch")
    check(sha(candidate) == manifest["output"]["sha256"], "candidate SHA mismatch")

    font12 = manifest["fonts"]["12x12"]["allocation"]
    font8 = manifest["fonts"]["8x16"]["allocation"]
    f12_start, f12_end = hx(font12["file_offset"]), hx(font12["end_exclusive"])
    f8_start, f8_end = hx(font8["file_offset"]), hx(font8["end_exclusive"])
    check(f12_end - f12_start == FONT12_STRIDE * FONT12_COUNT, "12x12 allocation size mismatch")
    check(f8_end - f8_start == FONT8_STRIDE * FONT8_COUNT, "8x16 allocation size mismatch")
    check(sha(candidate[f12_start:f12_end]) == manifest["fonts"]["12x12"]["sha256"], "12x12 blob SHA mismatch")
    check(sha(candidate[f8_start:f8_end]) == manifest["fonts"]["8x16"]["sha256"], "8x16 blob SHA mismatch")

    font_patches = manifest["patches"]["font_base_literals"]
    check(u32(candidate, FONT8_LITERAL_FILE) == hx(font_patches[0]["new_value"]), "8x16 base literal mismatch")
    check(u32(candidate, FONT12_LITERAL_FILE) == hx(font_patches[1]["new_value"]), "12x12 base literal mismatch")
    check(u32(original, FONT8_LITERAL_FILE) == hx(font_patches[0]["old_value"]), "8x16 source literal drift")
    check(u32(original, FONT12_LITERAL_FILE) == hx(font_patches[1]["old_value"]), "12x12 source literal drift")
    check(
        candidate[FONT12_BASE : FONT12_BASE + FONT12_STRIDE * FONT12_COUNT]
        == original[FONT12_BASE : FONT12_BASE + FONT12_STRIDE * FONT12_COUNT],
        "original 12x12 font changed",
    )
    check(
        candidate[FONT8_BASE : FONT8_BASE + FONT8_STRIDE * FONT8_COUNT]
        == original[FONT8_BASE : FONT8_BASE + FONT8_STRIDE * FONT8_COUNT],
        "original 8x16 font changed",
    )

    # Verify every selected slot carries a nonblank glyph in both relocated
    # font modes.  This catches a token/font-slot mismatch even if the blob SHA
    # itself is internally consistent.
    selected = manifest["font_assignment"]["selected"]
    selected_slots: set[int] = set()
    active_rows: list[int] = []
    for row in selected:
        slot = hx(row["slot"])
        check(slot not in selected_slots, f"duplicate selected slot 0x{slot:04X}")
        selected_slots.add(slot)
        g12 = candidate[f12_start + slot * FONT12_STRIDE : f12_start + (slot + 1) * FONT12_STRIDE]
        g8 = candidate[f8_start + slot * FONT8_STRIDE : f8_start + (slot + 1) * FONT8_STRIDE]
        check(any(g12), f"blank 12x12 selected glyph {row['char']}")
        check(any(g8), f"blank 8x16 selected glyph {row['char']}")
        active_rows.append(sum(any(g8[y * 2 : y * 2 + 2]) for y in range(16)))
    check(min(active_rows) >= 10, f"8x16 active-row collapse: min={min(active_rows)}")
    manifest_rows = manifest["fonts"]["8x16"].get("active_rows", {})
    check(int(manifest_rows.get("min", -1)) == min(active_rows), "8x16 active-row minimum drift")
    check(int(manifest_rows.get("max", -1)) == max(active_rows), "8x16 active-row maximum drift")

    # Recheck all owner fields from the translation plan, then follow every
    # ordinary pointer to the exact payload recorded in the integrated sheet.
    allowed: set[int] = set(range(FONT8_LITERAL_FILE, FONT8_LITERAL_FILE + 4))
    allowed.update(range(FONT12_LITERAL_FILE, FONT12_LITERAL_FILE + 4))
    for patch in report["pointer_plan"]["pointer_recalculation"]["owner_patches"]:
        source = hx(patch["source_file"])
        value = hx(patch["new_value"])
        allowed.update(range(source, source + 4))
        check(u32(candidate, source) == value, f"owner pointer mismatch at 0x{source:08X}")

    ordinary_checked = 0
    for row in report["records"]:
        if row["storage_contract"] != "nul_stream":
            continue
        refs = [
            ref
            for ref in row.get("references", [])
            if ref.get("patchable_u32") and ref.get("relocation_schema") == "ordinary_u32_stream"
        ]
        check(refs, f"ordinary row without owner: {row['record_id']}")
        target = u32(candidate, hx(refs[0]["pointer_source_file"])) - ROM_BASE
        payload = raw(row["translated_raw_hex"])
        check(0 <= target <= len(candidate) - len(payload), f"ordinary target outside image: {row['record_id']}")
        check(candidate[target : target + len(payload)] == payload, f"ordinary payload mismatch: {row['record_id']}")
        ordinary_checked += 1

    changed = [
        index
        for index, (before, after) in enumerate(zip(original, candidate[: len(original)]))
        if before != after
    ]
    unexpected = [index for index in changed if index not in allowed]
    check(not unexpected, f"unexpected original-half changes: {len(unexpected)}")
    check(candidate[STRONG_TAIL:ORIGINAL_SIZE] == original[STRONG_TAIL:ORIGINAL_SIZE], "strong tail changed")
    check(candidate[0xA0:0xC0] == original[0xA0:0xC0], "GBA header changed")

    result = {
        "result": "PASS",
        "candidate_sha256": sha(candidate),
        "font_selected_glyphs": len(selected),
        "ordinary_payloads_checked": ordinary_checked,
        "owner_u32_fields_checked": len(report["pointer_plan"]["pointer_recalculation"]["owner_patches"]),
        "changed_bytes_in_original_half": len(changed),
        "allowed_patch_bytes": len(allowed),
        "unexpected_changed_bytes": 0,
        "original_fonts_unchanged": True,
        "strong_tail_unchanged": True,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
