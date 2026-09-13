#!/usr/bin/env python3
"""Build and statically verify a Korean-display POC ROM for G Generation Advance.

The input ROM is never modified.  The POC replaces four glyphs in both of the
game's font paths, adds a tokenized ``한글출력`` marker in unused tail space,
and broadly redirects two historical pointer runs to that marker.  This was an
early visibility/stress-test technique: later strict R3/dataflow analysis proved
that the full 200/202 physical runs are heterogeneous and must NOT be used as
production text-owner boundaries.  Four frequent literal-glyph slots are also
replaced so Korean pixels are likely to appear during a smoke test.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from PIL import Image, ImageDraw, ImageFont


EXPECTED_SIZE = 16 * 1024 * 1024
EXPECTED_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"
ROM_BASE = 0x08000000

FONT_12X12_BASE = 0x0008AC40
FONT_12X12_STRIDE = 18
FONT_12X12_COUNT = 1992
FONT_8X16_BASE = 0x00094028
FONT_8X16_STRIDE = 32
FONT_8X16_COUNT = 2068

POC_TEXT = "한글출력"
POC_TOKENS = (0xE6D0, 0xE6D1, 0xE6D2, 0xE6D3)
FREQUENT_ALIAS_TOKENS = (0xE1A6, 0xE5B4, 0xE4C5, 0xE1F6)
POC_STRING_OFFSET = 0x00FCED40
BROAD_POC_POINTER_RUNS = (
    (0x00FCE2D8, 200),
    (0x00FCDF78, 202),
)


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def glyph_slot(token: int) -> int:
    """Mirror the game's E000-EFFF -> internal-slot normalization."""
    if not 0xE000 <= token <= 0xEFFF:
        raise ValueError(f"not a literal glyph token: 0x{token:04X}")
    return (token + 0x20E0) & 0xFFFF


def render_glyph(char: str, font: ImageFont.FreeTypeFont, width: int, height: int) -> Image.Image:
    scratch = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(scratch)
    left, top, right, bottom = draw.textbbox((0, 0), char, font=font)
    glyph_width = right - left
    glyph_height = bottom - top
    x = (width - glyph_width) // 2 - left
    y = (height - glyph_height) // 2 - top
    draw.text((x, y), char, font=font, fill=255)
    return scratch.point(lambda value: 255 if value >= 128 else 0, mode="1").convert("L")


