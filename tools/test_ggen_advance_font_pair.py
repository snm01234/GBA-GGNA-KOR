#!/usr/bin/env python3
"""Build a font-only derivative of the latest unified GGA POC.

The builder intentionally accepts only the native, antialias-free BDF faces
from Galmuri.zip.  Its defaults are the current canonical POC pair:
Galmuri11 Regular for 12x12 and Galmuri11-Condensed Regular for 8x16.
Other pairs can still be generated explicitly for comparison.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile

from PIL import Image, ImageDraw, ImageFont


THIS_DIR = Path(__file__).resolve().parent
ADVANCE_DIR = THIS_DIR.parent
for path in (THIS_DIR,):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from ggen_advance_project_paths import FONT_ZIP  # noqa: E402

import build_ggen_advance_ko_poc as fontops  # noqa: E402


ROM_BASE = 0x08000000
DEFAULT_BASE = ADVANCE_DIR / "outputs" / "20260829_ggen_advance_unified_rom" / "ggen_advance_unified_translation_poc_20260831.gba"
DEFAULT_APPLY_MAP = ADVANCE_DIR / "analysis" / "ggen_advance_korean_apply_charmap_20260831.json"
DEFAULT_MANIFEST = ADVANCE_DIR / "analysis" / "ggen_advance_unified_rom_poc_20260831.json"
DEFAULT_FONT_ZIP = FONT_ZIP
DEFAULT_OUT = ADVANCE_DIR / "outputs" / "20260828_ggen_advance_font_tests" / "ggen_advance_galmuri11_12x12_galmuri11condensed_8x16_native_basic.gba"
DEFAULT_PREVIEW = Path(
    r"C:\Users\Administrator\.codex\visualizations\2026\08\28\01a04823-6b47-76f3-aa3e-d5117456d509\ggen-advance-galmuri11-native-condensed-basic-test.png"
)
DEFAULT_TEST_MANIFEST = ADVANCE_DIR / "analysis" / "ggen_advance_font_pair_galmuri11_native_condensed_test_20260828.json"
DEFAULT_FONT12_MEMBER = "Galmuri11.bdf"
DEFAULT_FONT8_MEMBER = "Galmuri11-Condensed.bdf"


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def gate(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"gate failed: {message}")


def parse_hex(value: str) -> int:
    return int(value, 16)


@dataclass(frozen=True)
class BdfGlyph:
    width: int
    height: int
    x_offset: int
    y_offset: int
    rows: tuple[int, ...]


class BdfFont:
    """Minimal BDF reader for native, antialias-free Galmuri glyphs."""

    def __init__(self, glyphs: dict[int, BdfGlyph], name: str):
        self.glyphs = glyphs
        self.name = name

    @classmethod
    def from_bytes(cls, data: bytes, name: str) -> "BdfFont":
        lines = data.decode("utf-8").splitlines()
        glyphs: dict[int, BdfGlyph] = {}
        index = 0
        while index < len(lines):
            if not lines[index].startswith("STARTCHAR"):
                index += 1
                continue
            start = index
            encoding = None
            width = height = x_offset = y_offset = 0
            bitmap: list[int] = []
            index += 1
            while index < len(lines) and lines[index] != "ENDCHAR":
                line = lines[index]
                if line.startswith("ENCODING "):
                    encoding = int(line.split()[1])
                elif line.startswith("BBX "):
                    _, width, height, x_offset, y_offset = line.split()
                    width, height, x_offset, y_offset = map(
                        int, (width, height, x_offset, y_offset)
                    )
                elif line == "BITMAP":
                    index += 1
                    while index < len(lines) and lines[index] != "ENDCHAR":
                        bitmap.append(int(lines[index], 16))
                        index += 1
                    break
                index += 1
            if encoding is not None and len(bitmap) == height:
                glyphs[encoding] = BdfGlyph(
                    width, height, x_offset, y_offset, tuple(bitmap)
                )
            index = max(index, start + 1) + 1
        return cls(glyphs, name)

    def render(self, char: str, cell_width: int, cell_height: int) -> Image.Image:
        glyph = self.glyphs.get(ord(char))
        if glyph is None:
            raise ValueError(f"{self.name} has no glyph for {char!r}")
        gate(
            glyph.width <= cell_width and glyph.height <= cell_height,
            f"{self.name} glyph exceeds {cell_width}x{cell_height} cell: {char!r} "
            f"{glyph.width}x{glyph.height} offset={glyph.x_offset},{glyph.y_offset}",
        )
        output = Image.new("L", (cell_width, cell_height), 0)
        # BDF rows are top-to-bottom and are already the font's native pixels.
        x_origin = (cell_width - glyph.width) // 2 + glyph.x_offset
        y_origin = (cell_height - glyph.height) // 2 - glyph.y_offset
        hex_width = max(1, (glyph.width + 7) // 8)
        clipped_pixels = 0
        for row, value in enumerate(glyph.rows):
            for col in range(glyph.width):
                bit = (value >> (hex_width * 8 - 1 - col)) & 1
                if bit:
                    x = x_origin + col
                    y = y_origin + row
                    if 0 <= x < cell_width and 0 <= y < cell_height:
                        output.putpixel((x, y), 255)
                    else:
                        clipped_pixels += 1
        gate(
            clipped_pixels == 0,
            f"{self.name} glyph pixels exceed {cell_width}x{cell_height} cell: {char!r} "
            f"clipped={clipped_pixels}",
        )
        return output


def load_bdf(archive: ZipFile, member: str) -> BdfFont:
    return BdfFont.from_bytes(archive.read(member), member)


def face_name(member: str) -> str:
    return "Regular Condensed" if "condensed" in member.casefold() else "Regular"


def render_condensed_8x16_basic(char: str, font: BdfFont) -> Image.Image:
    """Place a native BDF bitmap in the 8x16 cell without row duplication."""
    return font.render(char, 8, 16)


def render_12x12_basic(char: str, font: BdfFont) -> Image.Image:
    """Place a native BDF bitmap in the 12x12 cell without synthetic weight."""
    return font.render(char, 12, 12)


def touches_cell_edge(image: Image.Image) -> bool:
    width, height = image.size
    return any(
        image.getpixel((0, y))
        or image.getpixel((width - 1, y))
        or image.getpixel((x, 0))
        or image.getpixel((x, height - 1))
        for y in range(height)
        for x in range(width)
    )


def slot_for_assignment(item: dict[str, object], mode: str) -> int | None:
    paint = str(item.get("paint") or "")
    if mode == "12x12" and paint not in {"both", "12x12", "split"}:
        return None
    if mode == "8x16" and paint not in {"both", "8x16", "split"}:
        return None
    if mode == "8x16" and item.get("slot_8x16"):
        return parse_hex(str(item["slot_8x16"]))
    return parse_hex(str(item["slot"]))


def render_sample_strip(
    text: str,
    font: BdfFont,
    mode: str,
    scale: int,
) -> Image.Image:
    cell_w, cell_h = (12, 12) if mode == "12x12" else (8, 16)
    render = render_12x12_basic if mode == "12x12" else render_condensed_8x16_basic
    width = sum(cell_w * scale + (scale * 2 if char == " " else 0) for char in text)
    output = Image.new("RGB", (width, cell_h * scale), "#000000")
    cursor = 0
    for char in text:
        cell = render(char, font)
        enlarged = cell.resize((cell_w * scale, cell_h * scale), Image.Resampling.NEAREST).convert("RGB")
        output.paste(enlarged, (cursor, 0))
        cursor += cell_w * scale
        if char == " ":
            cursor += scale * 2
    return output


def build_preview(
    path: Path,
    font12: BdfFont,
    font8: BdfFont,
    font12_member: str,
    font8_member: str,
) -> None:
    samples = ("한글 가독성!", "젠장! 젠장!")
    scale = 5
    width = 1200
    canvas = Image.new("RGB", (width, 410), "#161616")
    draw = ImageDraw.Draw(canvas)
    label_font = ImageFont.truetype(r"C:\Windows\Fonts\malgun.ttf", 20)
    small_font = ImageFont.truetype(r"C:\Windows\Fonts\malgun.ttf", 14)
    draw.text((18, 12), "G Generation Advance basic-weight font test", font=label_font, fill="#eeeeee")
    draw.text(
        (18, 42),
        f"12x12: {font12_member}   8x16: {font8_member}   (native BDF; no bold, dilation, or row stretch)",
        font=small_font,
        fill="#aeb4be",
    )
    draw.text((18, 76), "12×12", font=small_font, fill="#aeb4be")
    draw.text((110, 76), samples[0], font=small_font, fill="#7f8792")
    canvas.paste(render_sample_strip(samples[0], font12, "12x12", scale), (110, 97))
    draw.text((18, 255), "8×16", font=small_font, fill="#aeb4be")
    draw.text((110, 255), samples[1], font=small_font, fill="#7f8792")
    canvas.paste(render_sample_strip(samples[1], font8, "8x16", scale), (110, 276))
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path)


def build_test(
    base_rom_path: Path,
    apply_map_path: Path,
    base_manifest_path: Path,
    font_zip: Path,
    font12_member: str,
    font8_member: str,
    output_path: Path,
    preview_path: Path,
    test_manifest_path: Path,
) -> dict[str, object]:
    base_rom = base_rom_path.read_bytes()
    base_manifest = json.loads(base_manifest_path.read_text(encoding="utf-8"))
    expected_base_sha = str(base_manifest["output"]["sha256"])
    gate(sha256(base_rom) == expected_base_sha, "base ROM does not match the latest unified POC manifest")
    apply_map = json.loads(apply_map_path.read_text(encoding="utf-8"))
    assignments = list(apply_map.get("assignments") or [])
    gate(assignments, "apply-charmap has no assignments")

    with ZipFile(font_zip) as archive:
        # Use the font package's native BDF bitmaps.  This avoids FreeType
        # antialias thresholding and keeps the face's original stroke weight.
        test12 = load_bdf(archive, font12_member)
        test8 = load_bdf(archive, font8_member)
        build_preview(preview_path, test12, test8, font12_member, font8_member)

        candidate = bytearray(base_rom)
        font12_offset = parse_hex(str(base_manifest["fonts"]["font_12x12"]["file_offset"]))
        font8_offset = parse_hex(str(base_manifest["fonts"]["font_8x16"]["file_offset"]))
        original_half = bytes(base_rom[: len(base_rom) // 2])
        painted12 = painted8 = 0
        edge12 = edge8 = 0
        blank12: list[str] = []
        blank8: list[str] = []
        for item in assignments:
            char = str(item["char"])
            slot12 = slot_for_assignment(item, "12x12")
            if slot12 is not None:
                image12 = render_12x12_basic(char, test12)
                edge12 += touches_cell_edge(image12)
                packed12 = fontops.pack_12x12(image12)
                start = font12_offset + slot12 * fontops.FONT_12X12_STRIDE
                candidate[start : start + fontops.FONT_12X12_STRIDE] = packed12
                painted12 += 1
                if not any(packed12):
                    blank12.append(char)
            slot8 = slot_for_assignment(item, "8x16")
            if slot8 is not None:
                image8 = render_condensed_8x16_basic(char, test8)
                edge8 += touches_cell_edge(image8)
                packed8 = fontops.pack_8x16(image8)
                start = font8_offset + slot8 * fontops.FONT_8X16_STRIDE
                candidate[start : start + fontops.FONT_8X16_STRIDE] = packed8
                painted8 += 1
                if not any(packed8):
                    blank8.append(char)

    gate(len(candidate) == len(base_rom), "font-pair test ROM size drift")
    gate(bytes(candidate[: len(base_rom) // 2]) == original_half, "font-pair test changed the original ROM half")
    gate(not blank12 and not blank8, "font-pair test rendered blank Hangul glyphs")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(candidate)
    result = {
        "schema_version": 1,
        "description": "font-only derivative of the latest unified GGA POC",
        "base_rom": {"file": str(base_rom_path), "sha256": sha256(base_rom)},
        "font_pair": {
            "12x12": {
                "member": font12_member,
                "face": face_name(font12_member),
                "cell_placement": "native BDF bitmap centered in 12x12",
            },
            "8x16": {
                "member": font8_member,
                "face": face_name(font8_member),
                "cell_placement": "native BDF bitmap centered in 8x16",
                "vertical_active_rows": "font-native (no duplication)",
            },
        },
        "assignments": len(assignments),
        "painted_12x12": painted12,
        "painted_8x16": painted8,
        "output": {"file": str(output_path), "size": len(candidate), "sha256": sha256(candidate)},
        "preview": str(preview_path),
        "verification": {
            "original_rom_half_unchanged": True,
            "blank_12x12": len(blank12),
            "blank_8x16": len(blank8),
            "12x12_cell_edge_contacts": edge12,
            "8x16_cell_edge_contacts": edge8,
            "native_bitmap_source": True,
            "synthetic_bold_or_dilation": False,
            "native_bitmap_pixels_clipped": 0,
            "12x12_font_cell_clipping": False,
            "8x16_font_cell_clipping": False,
        },
    }
    test_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    test_manifest_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-rom", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--apply-map", type=Path, default=DEFAULT_APPLY_MAP)
    parser.add_argument("--base-manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--font-zip", type=Path, default=DEFAULT_FONT_ZIP)
    parser.add_argument("--font12-member", default=DEFAULT_FONT12_MEMBER)
    parser.add_argument("--font8-member", default=DEFAULT_FONT8_MEMBER)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--preview", type=Path, default=DEFAULT_PREVIEW)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_TEST_MANIFEST)
    args = parser.parse_args()
    result = build_test(
        args.base_rom,
        args.apply_map,
        args.base_manifest,
        args.font_zip,
        args.font12_member,
        args.font8_member,
        args.out,
        args.preview,
        args.manifest,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
