#!/usr/bin/env python3
"""Build a font-enabled 32 MiB translation-display PoC for GGA.

The translation PoC already relocates translated streams and patches their
owner pointers.  This companion builder adds the missing display layer:
relocated 12x12/8x16 font copies, Korean glyphs rendered into the exact token
slots used by the translation payload, and the two proven font-base literals
redirected to those copies.

Only Hangul characters that occur in ready translation rows are rendered.  All
unselected glyph slots remain byte-identical to the clean Japanese fonts.  The
PoC uses the existing allocation plan, including a small number of reclaim
slots; the manifest reports those explicitly so this remains a display proof,
not a release-safe full-font policy.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from io import BytesIO
from pathlib import Path
from typing import Any
from zipfile import ZipFile

from PIL import Image, ImageDraw, ImageFont

THIS_DIR = Path(__file__).resolve().parent
ADVANCE_DIR = THIS_DIR.parent
for path in (THIS_DIR,):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from ggen_advance_project_paths import FONT_ZIP  # noqa: E402

import build_ggen_advance_translation_master as translation  # noqa: E402
import build_ggen_advance_ko_poc as fontops  # noqa: E402
import ggen_advance_32m_layout as layout  # noqa: E402


ROM_BASE = 0x08000000
EXPANDED_SIZE = 32 * 1024 * 1024
FONT8_LITERAL_FILE = 0x00001350
FONT12_LITERAL_FILE = 0x00001388
ORIGINAL_FONT8_ADDRESS = 0x08094028
ORIGINAL_FONT12_ADDRESS = 0x0808AC40
STRONG_TAIL = 0x00FCED40


def sha256(value: bytes | bytearray) -> str:
    return hashlib.sha256(value).hexdigest()


def parse_hex(value: str) -> int:
    return int(value, 16)


def raw_hex(value: str) -> bytes:
    return bytes.fromhex(value.replace(" ", ""))


def u32(data: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def gate(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def selected_hangul(rows: list[dict[str, Any]]) -> set[str]:
    return {
        char
        for row in rows
        if row["translation_status"] in {"translated", "translated_same", "translated_partial_charmap_preserved"}
        for char in str(row.get("translation_ko", ""))
        if "가" <= char <= "힣"
    }


def load_display_fonts(font_zip: Path) -> tuple[ImageFont.FreeTypeFont, ImageFont.FreeTypeFont]:
    """Load faces at the native cell sizes used by the two GBA font modes."""
    with ZipFile(font_zip) as archive:
        # The 12x12 mode has an 11px usable text cell; the bold face keeps
        # Korean stems distinct after 1bpp packing.
        large = ImageFont.truetype(BytesIO(archive.read("Galmuri11-Bold.ttf")), 11)
        # Galmuri7 is the 8px Hangul face.  Rendering it at 7px into a 16px
        # cell was the source of the observed vowel/batchim loss.
        small = ImageFont.truetype(BytesIO(archive.read("Galmuri7.ttf")), 8)
    return large, small


def render_native_8x16(char: str, font: ImageFont.FreeTypeFont) -> Image.Image:
    """Render Galmuri7's native 8x8 cell and stretch its ink to 14 rows."""
    base = Image.new("L", (8, 8), 0)
    draw = ImageDraw.Draw(base)
    left, top, right, bottom = draw.textbbox((0, 0), char, font=font)
    width = right - left
    height = bottom - top
    gate(width <= 8 and height <= 8, f"Galmuri7 glyph exceeds native 8px cell: {char!r} {width}x{height}")
    draw.text((-left, -top), char, font=font, fill=255)
    binary = [
        [255 if base.getpixel((x, y)) >= 128 else 0 for x in range(8)]
        for y in range(8)
    ]
    occupied = [y for y, row in enumerate(binary) if any(row)]
    if not occupied:
        return Image.new("L", (8, 16), 0)
    source = binary[min(occupied) : max(occupied) + 1]
    output = Image.new("L", (8, 16), 0)
    target_height = 14
    top_padding = (16 - target_height) // 2
    for dy in range(target_height):
        source_y = min(len(source) - 1, (dy * len(source)) // target_height)
        for x, value in enumerate(source[source_y]):
            output.putpixel((x, top_padding + dy), value)
    return output


def build_candidate(
    data: bytes,
    font_zip: Path,
    reference_dir: Path,
    expected_reference_frequency_sha256: str | None = None,
) -> tuple[bytearray, dict[str, Any]]:
    gate(len(data) == 16 * 1024 * 1024, "clean ROM must be exactly 16 MiB")

    # Rebuild the canonical translation report in memory, preserving the
    # exact translation/pointer source of truth used by the XLSX sheet.
    report = translation.build_report(data)
    candidate = bytearray(report.pop("_candidate_bytes"))
    gate(len(candidate) == EXPANDED_SIZE, "translation candidate must be 32 MiB")

    rows = report["records"]
    required = selected_hangul(rows)
    gate(required, "no ready Hangul appears in the translation rows")

    plan = json.loads(translation.CHARMAP_PATH.read_text(encoding="utf-8"))
    assignments = {str(row["char"]): row for row in plan["assignments"]}
    missing = sorted(required - set(assignments))
    gate(not missing, f"ready Hangul has no Korean charmap assignment: {missing}")
    selected = [assignments[char] for char in sorted(required)]
    reclaim_selected = [row for row in selected if row["phase"] == "reclaim"]

    # Render against the advance-local snapshot, not a regenerated root plan:
    # the translation payload already contains these exact slot/token values.
    # The root font module is used only for deterministic Galmuri rendering and
    # original-format packing.
    original12 = data[fontops.FONT_12X12_BASE : fontops.FONT_12X12_BASE + fontops.FONT_12X12_STRIDE * fontops.FONT_12X12_COUNT]
    original8 = data[fontops.FONT_8X16_BASE : fontops.FONT_8X16_BASE + fontops.FONT_8X16_STRIDE * fontops.FONT_8X16_COUNT]
    gate(len(original12) == fontops.FONT_12X12_STRIDE * fontops.FONT_12X12_COUNT, "12x12 font source range truncated")
    gate(len(original8) == fontops.FONT_8X16_STRIDE * fontops.FONT_8X16_COUNT, "8x16 font source range truncated")
    blob12 = bytearray(original12)
    blob8 = bytearray(original8)
    large_font, small_font = load_display_fonts(font_zip)
    blank12 = 0
    blank8 = 0
    glyph_rows: list[dict[str, Any]] = []
    selected_slots: set[int] = set()
    for row in selected:
        char = str(row["char"])
        slot = parse_hex(str(row["slot"]))
        gate(slot not in selected_slots, f"duplicate selected font slot: 0x{slot:04X}")
        gate(slot < min(fontops.FONT_12X12_COUNT, fontops.FONT_8X16_COUNT), f"font slot outside shared range: 0x{slot:04X}")
        selected_slots.add(slot)
        packed12 = fontops.pack_12x12(fontops.render_glyph(char, large_font, 12, 12))
        small_image = render_native_8x16(char, small_font)
        packed8 = fontops.pack_8x16(small_image)
        blank12 += not any(packed12)
        blank8 += not any(packed8)
        start12 = slot * fontops.FONT_12X12_STRIDE
        start8 = slot * fontops.FONT_8X16_STRIDE
        blob12[start12 : start12 + fontops.FONT_12X12_STRIDE] = packed12
        blob8[start8 : start8 + fontops.FONT_8X16_STRIDE] = packed8
        glyph_rows.append(
            {
                "char": char,
                "slot": row["slot"],
                "token": row["token"],
                "phase": row["phase"],
                "font12_sha256": sha256(packed12),
                "font8_sha256": sha256(packed8),
                "font8_active_rows": sum(
                    any(small_image.getpixel((x, y)) for x in range(8))
                    for y in range(16)
                ),
            }
        )
    gate(blank12 == 0 and blank8 == 0, "one or more selected Korean glyphs rendered blank")
    active_rows = [int(row["font8_active_rows"]) for row in glyph_rows]
    gate(min(active_rows) >= 10, f"8x16 glyph active-row collapse: min={min(active_rows)}")
    fonts = {
        "_blob12": bytes(blob12),
        "_blob8": bytes(blob8),
        "font_12x12": {"changed_bytes": sum(a != b for a, b in zip(original12, blob12))},
        "font_8x16": {"changed_bytes": sum(a != b for a, b in zip(original8, blob8))},
        "verification": {"result": "PASS"},
        "glyphs": glyph_rows,
    }

    allocator = layout.AppendAllocator()
    font12_alloc = allocator.allocate(
        "translated_korean_font_12x12",
        len(fonts["_blob12"]),
        region="static",
        category="font",
        alignment=0x20,
        source="clean 12x12 font + ready translation Hangul slots",
    )
    font8_alloc = allocator.allocate(
        "translated_korean_font_8x16",
        len(fonts["_blob8"]),
        region="static",
        category="font",
        alignment=0x20,
        source="clean 8x16 font + ready translation Hangul slots",
    )
    candidate[font12_alloc.file_offset : font12_alloc.end_exclusive] = fonts["_blob12"]
    candidate[font8_alloc.file_offset : font8_alloc.end_exclusive] = fonts["_blob8"]

    gate(u32(data, FONT8_LITERAL_FILE) == ORIGINAL_FONT8_ADDRESS, "8x16 font-base literal drift")
    gate(u32(data, FONT12_LITERAL_FILE) == ORIGINAL_FONT12_ADDRESS, "12x12 font-base literal drift")
    struct.pack_into("<I", candidate, FONT8_LITERAL_FILE, font8_alloc.address)
    struct.pack_into("<I", candidate, FONT12_LITERAL_FILE, font12_alloc.address)

    # The translation builder already verifies all payloads.  Repeat the
    # pointer->payload check after font insertion so this output is tied to the
    # exact bytes the display PoC will use.
    ordinary_checked = 0
    for row in rows:
        if row["storage_contract"] != "nul_stream":
            continue
        refs = [
            ref
            for ref in row.get("references", [])
            if ref.get("patchable_u32") and ref.get("relocation_schema") == "ordinary_u32_stream"
        ]
        gate(refs, f"ordinary row lacks an owner pointer: {row['record_id']}")
        target = u32(candidate, parse_hex(refs[0]["pointer_source_file"])) - ROM_BASE
        payload = raw_hex(str(row["translated_raw_hex"]))
        gate(
            0 <= target <= len(candidate) - len(payload)
            and candidate[target : target + len(payload)] == payload,
            f"translated payload drift after font insertion: {row['record_id']}",
        )
        ordinary_checked += 1

    # Verify the two font copies and every selected glyph slot in both modes.
    original12 = data[fontops.FONT_12X12_BASE : fontops.FONT_12X12_BASE + fontops.FONT_12X12_STRIDE * fontops.FONT_12X12_COUNT]
    original8 = data[fontops.FONT_8X16_BASE : fontops.FONT_8X16_BASE + fontops.FONT_8X16_STRIDE * fontops.FONT_8X16_COUNT]
    for row in selected:
        slot = parse_hex(str(row["slot"]))
        start12 = slot * fontops.FONT_12X12_STRIDE
        start8 = slot * fontops.FONT_8X16_STRIDE
        glyph12 = fonts["_blob12"][start12 : start12 + fontops.FONT_12X12_STRIDE]
        glyph8 = fonts["_blob8"][start8 : start8 + fontops.FONT_8X16_STRIDE]
        gate(any(glyph12), f"blank 12x12 glyph for {row['char']}")
        gate(any(glyph8), f"blank 8x16 glyph for {row['char']}")
    gate(
        candidate[font12_alloc.file_offset : font12_alloc.end_exclusive] == fonts["_blob12"],
        "relocated 12x12 font payload mismatch",
    )
    gate(
        candidate[font8_alloc.file_offset : font8_alloc.end_exclusive] == fonts["_blob8"],
        "relocated 8x16 font payload mismatch",
    )
    gate(
        candidate[fontops.FONT_12X12_BASE : fontops.FONT_12X12_BASE + fontops.FONT_12X12_STRIDE * fontops.FONT_12X12_COUNT]
        == data[fontops.FONT_12X12_BASE : fontops.FONT_12X12_BASE + fontops.FONT_12X12_STRIDE * fontops.FONT_12X12_COUNT],
        "original 12x12 font was modified",
    )
    gate(
        candidate[fontops.FONT_8X16_BASE : fontops.FONT_8X16_BASE + fontops.FONT_8X16_STRIDE * fontops.FONT_8X16_COUNT]
        == data[fontops.FONT_8X16_BASE : fontops.FONT_8X16_BASE + fontops.FONT_8X16_STRIDE * fontops.FONT_8X16_COUNT],
        "original 8x16 font was modified",
    )

    # Strong original-half write-scope gate: the only additional writes beyond
    # the translation owner's pointer patches are the two proven font literals.
    allowed: set[int] = set(range(FONT8_LITERAL_FILE, FONT8_LITERAL_FILE + 4))
    allowed.update(range(FONT12_LITERAL_FILE, FONT12_LITERAL_FILE + 4))
    for patch in report["pointer_plan"]["pointer_recalculation"]["owner_patches"]:
        source = parse_hex(str(patch["source_file"]))
        allowed.update(range(source, source + 4))
    changed = [
        index
        for index, (before, after) in enumerate(zip(data, candidate[: len(data)]))
        if before != after
    ]
    unexpected = [index for index in changed if index not in allowed]
    gate(not unexpected, f"unexpected original-half changes: {len(unexpected)}")
    gate(candidate[STRONG_TAIL : len(data)] == data[STRONG_TAIL:], "strong tail changed")
    gate(candidate[0xA0:0xC0] == data[0xA0:0xC0], "GBA header changed")

    manifest: dict[str, Any] = {
        "schema_version": 1,
        "description": "font-enabled 32 MiB Korean translation display PoC",
        "source": report["source"],
        "translation": {
            "record_identity_sha256": report["record_identity_sha256"],
            "translation_content_sha256": report["translation_content_sha256"],
            "ready_rows": report["summary"]["translated_rows"],
            "ready_hangul_characters": len(required),
        },
        "output": {
            "size": len(candidate),
            "sha256": sha256(candidate),
        },
        "font_assignment": {
            "plan_path": str(translation.CHARMAP_PATH),
            "assignment_sha256": plan["allocation"]["assignment_sha256"],
            "selected_glyphs": len(selected),
            "bootstrap_selected": len(selected) - len(reclaim_selected),
            "reclaim_selected": len(reclaim_selected),
            "reclaim_characters": [row["char"] for row in reclaim_selected],
            "selected": [
                {
                    "char": row["char"],
                    "slot": row["slot"],
                    "token": row["token"],
                    "phase": row["phase"],
                }
                for row in selected
            ],
        },
        "fonts": {
            "12x12": {
                "allocation": font12_alloc.to_manifest(),
                "source_file_offset": f"0x{fontops.FONT_12X12_BASE:08X}",
                "size": len(fonts["_blob12"]),
                "sha256": sha256(fonts["_blob12"]),
                "changed_bytes_inside_relocated_blob": fonts["font_12x12"]["changed_bytes"],
                "rasterization": "Galmuri11-Bold.ttf @ 11px into the native 12x12 1bpp cell",
            },
            "8x16": {
                "allocation": font8_alloc.to_manifest(),
                "source_file_offset": f"0x{fontops.FONT_8X16_BASE:08X}",
                "size": len(fonts["_blob8"]),
                "sha256": sha256(fonts["_blob8"]),
                "changed_bytes_inside_relocated_blob": fonts["font_8x16"]["changed_bytes"],
                "rasterization": "Galmuri7.ttf @ 8px native 8x8, vertically expanded to 14 active rows in 8x16",
                "active_rows": {
                    "min": min(active_rows),
                    "mean": round(sum(active_rows) / len(active_rows), 2),
                    "max": max(active_rows),
                },
            },
        },
        "patches": {
            "font_base_literals": [
                {
                    "source_file": f"0x{FONT8_LITERAL_FILE:08X}",
                    "old_value": f"0x{ORIGINAL_FONT8_ADDRESS:08X}",
                    "new_value": f"0x{font8_alloc.address:08X}",
                },
                {
                    "source_file": f"0x{FONT12_LITERAL_FILE:08X}",
                    "old_value": f"0x{ORIGINAL_FONT12_ADDRESS:08X}",
                    "new_value": f"0x{font12_alloc.address:08X}",
                },
            ],
            "translation_owner_u32_fields": report["pointer_plan"]["pointer_recalculation"]["owner_u32_fields"],
            "ordinary_payloads_checked": ordinary_checked,
            "changed_bytes_in_original_half": len(changed),
            "allowed_patch_bytes": len(allowed),
            "unexpected_changed_bytes": len(unexpected),
        },
        "verification": {
            "result": "PASS",
            "font_blob_builder": fonts["verification"]["result"],
            "font_base_literals_redirected": True,
            "translated_payloads_still_match": True,
            "original_fonts_unchanged": True,
            "ordinary_payloads_checked": ordinary_checked,
            "strong_tail_unchanged": True,
            "header_unchanged": True,
            "unexpected_original_half_changes": len(unexpected),
        },
        "base_translation_verification": report["pointer_plan"]["verification"],
        "static_layout": allocator.manifest(),
    }
    return candidate, manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rom", type=Path)
    parser.add_argument("--font-zip", type=Path, default=FONT_ZIP)
    parser.add_argument("--reference-ko-dir", type=Path, default=ADVANCE_DIR / "data")
    parser.add_argument("--expected-reference-frequency-sha256")
    parser.add_argument(
        "--out-rom",
        type=Path,
        default=ADVANCE_DIR / "outputs" / "20260827_translation_master" / "ggen_advance_translation_font_poc_20260827.gba",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ADVANCE_DIR / "analysis" / "ggen_advance_translation_font_poc_20260827.json",
    )
    args = parser.parse_args()

    data = args.rom.read_bytes()
    gate(len(data) == 16 * 1024 * 1024, "clean Japanese ROM must be 16 MiB")
    candidate, manifest = build_candidate(
        data,
        args.font_zip,
        args.reference_ko_dir,
        args.expected_reference_frequency_sha256,
    )
    args.out_rom.parent.mkdir(parents=True, exist_ok=True)
    args.out_rom.write_bytes(candidate)
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