def pack_12x12(image: Image.Image) -> bytes:
    packed = bytearray(FONT_12X12_STRIDE)
    for y in range(12):
        for x in range(12):
            if image.getpixel((x, y)):
                bit = y * 12 + x
                packed[bit // 8] |= 1 << (bit & 7)
    return bytes(packed)


def unpack_12x12(raw: bytes) -> Image.Image:
    if len(raw) != FONT_12X12_STRIDE:
        raise ValueError("12x12 glyph must be 18 bytes")
    image = Image.new("L", (12, 12), 0)
    for y in range(12):
        for x in range(12):
            bit = y * 12 + x
            if raw[bit // 8] & (1 << (bit & 7)):
                image.putpixel((x, y), 255)
    return image


def pack_8x16(image: Image.Image) -> bytes:
    packed = bytearray(FONT_8X16_STRIDE)
    for y in range(16):
        for x in range(8):
            if image.getpixel((x, y)):
                packed[y * 2 + x // 4] |= 1 << (2 * (x & 3))
    return bytes(packed)


def unpack_8x16(raw: bytes) -> Image.Image:
    if len(raw) != FONT_8X16_STRIDE:
        raise ValueError("8x16 glyph must be 32 bytes")
    image = Image.new("L", (8, 16), 0)
    for y in range(16):
        for x in range(8):
            value = (raw[y * 2 + x // 4] >> (2 * (x & 3))) & 0x03
            if value:
                image.putpixel((x, y), 255)
    return image


def load_fonts(font_zip: Path) -> tuple[ImageFont.FreeTypeFont, ImageFont.FreeTypeFont]:
    with ZipFile(font_zip) as archive:
        large = ImageFont.truetype(BytesIO(archive.read("Galmuri11-Bold.ttf")), 11)
        small = ImageFont.truetype(BytesIO(archive.read("Galmuri7.ttf")), 7)
    return large, small


def encoded_poc_string() -> bytes:
    return b"".join(struct.pack(">H", token) for token in POC_TOKENS) + b"\x00"


def validate_pointer_table(data: bytes | bytearray, offset: int, count: int) -> None:
    end = offset + count * 4
    if end > len(data):
        raise ValueError(f"pointer table 0x{offset:08X} exceeds ROM")
    for index in range(count):
        value = struct.unpack_from("<I", data, offset + index * 4)[0]
        if not ROM_BASE <= value < ROM_BASE + len(data):
            raise ValueError(
                f"pointer table 0x{offset:08X}[{index}] is not a ROM pointer: 0x{value:08X}"
            )


def write_glyph(data: bytearray, token: int, packed_12: bytes, packed_8: bytes) -> dict[str, object]:
    slot = glyph_slot(token)
    if slot >= min(FONT_12X12_COUNT, FONT_8X16_COUNT):
        raise ValueError(f"glyph slot 0x{slot:04X} is outside the shared font range")
    offset_12 = FONT_12X12_BASE + slot * FONT_12X12_STRIDE
    offset_8 = FONT_8X16_BASE + slot * FONT_8X16_STRIDE
    data[offset_12 : offset_12 + FONT_12X12_STRIDE] = packed_12
    data[offset_8 : offset_8 + FONT_8X16_STRIDE] = packed_8
    return {
        "token": f"0x{token:04X}",
        "internal_slot": f"0x{slot:04X}",
        "font_12x12_offset": f"0x{offset_12:08X}",
        "font_8x16_offset": f"0x{offset_8:08X}",
    }


def write_glyph_slot(data: bytearray, slot: int, packed_12: bytes, packed_8: bytes) -> None:
    if slot >= min(FONT_12X12_COUNT, FONT_8X16_COUNT):
        raise ValueError(f"glyph slot 0x{slot:04X} is outside the shared font range")
    offset_12 = FONT_12X12_BASE + slot * FONT_12X12_STRIDE
    offset_8 = FONT_8X16_BASE + slot * FONT_8X16_STRIDE
    data[offset_12 : offset_12 + FONT_12X12_STRIDE] = packed_12
    data[offset_8 : offset_8 + FONT_8X16_STRIDE] = packed_8


def write_preview(
    path: Path,
    glyphs_12: list[Image.Image],
    glyphs_8: list[Image.Image],
) -> None:
    scale = 6
    margin = 8
    gap = 8
    large_width = len(glyphs_12) * 12 * scale + (len(glyphs_12) - 1) * gap
    small_width = len(glyphs_8) * 8 * scale + (len(glyphs_8) - 1) * gap
    canvas = Image.new("RGB", (max(large_width, small_width) + margin * 2, 220), "#20242b")
    draw = ImageDraw.Draw(canvas)
    draw.text((margin, 8), "12x12 / 1bpp", fill="white")
    x = margin
    for glyph in glyphs_12:
        enlarged = glyph.resize((12 * scale, 12 * scale), Image.Resampling.NEAREST).convert("RGB")
        canvas.paste(enlarged, (x, 28))
        x += 12 * scale + gap
    draw.text((margin, 112), "8x16 / 2bpp", fill="white")
    x = margin
    for glyph in glyphs_8:
        enlarged = glyph.resize((8 * scale, 16 * scale), Image.Resampling.NEAREST).convert("RGB")
        canvas.paste(enlarged, (x, 132))
        x += 8 * scale + gap
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path)


def verify_candidate(
    data: bytes | bytearray,
    expected_12: list[bytes],
    expected_8: list[bytes],
    *,
    include_aliases: bool,
    broad_aliases: bool,
) -> dict[str, object]:
    marker = encoded_poc_string()
    if data[POC_STRING_OFFSET : POC_STRING_OFFSET + len(marker)] != marker:
        raise ValueError("POC marker string verification failed")
    marker_pointer = ROM_BASE + POC_STRING_OFFSET
    redirected_tables = []
    for table_offset, count in BROAD_POC_POINTER_RUNS:
        values = struct.unpack_from(f"<{count}I", data, table_offset)
        if any(value != marker_pointer for value in values):
            raise ValueError(f"pointer redirect verification failed at 0x{table_offset:08X}")
        redirected_tables.append({"offset": f"0x{table_offset:08X}", "entries": count})

    tokens = list(POC_TOKENS)
    if include_aliases:
        tokens.extend(FREQUENT_ALIAS_TOKENS)
    verified = []
    specific_slots: set[int] = set()
    for index, token in enumerate(tokens):
        char_index = index % len(POC_TEXT)
        slot = glyph_slot(token)
        specific_slots.add(slot)
        offset_12 = FONT_12X12_BASE + slot * FONT_12X12_STRIDE
        offset_8 = FONT_8X16_BASE + slot * FONT_8X16_STRIDE
        if bytes(data[offset_12 : offset_12 + FONT_12X12_STRIDE]) != expected_12[char_index]:
            raise ValueError(f"12x12 glyph verification failed for 0x{token:04X}")
        if bytes(data[offset_8 : offset_8 + FONT_8X16_STRIDE]) != expected_8[char_index]:
            raise ValueError(f"8x16 glyph verification failed for 0x{token:04X}")
        verified.append(f"0x{token:04X}")
    verified_broad_slots = 0
    if broad_aliases:
        for slot in range(1, min(FONT_12X12_COUNT, FONT_8X16_COUNT)):
            if slot in specific_slots:
                continue
            char_index = (slot - 1) % len(POC_TEXT)
            offset_12 = FONT_12X12_BASE + slot * FONT_12X12_STRIDE
            offset_8 = FONT_8X16_BASE + slot * FONT_8X16_STRIDE
            if bytes(data[offset_12 : offset_12 + FONT_12X12_STRIDE]) != expected_12[char_index]:
                raise ValueError(f"broad 12x12 glyph verification failed for slot 0x{slot:04X}")
            if bytes(data[offset_8 : offset_8 + FONT_8X16_STRIDE]) != expected_8[char_index]:
                raise ValueError(f"broad 8x16 glyph verification failed for slot 0x{slot:04X}")
            verified_broad_slots += 1
    return {
        "marker_offset": f"0x{POC_STRING_OFFSET:08X}",
        "marker_address": f"0x{marker_pointer:08X}",
        "marker_bytes": marker.hex(" ").upper(),
        "redirected_tables": redirected_tables,
        "verified_glyph_tokens": verified,
        "verified_broad_alias_slots": verified_broad_slots,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rom", type=Path, help="clean Japanese ROM")
    parser.add_argument("--out", type=Path, required=True, help="new POC ROM path")
    parser.add_argument("--font-zip", type=Path, required=True, help="Galmuri release archive")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--preview", type=Path, required=True)
    parser.add_argument(
        "--no-frequent-aliases",
        action="store_true",
        help="do not replace four frequent Japanese glyph slots",
    )
    parser.add_argument(
        "--broad-runtime-aliases",
        action="store_true",
        help=(
            "POC-only: replace every shared renderable glyph slot with a repeating "
            "Hangul pattern so the first Japanese text screen proves runtime rendering"
        ),
    )
    args = parser.parse_args()

    original = args.rom.read_bytes()
    original_hash = sha256(original)
    if len(original) != EXPECTED_SIZE or original_hash != EXPECTED_SHA256:
        raise SystemExit(
            "Refusing unknown ROM: "
            f"size={len(original)}, sha256={original_hash}; expected {EXPECTED_SIZE}, {EXPECTED_SHA256}"
        )
    for table_offset, count in BROAD_POC_POINTER_RUNS:
        validate_pointer_table(original, table_offset, count)
    if any(value != 0xFF for value in original[POC_STRING_OFFSET : POC_STRING_OFFSET + 64]):
        raise SystemExit(f"expected FF tail space at 0x{POC_STRING_OFFSET:08X}")

    large_font, small_font = load_fonts(args.font_zip)
    glyphs_12 = [render_glyph(char, large_font, 12, 12) for char in POC_TEXT]
    glyphs_8 = [render_glyph(char, small_font, 8, 16) for char in POC_TEXT]
    packed_12 = [pack_12x12(glyph) for glyph in glyphs_12]
    packed_8 = [pack_8x16(glyph) for glyph in glyphs_8]

    candidate = bytearray(original)
    patches = []
    broad_alias_count = 0
    if args.broad_runtime_aliases:
        # Slots 01-DF are the game's very dense single-byte alphabet and include
        # most characters seen in the first prologue.  E0+ are reached by
        # two-byte E000-EFFF tokens.  Slot 00 is the string terminator and is
        # deliberately left alone.
        for slot in range(0x0001, min(FONT_12X12_COUNT, FONT_8X16_COUNT)):
            char_index = (slot - 0x0001) % len(POC_TEXT)
            write_glyph_slot(candidate, slot, packed_12[char_index], packed_8[char_index])
            broad_alias_count += 1
    tokens = list(POC_TOKENS)
    include_aliases = not args.no_frequent_aliases
    if include_aliases:
        tokens.extend(FREQUENT_ALIAS_TOKENS)
    for index, token in enumerate(tokens):
        char_index = index % len(POC_TEXT)
        row = write_glyph(candidate, token, packed_12[char_index], packed_8[char_index])
        row["character"] = POC_TEXT[char_index]
        row["purpose"] = "marker" if token in POC_TOKENS else "frequent-runtime-alias"
        patches.append(row)

    marker = encoded_poc_string()
    candidate[POC_STRING_OFFSET : POC_STRING_OFFSET + len(marker)] = marker
    marker_pointer = ROM_BASE + POC_STRING_OFFSET
    for table_offset, count in BROAD_POC_POINTER_RUNS:
        for index in range(count):
            struct.pack_into("<I", candidate, table_offset + index * 4, marker_pointer)

    verification = verify_candidate(
        candidate,
        packed_12,
        packed_8,
        include_aliases=include_aliases,
        broad_aliases=args.broad_runtime_aliases,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(candidate)
    write_preview(args.preview, glyphs_12, glyphs_8)

    changed_offsets = [index for index, pair in enumerate(zip(original, candidate)) if pair[0] != pair[1]]
    patch_regions = [
        {
            "purpose": "confirmed text pointer table redirect",
            "start": f"0x{table_offset:08X}",
            "end_exclusive": f"0x{table_offset + count * 4:08X}",
            "length": count * 4,
        }
        for table_offset, count in BROAD_POC_POINTER_RUNS
    ]
    patch_regions.append(
        {
            "purpose": "tokenized Korean marker",
            "start": f"0x{POC_STRING_OFFSET:08X}",
            "end_exclusive": f"0x{POC_STRING_OFFSET + len(marker):08X}",
            "length": len(marker),
        }
    )
    if args.broad_runtime_aliases:
        patch_regions.extend(
            [
                {
                    "purpose": "POC-only broad 12x12 Hangul aliases (slots 1+)",
                    "start": f"0x{FONT_12X12_BASE + FONT_12X12_STRIDE:08X}",
                    "end_exclusive": f"0x{FONT_12X12_BASE + FONT_12X12_COUNT * FONT_12X12_STRIDE:08X}",
                    "length": (FONT_12X12_COUNT - 1) * FONT_12X12_STRIDE,
                },
                {
                    "purpose": "POC-only broad 8x16 Hangul aliases (slots 1+)",
                    "start": f"0x{FONT_8X16_BASE + FONT_8X16_STRIDE:08X}",
                    "end_exclusive": f"0x{FONT_8X16_BASE + FONT_8X16_COUNT * FONT_8X16_STRIDE:08X}",
                    "length": (FONT_8X16_COUNT - 1) * FONT_8X16_STRIDE,
                },
            ]
        )

    manifest = {
        "schema_version": 1,
        "description": "mGBA runtime Korean-display POC; not a translation patch",
        "source": {
            "path": str(args.rom.resolve()),
            "size": len(original),
            "sha256": original_hash,
        },
        "output": {
            "path": str(args.out.resolve()),
            "size": len(candidate),
            "sha256": sha256(candidate),
        },
        "text": POC_TEXT,
        "glyph_patches": patches,
        "broad_runtime_aliases": {
            "enabled": args.broad_runtime_aliases,
            "shared_renderable_slots_replaced": broad_alias_count,
            "purpose": "runtime visibility only; not translation data",
        },
        "verification": verification,
        "changed_byte_count": len(changed_offsets),
        "patch_regions": patch_regions,
        "preview": str(args.preview.resolve()),
        "runtime_status": "pending mGBA smoke test",
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": manifest["output"],
                "text": manifest["text"],
                "changed_byte_count": manifest["changed_byte_count"],
                "broad_runtime_aliases": manifest["broad_runtime_aliases"],
                "verification": manifest["verification"],
                "manifest": str(args.manifest.resolve()),
                "preview": str(args.preview.resolve()),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
