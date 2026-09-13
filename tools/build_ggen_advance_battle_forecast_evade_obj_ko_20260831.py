#!/usr/bin/env python3
"""Patch the live battle-forecast 回避 OBJ badge and its similar 待機 badge.

Savestate VRAM proves the visible 40x16 回避 button is sprite resource
0x08A8C004 tiles 35-44, copied to OBJ tiles 224-233.  Tiles 55-64 are the
same 40x16 chrome family and match 待機.  The live ID badge (tiles 45-54)
keeps its original palette and pixels.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from zipfile import ZipFile

from PIL import Image, ImageDraw

import analyze_ggen_advance_battle_forecast_evade_obj_20260831 as analysis
import test_ggen_advance_font_pair as fontpair
from ggen_advance_project_paths import ADVANCE_ROOT, FONT_ZIP, MAIN_TIP_MANIFEST

MAIN_ROM = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).gba"
MAIN_SAV = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).sav"
JP_ROM = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Japan).gba"
OUT_DIR = ADVANCE_ROOT / "outputs" / "20260831_ggen_advance_battle_forecast"
OUT_ROM = OUT_DIR / "ggen_advance_battle_forecast_evade_obj_ko_idround_candidate_20260831.gba"
OUT_SAV = OUT_ROM.with_suffix(".sav")
OUT_PREVIEW = OUT_DIR / "ggen_advance_battle_forecast_evade_obj_ko_idround_preview_20260831.png"
OUT_MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_battle_forecast_evade_obj_ko_idround_20260831.json"
TRACE = ADVANCE_ROOT / "analysis" / "ggen_advance_battle_forecast_evade_obj_20260831.json"

EXPECTED_MAIN_SHA256 = "25c04ba5925f5e6913922b480856007738950246b7d0d8fd986a6542fb779aa8"
EXPECTED_JP_SHA256 = analysis.EXPECTED_JP_SHA256
FONT_MEMBER = "Galmuri11.bdf"

LABELS = (
    {"source": "回避", "translation": "회피", "tiles": analysis.EVADE_SRC_TILES},
    {"source": "待機", "translation": "대기", "tiles": analysis.EXTRA_SRC_TILES},
)

WELL_FILL_BY_ROW = {0: 6, 1: 9, 14: 9, 15: 6}
WELL_FILL = 10  # ID interior gold; pal12/13 share this yellow-series ramp
LETTER_INDICES = frozenset({1, 11})
PREVIEW_RGB = {
    0: (248, 160, 200),
    1: (120, 96, 32),
    6: (232, 40, 16),
    7: (248, 80, 16),
    8: (248, 112, 24),
    9: (248, 176, 40),
    10: (248, 224, 64),
    11: (248, 248, 136),
    12: (248, 248, 248),
}


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_badge(rom: bytes, tiles: tuple[int, ...]) -> list[list[int]]:
    return analysis.compose_40x16_1d([analysis.decode_tile(analysis.resource_tile(rom, tile_id)) for tile_id in tiles])


def write_badge(rom: bytearray, tiles: tuple[int, ...], pixels: list[list[int]]) -> None:
    encoded = analysis.split_40x16_1d(pixels)
    gate(len(encoded) == len(tiles), "badge tile count mismatch")
    for tile_id, tile in zip(tiles, encoded, strict=True):
        payload = analysis.encode_tile(tile)
        start = analysis.GRAPHICS_OFFSET + tile_id * analysis.TILE_BYTES
        rom[start : start + analysis.TILE_BYTES] = payload


CAP_X = tuple(list(range(0, analysis.INTERIOR_X[0])) + list(range(analysis.INTERIOR_X[1] + 1, 40)))


def chrome_mask(_original: list[list[int]]) -> set[tuple[int, int]]:
    # Caps only. Interior 9/10 are the yellow well and must remain paintable.
    return {(x, y) for y in range(16) for x in CAP_X}


def well_fill_for_row(y: int) -> int:
    return WELL_FILL_BY_ROW.get(y, WELL_FILL)


def id_yellow_template(id_pixels: list[list[int]]) -> list[list[int]]:
    """Strip ID letters so the native gold/orange well can be reused."""
    plaque = [row[:] for row in id_pixels]
    for y in range(16):
        fill = well_fill_for_row(y)
        for x in range(analysis.INTERIOR_X[0], analysis.INTERIOR_X[1] + 1):
            if plaque[y][x] in LETTER_INDICES or plaque[y][x] == analysis.SHADOW_INDEX:
                plaque[y][x] = fill
    return plaque


def restore_id_badge(
    pixels: list[list[int]],
    original: list[list[int]],
    plaque: list[list[int]],
) -> dict[str, int]:
    """Clone the letter-stripped ID badge, including left/right rounded caps.

    22.101 stamped only x=5..31, so 回避 kept its Japanese right cap. That cap
    stores the dark well (index 1) inside the round (`19877600` vs ID
    `AA987760`), which reads as a blocky brown column past 회피. Copy the ID
    chrome byte-for-byte; do not rewrite the live ID tiles themselves.
    """
    stamped = 0
    cleared_dark = 0
    cap_stamped = 0
    for y in range(16):
        for x in range(40):
            if original[y][x] == analysis.SHADOW_INDEX:
                cleared_dark += 1
            pixels[y][x] = plaque[y][x]
            stamped += 1
            if x in CAP_X:
                cap_stamped += 1
    dark_left = [
        (x, y)
        for y in range(1, 15)
        for x in range(analysis.INTERIOR_X[0], analysis.INTERIOR_X[1] + 1)
        if pixels[y][x] == analysis.SHADOW_INDEX
    ]
    cap_mismatch = [
        (x, y, pixels[y][x], plaque[y][x])
        for y in range(16)
        for x in CAP_X
        if pixels[y][x] != plaque[y][x]
    ]
    gate(not dark_left, f"dark well still present after ID clone: {dark_left[:8]}")
    gate(not cap_mismatch, f"rounded cap did not clone from ID: {cap_mismatch[:8]}")
    gate(stamped == 40 * 16, "ID clone missed pixels")
    return {
        "stamped": stamped,
        "cleared_dark": cleared_dark,
        "cap_stamped": cap_stamped,
        "yellow_well": True,
        "id_round_cloned": True,
    }


def render_korean(text: str, font: fontpair.BdfFont, chrome: set[tuple[int, int]]) -> tuple[set[tuple[int, int]], dict]:
    glyphs = []
    for char in text:
        info = font.glyphs.get(ord(char))
        gate(info is not None, f"Galmuri11 glyph missing: {char}")
        native = font.render(char, info.width, info.height)
        glyphs.append((char, info, native))
    gap = 1
    total_w = sum(info.width for _, info, _ in glyphs) + gap * (len(glyphs) - 1)
    total_h = max(info.height for _, info, _ in glyphs)
    interior_w = analysis.INTERIOR_X[1] - analysis.INTERIOR_X[0] + 1
    x0 = analysis.INTERIOR_X[0] + (interior_w - (total_w + 1)) // 2
    y0 = 2
    ink: set[tuple[int, int]] = set()
    x = x0
    placements = []
    for char, info, native in glyphs:
        placements.append({"char": char, "bbx": [info.width, info.height], "x": x, "y": y0})
        for gy in range(native.height):
            for gx in range(native.width):
                if native.getpixel((gx, gy)):
                    ink.add((x + gx, y0 + gy))
        x += info.width + gap
    gate(ink, f"empty Korean ink mask: {text}")
    collision = [pos for pos in ink if pos in chrome]
    gate(not collision, f"Korean ink hits chrome for {text}: {collision[:8]}")
    xs = [px for px, _ in ink]
    ys = [py for _, py in ink]
    gate(min(xs) >= analysis.INTERIOR_X[0] and max(xs) + 1 <= analysis.INTERIOR_X[1], f"Korean face overflows interior: {text}")
    gate(min(ys) >= 1 and max(ys) + 1 <= 14, f"Korean face overflows badge height: {text}")
    return ink, {
        "font": FONT_MEMBER,
        "native_size": [total_w, total_h],
        "origin": [x0, y0],
        "placements": placements,
        "ink_pixels": len(ink),
        "bbox": [min(xs), min(ys), max(xs), max(ys)],
    }


def paint_korean(pixels: list[list[int]], ink: set[tuple[int, int]], chrome: set[tuple[int, int]]) -> dict[str, int]:
    shadow: set[tuple[int, int]] = set()
    for x, y in ink:
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                sx, sy = x + dx, y + dy
                if (sx, sy) in ink:
                    continue
                if (sx, sy) in chrome or not (0 <= sx < 40 and 0 <= sy < 16):
                    continue
                pixels[sy][sx] = analysis.SHADOW_INDEX
                shadow.add((sx, sy))
    face_pixels = 0
    for x, y in ink:
        gate((x, y) not in chrome, f"Korean face would overwrite chrome at {x},{y}")
        pixels[y][x] = analysis.FACE_INDEX
        face_pixels += 1
    gate(face_pixels == len(ink), "face paint count drifted")
    return {
        "shadow_pixels": len(shadow),
        "face_pixels": face_pixels,
        "shadow_geometry": "8-neighbour contour from Korean ink",
    }


def render_badge(pixels: list[list[int]], scale: int = 8) -> Image.Image:
    image = Image.new("RGB", (40, 16), (0, 0, 0))
    for y, row in enumerate(pixels):
        for x, value in enumerate(row):
            image.putpixel((x, y), PREVIEW_RGB.get(value, (40, 40, 40)))
    return image.resize((40 * scale, 16 * scale), Image.Resampling.NEAREST)


def build_preview(
    before: dict[str, list[list[int]]],
    plaque: dict[str, list[list[int]]],
    after: dict[str, list[list[int]]],
    path: Path,
) -> None:
    scale = 8
    cell_w, cell_h = 40 * scale, 16 * scale
    image = Image.new("RGB", (32 + cell_w * 3, 28 + (cell_h + 28) * len(LABELS)), (24, 26, 30))
    draw = ImageDraw.Draw(image)
    draw.text((8, 6), "JP  ->  ID clone (well+round)  ->  KO Galmuri11, 8-neighbour shadow", fill=(230, 230, 230))
    y = 24
    for spec in LABELS:
        key = spec["source"]
        boards = (before[key], plaque[key], after[key])
        labels = (f"JP {spec['source']}", "ID clone", f"KO {spec['translation']}")
        for column, (board, caption) in enumerate(zip(boards, labels, strict=True)):
            x = 8 + column * (cell_w + 8)
            draw.text((x, y), caption, fill=(210, 210, 210))
            image.paste(render_badge(board, scale), (x, y + 14))
        y += cell_h + 28
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--main", type=Path, default=MAIN_ROM)
    parser.add_argument("--main-sav", type=Path, default=MAIN_SAV)
    parser.add_argument("--jp", type=Path, default=JP_ROM)
    parser.add_argument("--out", type=Path, default=OUT_ROM)
    parser.add_argument("--out-sav", type=Path, default=OUT_SAV)
    parser.add_argument("--preview", type=Path, default=OUT_PREVIEW)
    parser.add_argument("--manifest", type=Path, default=OUT_MANIFEST)
    args = parser.parse_args()

    main_rom = args.main.read_bytes()
    jp = args.jp.read_bytes()
    manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    trace = json.loads(TRACE.read_text(encoding="utf-8"))
    gate(sha256(main_rom) == EXPECTED_MAIN_SHA256, f"main TIP hash drift: {sha256(main_rom)}")
    gate(manifest.get("sha256") == EXPECTED_MAIN_SHA256, "main TIP manifest hash drift")
    gate(sha256(jp) == EXPECTED_JP_SHA256, "Japanese ROM identity drift")
    gate(trace["verification"]["result"] == "PASS", "ownership trace is not PASS")
    gate(trace["similar_40x16"]["identified_source"] == "待機", "extra badge identity drift")
    gate(args.main_sav.is_file(), "canonical main SAV is missing")

    patched = bytearray(main_rom)
    with ZipFile(FONT_ZIP) as archive:
        font = fontpair.load_bdf(archive, FONT_MEMBER)

    id_badge = read_badge(main_rom, tuple(analysis.ID_SRC_TILES))
    yellow_plaque = id_yellow_template(id_badge)
    id_cap_drift = [
        (x, y, id_badge[y][x], yellow_plaque[y][x])
        for y in range(16)
        for x in CAP_X
        if id_badge[y][x] != yellow_plaque[y][x]
    ]
    gate(not id_cap_drift, f"letter strip changed ID rounded caps: {id_cap_drift[:8]}")
    reports = []
    before_pixels = {}
    plaque_pixels = {}
    after_pixels = {}
    allowed = set()
    for spec in LABELS:
        tiles = tuple(spec["tiles"])
        before = read_badge(main_rom, tiles)
        source = read_badge(jp, tiles)
        gate(before == source, f"main badge already differs from JP: {spec['source']}")
        pixels = [row[:] for row in before]
        chrome = chrome_mask(before)
        restored = restore_id_badge(pixels, before, yellow_plaque)
        plaque = [row[:] for row in pixels]
        ink, font_info = render_korean(spec["translation"], font, chrome)
        painted = paint_korean(pixels, ink, chrome)
        cap_after = [
            (x, y, pixels[y][x], yellow_plaque[y][x])
            for y in range(16)
            for x in CAP_X
            if pixels[y][x] != yellow_plaque[y][x]
        ]
        gate(not cap_after, f"Korean paint disturbed ID round caps: {spec['source']} {cap_after[:8]}")
        leftover_jp = [
            (x, y)
            for y in range(analysis.ERASE_Y[0], analysis.ERASE_Y[1] + 1)
            for x in range(analysis.ERASE_X[0], analysis.ERASE_X[1] + 1)
            if before[y][x] == analysis.FACE_INDEX
            and pixels[y][x] == analysis.FACE_INDEX
            and (x, y) not in ink
        ]
        gate(not leftover_jp, f"Japanese glyph remnant remains beside Korean ink: {spec['source']} {leftover_jp[:8]}")
        contour = {
            (x + dx, y + dy)
            for x, y in ink
            for dy in (-1, 0, 1)
            for dx in (-1, 0, 1)
            if not (dx == 0 and dy == 0)
        } - ink
        orphan_dark = [
            (x, y)
            for y in range(1, 15)
            for x in range(analysis.INTERIOR_X[0], analysis.INTERIOR_X[1] + 1)
            if pixels[y][x] == analysis.SHADOW_INDEX and (x, y) not in contour
        ]
        gate(not orphan_dark, f"dark pixels outside Korean contour: {spec['source']} {orphan_dark[:8]}")
        write_badge(patched, tiles, pixels)
        after = read_badge(bytes(patched), tiles)
        gate(after == pixels, f"round-trip encode failed: {spec['source']}")
        before_pixels[spec["source"]] = before
        after_pixels[spec["source"]] = after
        plaque_pixels[spec["source"]] = plaque
        for tile_id in tiles:
            start = analysis.GRAPHICS_OFFSET + tile_id * analysis.TILE_BYTES
            allowed.update(range(start, start + analysis.TILE_BYTES))
        reports.append(
            {
                "source": spec["source"],
                "translation": spec["translation"],
                "source_tiles": [f"0x{tile_id:02X}" for tile_id in tiles],
                "file_offset": f"0x{analysis.GRAPHICS_OFFSET + tiles[0] * analysis.TILE_BYTES:08X}",
                "restore": restored,
                "japanese_glyph_remnant_outside_korean_ink": 0,
                "font": font_info,
                "paint": painted,
                "before_sha256": sha256(b"".join(analysis.encode_tile(tile) for tile in analysis.split_40x16_1d(before))),
                "after_sha256": sha256(b"".join(analysis.encode_tile(tile) for tile in analysis.split_40x16_1d(after))),
            }
        )

    changed = [index for index, (left, right) in enumerate(zip(main_rom, patched, strict=True)) if left != right]
    gate(changed and set(changed) <= allowed, "patch escaped the 回避/待機 graphic tiles")
    for tile_id in analysis.ID_SRC_TILES:
        start = analysis.GRAPHICS_OFFSET + tile_id * analysis.TILE_BYTES
        gate(bytes(patched[start : start + analysis.TILE_BYTES]) == main_rom[start : start + analysis.TILE_BYTES], "ID badge tiles changed")
    gate(bytes(patched[analysis.RESOURCE_OFFSET : analysis.GRAPHICS_OFFSET]) == main_rom[analysis.RESOURCE_OFFSET : analysis.GRAPHICS_OFFSET], "A8C004 header/frame table changed")
    gate(bytes(patched[analysis.PALETTE_OFFSET : analysis.PALETTE_OFFSET + 0x60]) == main_rom[analysis.PALETTE_OFFSET : analysis.PALETTE_OFFSET + 0x60], "A8C004 live palettes changed")
    original_half_changed = [index for index in changed if index < 16 * 1024 * 1024]
    gate(all(index >= analysis.GRAPHICS_OFFSET for index in original_half_changed), "unexpected original-half change outside A8C004 graphics")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(patched)
    shutil.copy2(args.main_sav, args.out_sav)
    gate(args.out_sav.read_bytes() == args.main_sav.read_bytes(), "test SAV is not a byte-exact copy of the canonical main SAV")
    gate(args.main.read_bytes() == main_rom, "canonical main TIP was modified")
    build_preview(before_pixels, plaque_pixels, after_pixels, args.preview)

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_battle_forecast_evade_obj_ko_candidate",
        "parent_main_tip_sha256": EXPECTED_MAIN_SHA256,
        "trace": str(TRACE.relative_to(ADVANCE_ROOT)).replace("\\", "/"),
        "font": FONT_MEMBER,
        "style": {
            "face_index": analysis.FACE_INDEX,
            "shadow_index": analysis.SHADOW_INDEX,
            "shadow_geometry": "clone full ID badge (yellow well + rounded caps), then 8-neighbour contour in index 1 around Korean ink",
            "well_fill": WELL_FILL,
            "well_fill_by_row": WELL_FILL_BY_ROW,
            "id_badge_preserved": True,
            "id_round_caps_cloned": True,
            "first_candidate_x31_leak_fixed": True,
        },
        "labels": reports,
        "changed_bytes": len(changed),
        "output": {"path": str(args.out.relative_to(ADVANCE_ROOT)).replace("\\", "/"), "size": len(patched), "sha256": sha256(patched)},
        "save": {
            "path": str(args.out_sav.relative_to(ADVANCE_ROOT)).replace("\\", "/"),
            "size": args.out_sav.stat().st_size,
            "sha256": sha256(args.out_sav.read_bytes()),
            "copied_byte_exact": True,
        },
        "preview": str(args.preview.relative_to(ADVANCE_ROOT)).replace("\\", "/"),
        "verification": {
            "result": "PASS",
            "main_tip_hash_gated": True,
            "ownership_trace_pass": True,
            "回避_and_待機_id_badge_cloned_then_repainted": True,
            "japanese_face_cleared_including_x32_cap_leak": True,
            "dark_well_replaced_with_id_yellow_ramp": True,
            "id_round_caps_cloned": True,
            "shadow_rebuilt_from_korean_ink_contour": True,
            "ID_tiles_byte_exact": True,
            "header_frame_table_byte_exact": True,
            "live_palettes_byte_exact": True,
            "copied_sav_byte_exact": True,
            "canonical_main_tip_modified": False,
        },
    }
    args.manifest.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "result": "PASS",
                "output": report["output"],
                "changed_bytes": len(changed),
                "labels": [(row["source"], row["translation"], row["paint"]) for row in reports],
                "preview": report["preview"],
                "save_byte_exact": True,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
