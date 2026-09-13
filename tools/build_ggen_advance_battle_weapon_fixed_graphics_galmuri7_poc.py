#!/usr/bin/env python3
"""Patch the battle weapon-row fixed Japanese mini graphics with Galmuri7.

The battle list is not using the ordinary source 8x16 font for these labels.
`0x08039B28` renders each row into BG VRAM from small embedded graphic
resources, and `0x0803A19C` copies the finished 224x16 row to OBJ VRAM.  This
builder patches only the 64-byte 8x16 graphic payload inside the eight measured
resources for 実/攻/命/弾/射/近/単/全.  Resource headers, 32-byte palettes, layout,
and all unrelated graphics remain byte-identical.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

from PIL import Image

from ggen_advance_project_paths import ADVANCE_ROOT, FONT_ZIP
import test_ggen_advance_font_pair as fontpair

MAIN_ROM = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).gba"
JP_ROM = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Japan).gba"
OUT = ADVANCE_ROOT / "outputs" / "20260829_ggen_advance_battle_ui" / "ggen_advance_battle_weapon_fixed_graphics_galmuri7_shadowfix_candidate_20260830.gba"
MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_battle_weapon_fixed_graphics_galmuri7_shadowfix_20260830.json"
PREVIEW = ADVANCE_ROOT / "outputs" / "20260829_ggen_advance_battle_ui" / "ggen_advance_battle_weapon_fixed_graphics_galmuri7_shadowfix_preview_20260830.png"

EXPECTED_MAIN_SHA256 = "4cfd9bcaeadf33e068848ba0e4e45bc8bec2e0d62e0cf7a0fdbd508ac389998f"
EXPECTED_JP_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"
RESOURCE_HEADER = bytes.fromhex("0200010210000400140040005400200000000100")
GRAPHIC_REL = 0x14
GRAPHIC_BYTES = 0x40
PALETTE_REL = 0x54
PALETTE_BYTES = 0x20
SHADOW_INDEX = 4
SOURCE_BRIGHT_INDICES = {13, 14, 15}
SOURCE_GLYPH_INDICES = {SHADOW_INDEX, *SOURCE_BRIGHT_INDICES}
INK_INDEX = 15

# Clean, glyph-free 8x16 background cells from the same fixed-resource family.
# 0xA8DF20 / 0xA8DF94 / 0xA8E008 are the measured left/middle/right cells
# used by the battle row.  They let us restore the Japanese dark index-4
# outline as well as the D/E/F bright strokes without guessing a flat fill.
BACKGROUND_RESOURCES = {
    "left": 0x00A8DF20,
    "middle": 0x00A8DF94,
    "right": 0x00A8E008,
}

# These are measured resource descriptors referenced by 0x08039B28.
# The address delta is a regular 0x74 bytes because each resource contains
# 0x14 header + 0x40 graphic + 0x20 palette.
LABELS = {
    "실": {"source": "実", "offset": 0x00A8D854, "role": "physical_type", "screen_x_tile": 0, "background": "left"},
    "공": {"source": "攻", "offset": 0x00A8D9B0, "role": "attack", "screen_x_tile": 13, "background": "middle"},
    "명": {"source": "命", "offset": 0x00A8DA24, "role": "hit", "screen_x_tile": 20, "background": "middle"},
    "탄": {"source": "弾", "offset": 0x00A8DA98, "role": "ammo", "screen_x_tile": 23, "background": "middle"},
    "사": {"source": "射", "offset": 0x00A8DB0C, "role": "ranged", "screen_x_tile": 25, "background": "middle"},
    "전": {"source": "全", "offset": 0x00A8DB80, "role": "all", "screen_x_tile": 26, "background": "right"},
    "근": {"source": "近", "offset": 0x00A8DBF4, "role": "melee", "screen_x_tile": 25, "background": "middle"},
    "단": {"source": "単", "offset": 0x00A8DC68, "role": "single", "screen_x_tile": 26, "background": "right"},
}


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def decode_8x16(raw: bytes) -> list[list[int]]:
    gate(len(raw) == GRAPHIC_BYTES, "8x16 graphic payload must be 64 bytes")
    out = [[0] * 8 for _ in range(16)]
    for y in range(16):
        tile_base = 0 if y < 8 else 32
        row = tile_base + (y & 7) * 4
        for x in range(8):
            value = raw[row + (x >> 1)]
            out[y][x] = (value >> (4 * (x & 1))) & 0xF
    return out


def encode_8x16(pixels: list[list[int]]) -> bytes:
    gate(len(pixels) == 16 and all(len(row) == 8 for row in pixels), "8x16 pixel shape mismatch")
    out = bytearray(GRAPHIC_BYTES)
    for y in range(16):
        tile_base = 0 if y < 8 else 32
        row = tile_base + (y & 7) * 4
        for x in range(8):
            value = pixels[y][x] & 0xF
            index = row + (x >> 1)
            if x & 1:
                out[index] = (out[index] & 0x0F) | (value << 4)
            else:
                out[index] = (out[index] & 0xF0) | value
    return bytes(out)


def render_galmuri7(char: str, font: fontpair.BdfFont) -> Image.Image:
    glyph = font.glyphs.get(ord(char))
    gate(glyph is not None, f"Galmuri7 glyph missing: {char}")
    gate(glyph.height == 7 and glyph.width in (6, 7), f"unexpected Galmuri7 BBX for {char}: {glyph.width}x{glyph.height}")
    native = font.render(char, glyph.width, glyph.height)
    canvas = Image.new("1", (8, 16), 0)
    canvas.paste(native, ((8 - native.width) // 2, (16 - native.height) // 2))
    return canvas


def apply_label(rom: bytearray, jp: bytes, text: str, spec: dict, font: fontpair.BdfFont) -> dict:
    off = int(spec["offset"])
    gate(bytes(rom[off : off + len(RESOURCE_HEADER)]) == RESOURCE_HEADER, f"main resource header drift: {spec['source']}")
    gate(jp[off : off + len(RESOURCE_HEADER)] == RESOURCE_HEADER, f"JP resource header drift: {spec['source']}")
    gate(
        bytes(rom[off : off + GRAPHIC_REL + GRAPHIC_BYTES + PALETTE_BYTES])
        == jp[off : off + GRAPHIC_REL + GRAPHIC_BYTES + PALETTE_BYTES],
        f"main battle resource already differs from Japanese source: {spec['source']}",
    )

    graphic_off = off + GRAPHIC_REL
    before = bytes(rom[graphic_off : graphic_off + GRAPHIC_BYTES])
    palette_before = bytes(rom[off + PALETTE_REL : off + PALETTE_REL + PALETTE_BYTES])
    pixels = decode_8x16(before)

    background_name = str(spec["background"])
    background_off = BACKGROUND_RESOURCES[background_name]
    gate(jp[background_off : background_off + len(RESOURCE_HEADER)] == RESOURCE_HEADER, f"background resource header drift: {background_name}")
    background = decode_8x16(jp[background_off + GRAPHIC_REL : background_off + GRAPHIC_REL + GRAPHIC_BYTES])

    # The first POC cleared only D/E/F.  The source graphic also carries a
    # dark index-4 outline/shadow, so the Japanese silhouette remained around
    # the new Korean glyph.  Restore only pixels that differ from the measured
    # clean left/middle/right background and belong to the source glyph palette.
    # This preserves unrelated frame/gradient pixels byte-for-byte.
    restored = 0
    restored_shadow = 0
    restored_bright = 0
    for y in range(16):
        for x in range(8):
            value = pixels[y][x]
            if value in SOURCE_GLYPH_INDICES and value != background[y][x]:
                pixels[y][x] = background[y][x]
                restored += 1
                if value == SHADOW_INDEX:
                    restored_shadow += 1
                else:
                    restored_bright += 1
    gate(restored_shadow > 0 and restored_bright > 0, f"Japanese glyph shadow/bright footprint not found: {spec['source']}")

    glyph = render_galmuri7(text, font)
    ink_mask = [[bool(glyph.getpixel((x, y))) for x in range(8)] for y in range(16)]
    contour_mask = [[False] * 8 for _ in range(16)]
    for y in range(16):
        for x in range(8):
            if not ink_mask[y][x]:
                continue
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    ox, oy = x + dx, y + dy
                    if 0 <= ox < 8 and 0 <= oy < 16 and not ink_mask[oy][ox]:
                        contour_mask[oy][ox] = True

    contour_pixels = 0
    ink_pixels = 0
    for y in range(16):
        for x in range(8):
            if contour_mask[y][x]:
                pixels[y][x] = SHADOW_INDEX
                contour_pixels += 1
    for y in range(16):
        for x in range(8):
            if ink_mask[y][x]:
                pixels[y][x] = INK_INDEX
                ink_pixels += 1

    after = encode_8x16(pixels)
    gate(after != before, f"no change generated: {spec['source']}")
    rom[graphic_off : graphic_off + GRAPHIC_BYTES] = after
    gate(bytes(rom[off : off + GRAPHIC_REL]) == jp[off : off + GRAPHIC_REL], f"header modified: {spec['source']}")
    gate(bytes(rom[off + PALETTE_REL : off + PALETTE_REL + PALETTE_BYTES]) == palette_before, f"palette modified: {spec['source']}")

    return {
        "source": spec["source"],
        "translation": text,
        "role": spec["role"],
        "resource_file_offset": f"0x{off:08X}",
        "resource_address": f"0x{0x08000000 + off:08X}",
        "graphic_file_offset": f"0x{graphic_off:08X}",
        "screen_x_tile": spec["screen_x_tile"],
        "background_template": background_name,
        "background_resource_file_offset": f"0x{background_off:08X}",
        "source_glyph_pixels_restored": restored,
        "source_shadow_pixels_restored": restored_shadow,
        "source_bright_pixels_restored": restored_bright,
        "korean_contour_pixels": contour_pixels,
        "korean_ink_pixels": ink_pixels,
        "before_sha256": sha256(before),
        "after_sha256": sha256(after),
        "font": "Galmuri7.bdf native 6/7x7, no scaling",
        "palette_unchanged": True,
    }


def build_preview(jp: bytes, patched: bytes, out: Path) -> None:
    palette = {
        0: (0, 0, 0), 4: (55, 55, 55), 6: (115, 115, 115), 7: (145, 145, 145),
        8: (175, 175, 175), 9: (205, 205, 205), 13: (205, 180, 80),
        14: (230, 205, 105), 15: (255, 240, 145),
    }
    labels = list(LABELS.items())
    scale = 4
    image = Image.new("RGB", (8 * scale * len(labels), 16 * scale * 2), (0, 0, 0))
    for column, (text, spec) in enumerate(labels):
        off = int(spec["offset"]) + GRAPHIC_REL
        for row_index, source in enumerate((jp, patched)):
            pixels = decode_8x16(source[off : off + GRAPHIC_BYTES])
            tile = Image.new("RGB", (8, 16), (0, 0, 0))
            for y in range(16):
                for x in range(8):
                    v = pixels[y][x]
                    tile.putpixel((x, y), palette.get(v, (v * 17, v * 17, v * 17)))
            tile = tile.resize((8 * scale, 16 * scale), Image.Resampling.NEAREST)
            image.paste(tile, (column * 8 * scale, row_index * 16 * scale))
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--main", type=Path, default=MAIN_ROM)
    ap.add_argument("--jp", type=Path, default=JP_ROM)
    ap.add_argument("--font-zip", type=Path, default=FONT_ZIP)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--manifest", type=Path, default=MANIFEST)
    ap.add_argument("--preview", type=Path, default=PREVIEW)
    args = ap.parse_args()

    main_bytes = args.main.read_bytes()
    jp = args.jp.read_bytes()
    gate(sha256(main_bytes) == EXPECTED_MAIN_SHA256, f"unexpected main TIP hash: {sha256(main_bytes)}")
    gate(sha256(jp) == EXPECTED_JP_SHA256, f"unexpected Japanese ROM hash: {sha256(jp)}")
    gate(len(main_bytes) == 32 * 1024 * 1024, f"unexpected main size: {len(main_bytes)}")

    with ZipFile(args.font_zip) as archive:
        font = fontpair.load_bdf(archive, "Galmuri7.bdf")

    patched = bytearray(main_bytes)
    reports = []
    for text, spec in LABELS.items():
        reports.append(apply_label(patched, jp, text, spec, font))

    changed = [i for i, (a, b) in enumerate(zip(main_bytes, patched)) if a != b]
    allowed = set()
    for spec in LABELS.values():
        start = int(spec["offset"]) + GRAPHIC_REL
        allowed.update(range(start, start + GRAPHIC_BYTES))
    gate(changed and all(i in allowed for i in changed), "changes escaped fixed battle graphic payloads")

    # Strong preservation gates: each full 0x74 descriptor may differ only in
    # the 0x40 graphic payload.  Header and local palette must remain exact.
    for spec in LABELS.values():
        off = int(spec["offset"])
        gate(bytes(patched[off : off + GRAPHIC_REL]) == main_bytes[off : off + GRAPHIC_REL], "resource header preservation failed")
        gate(bytes(patched[off + PALETTE_REL : off + 0x74]) == main_bytes[off + PALETTE_REL : off + 0x74], "resource palette preservation failed")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(patched)
    build_preview(jp, bytes(patched), args.preview)

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_battle_weapon_fixed_graphics_galmuri7",
        "result": "PASS",
        "source": {
            "main_path": str(args.main.relative_to(ADVANCE_ROOT)),
            "main_sha256": sha256(main_bytes),
            "japanese_sha256": sha256(jp),
        },
        "runtime_proof": {
            "row_compositor": "0x08039B28",
            "row_build_call": "0x080394FA",
            "row_obj_copy": "0x0803A19C",
            "row_obj_copy_call": "0x08039502",
            "rows": 4,
            "source_bg_tile_base": 10,
            "obj_tile_bases": [0, 56, 112, 168],
            "savestate_evidence": "legacy/analysis/ggen_advance_mgba_battle_ui_savestate_20260829.json",
            "old_8x16_source_font_hypothesis": "REJECTED",
            "fixed_resource_graphic_payload": "8x16 / 64 bytes / two vertical GBA 4bpp tiles",
        },
        "compound_mapping": {
            "射単": "사단",
            "近単": "근단",
            "射全": "사전",
            "近全": "근전",
            "code_rule": "0x0803A0DE-0x0803A17A combines 射/近 at x=25 and 単/全 at x=26",
        },
        "patches": reports,
        "output": {
            "path": str(args.out.relative_to(ADVANCE_ROOT)),
            "size": len(patched),
            "sha256": sha256(bytes(patched)),
            "preview": str(args.preview.relative_to(ADVANCE_ROOT)),
        },
        "verification": {
            "result": "PASS",
            "changed_byte_count": len(changed),
            "changed_bytes_confined_to_eight_graphic_payloads": True,
            "resource_headers_unchanged": True,
            "resource_palettes_unchanged": True,
            "resource_size_unchanged": True,
            "battle_layout_code_unchanged": True,
            "source_fonts_unchanged": True,
            "galmuri7_native_no_scale": True,
        },
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "out": str(args.out),
        "sha256": report["output"]["sha256"],
        "changed_bytes": len(changed),
        "patches": [(row["source"], row["translation"], row["graphic_file_offset"]) for row in reports],
    }, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
