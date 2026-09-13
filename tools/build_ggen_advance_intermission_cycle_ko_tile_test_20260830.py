#!/usr/bin/env python3
"""Build a non-canonical Korean intermission cycle tile test ROM and SAV."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from collections import Counter
from pathlib import Path
from zipfile import ZipFile

from PIL import Image, ImageDraw

THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_intermission_cycle_states_20260830 as analysis
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
import test_ggen_advance_font_pair as fontpair

MAIN_ROM = ROOT / "SD Gundam GGeneration Advance (Korean).gba"
SOURCE_SAV = ROOT / "SD Gundam GGeneration Advance (Korean).sav"
FONT_ZIP = ROOT / "assets" / "fonts" / "Galmuri.zip"
OUT_DIR = ROOT / "outputs" / "20260830_ggen_advance_intermission_menu"
DEFAULT_OUT = OUT_DIR / "ggen_advance_intermission_menu_ko_tile_test_20260830.gba"
DEFAULT_SAV = OUT_DIR / "ggen_advance_intermission_menu_ko_tile_test_20260830.sav"
DEFAULT_MANIFEST = ROOT / "analysis" / "ggen_advance_intermission_menu_ko_tile_test_20260830.json"
DEFAULT_PREVIEW = OUT_DIR / "ggen_advance_intermission_menu_ko_tile_test_preview_20260830.png"

EXPECTED_MAIN_SHA256 = "857b8f3da9fb727fb3e821f6c1218b7f2aed95c01a937be5291e663fa89b6f20"
ATLAS_START = analysis.ATLAS_START
ATLAS_END = analysis.ATLAS_END
ATLAS_TILES = (ATLAS_END - ATLAS_START) // 32
FACE = 9
CONTOUR = 6
# The native ornamental kanji use a four-tone dark-to-bright stack: 6 is the
# deepest contour, 7/8 are stepped shadow/highlight tones, and 9 is the yellow
# face.  Masking only 6/9 leaves blocky Japanese shadow residue.
JP_GLYPH = {1, 6, 7, 8, 9}
LABELS = {"operation": "작전", "formation": "편성", "development": "개발"}

FOCUS_STATES = {"operation": 0, "formation": 1, "development": 2}
FOCUS_SOURCE_RANGES = {"operation": range(0x000, 0x03C), "formation": range(0x070, 0x082),
                       "development": range(0x082, 0x094)}
FOCUS_POSITIONS = [(x, y) for y in range(3, 6) for x in range(1, 7)]

NONFOCUS_SPECS = {
    "formation": {"state": 2, "objects": [14, 15, 16, 17], "source": range(0x03C, 0x05C),
                  "positions": [(x, y) for y in range(2, 5) for x in range(1, 5)]},
    "development": {"state": 0, "objects": [14, 15, 16, 17], "source": range(0x05C, 0x065),
                    "positions": [(1, 2), (2, 2), (3, 2), (1, 3), (2, 3), (3, 3),
                                  (4, 2), (4, 3), (3, 4)]},
    "operation": {"state": 1, "objects": [18, 19, 20, 21], "source": range(0x065, 0x070),
                  "positions": [(1, 2), (2, 2), (3, 2), (1, 3), (2, 3), (3, 3),
                                (4, 2), (4, 3), (1, 4), (2, 4), (3, 4)]},
}


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def decode_tile(raw: bytes) -> list[list[int]]:
    gate(len(raw) == 32, "4bpp tile size drift")
    pixels = [[0] * 8 for _ in range(8)]
    for y in range(8):
        for x in range(8):
            value = raw[y * 4 + x // 2]
            pixels[y][x] = (value >> (4 * (x & 1))) & 15
    return pixels


def encode_tile(pixels: list[list[int]]) -> bytes:
    gate(len(pixels) == 8 and all(len(row) == 8 for row in pixels), "4bpp tile canvas drift")
    out = bytearray(32)
    for y in range(8):
        for x in range(0, 8, 2):
            out[y * 4 + x // 2] = pixels[y][x] | (pixels[y][x + 1] << 4)
    return bytes(out)


def canvas_tile(canvas: list[list[int]], x: int, y: int) -> bytes:
    return encode_tile([row[x * 8:(x + 1) * 8] for row in canvas[y * 8:(y + 1) * 8]])


def put_tile(canvas: list[list[int]], x: int, y: int, raw: bytes) -> None:
    tile = decode_tile(raw)
    for iy in range(8):
        canvas[y * 8 + iy][x * 8:(x + 1) * 8] = tile[iy]


def obj_bytes(state: bytes) -> bytes:
    return state[statefmt.STATE_VRAM + statefmt.OBJ_VRAM:statefmt.STATE_IWRAM]


def extract_focus(state: bytes) -> list[list[int]]:
    obj = obj_bytes(state)
    canvas = [[0] * 64 for _ in range(64)]
    for tile in range(64):
        put_tile(canvas, tile % 8, tile // 8, bytes(obj[tile * 32:(tile + 1) * 32]))
    return canvas


def extract_group(state: bytes, indices: list[int]) -> tuple[list[list[int]], dict[tuple[int, int], int]]:
    oam = state[statefmt.STATE_OAM:statefmt.STATE_VRAM]
    obj = obj_bytes(state)
    entries = [statefmt.parse_oam_entry(oam, index) for index in indices]
    x0, y0 = min(e["x"] for e in entries), min(e["y"] for e in entries)
    canvas = [[0] * 48 for _ in range(48)]
    tile_ids: dict[tuple[int, int], int] = {}
    for entry in entries:
        cols, rows = entry["width"] // 8, entry["height"] // 8
        for ty in range(rows):
            for tx in range(cols):
                tile = entry["tile"] + ty * cols + tx
                cx, cy = (entry["x"] - x0) // 8 + tx, (entry["y"] - y0) // 8 + ty
                put_tile(canvas, cx, cy, bytes(obj[tile * 32:(tile + 1) * 32]))
                tile_ids[(cx, cy)] = tile
    gate(len(tile_ids) == 36, "nonfocus 48x48 composition did not contain 36 tiles")
    return canvas, tile_ids


def infer_background(canvases: list[list[list[int]]], rect: tuple[int, int, int, int]) -> tuple[list[list[int]], int]:
    x0, y0, x1, y1 = rect
    background = [row[:] for row in canvases[0]]
    missing: list[tuple[int, int]] = []
    known: list[tuple[int, int]] = []
    for y in range(y0, y1):
        for x in range(x0, x1):
            candidates = [canvas[y][x] for canvas in canvases if canvas[y][x] not in JP_GLYPH]
            if candidates:
                background[y][x] = Counter(candidates).most_common(1)[0][0]
                known.append((x, y))
            else:
                missing.append((x, y))
    gate(known, "no native background samples survived glyph masking")
    for x, y in missing:
        same_row = [(abs(x - kx), kx, ky) for kx, ky in known if ky == y]
        pool = same_row or [(abs(x - kx) + abs(y - ky) * 2, kx, ky) for kx, ky in known]
        _, kx, ky = min(pool)
        background[y][x] = background[ky][kx]
    return background, len(missing)


def glyph_mask(text: str, font: fontpair.BdfFont, scale: int) -> list[list[bool]]:
    glyphs = []
    for char in text:
        glyph = font.glyphs.get(ord(char))
        gate(glyph is not None, f"Galmuri11 glyph missing: {char}")
        image = font.render(char, glyph.width, glyph.height)
        mask = [[bool(image.getpixel((x, y))) for x in range(image.width)] for y in range(image.height)]
        if scale > 1:
            mask = [[mask[y // scale][x // scale] for x in range(image.width * scale)]
                    for y in range(image.height * scale)]
        glyphs.append(mask)
    gap = 2
    width = sum(len(g[0]) for g in glyphs) + gap
    height = max(len(g) for g in glyphs)
    result = [[False] * width for _ in range(height)]
    cursor = 0
    for glyph in glyphs:
        top = (height - len(glyph)) // 2
        for y, row in enumerate(glyph):
            for x, value in enumerate(row):
                if value:
                    result[top + y][cursor + x] = True
        cursor += len(glyph[0]) + gap
    return result


def paint_label(background: list[list[int]], text: str, font: fontpair.BdfFont,
                rect: tuple[int, int, int, int], scale: int) -> tuple[list[list[int]], dict]:
    canvas = [row[:] for row in background]
    x0, y0, x1, y1 = rect
    mask = glyph_mask(text, font, scale)
    width, height = len(mask[0]), len(mask)
    ox, oy = x0 + (x1 - x0 - width) // 2, y0 + (y1 - y0 - height) // 2
    ink = [[False] * len(canvas[0]) for _ in canvas]
    for y, row in enumerate(mask):
        for x, value in enumerate(row):
            if value:
                ink[oy + y][ox + x] = True
    outline = [[False] * len(canvas[0]) for _ in canvas]
    for y in range(len(canvas)):
        for x in range(len(canvas[0])):
            if not ink[y][x]:
                continue
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    xx, yy = x + dx, y + dy
                    if 0 <= xx < len(canvas[0]) and 0 <= yy < len(canvas) and not ink[yy][xx]:
                        outline[yy][xx] = True
    coords = [(x, y) for y in range(len(canvas)) for x in range(len(canvas[0])) if ink[y][x] or outline[y][x]]
    gate(coords and min(x for x, _ in coords) >= x0 and max(x for x, _ in coords) < x1 and
         min(y for _, y in coords) >= y0 and max(y for _, y in coords) < y1, f"{text} escaped replacement rectangle")
    for y in range(len(canvas)):
        for x in range(len(canvas[0])):
            if outline[y][x]:
                canvas[y][x] = CONTOUR
            if ink[y][x]:
                canvas[y][x] = FACE
    return canvas, {"ink_pixels": sum(sum(row) for row in ink), "contour_pixels": sum(sum(row) for row in outline),
                    "bbox": [min(x for x, _ in coords), min(y for _, y in coords),
                             max(x for x, _ in coords), max(y for _, y in coords)]}


def source_for_runtime(atlas: bytes, raw: bytes, allowed: range, label: str) -> int:
    hits = [tile for tile in allowed if atlas[tile * 32:(tile + 1) * 32] == raw]
    gate(len(hits) == 1, f"{label} source mapping is not unique: {hits}")
    return hits[0]


def runtime_raw(state: bytes, tile: int) -> bytes:
    obj = obj_bytes(state)
    return bytes(obj[tile * 32:(tile + 1) * 32])


def write_source_tile(atlas: bytearray, assignments: dict[int, bytes], source: int, raw: bytes, owner: str) -> None:
    if source in assignments:
        gate(assignments[source] == raw, f"shared atlas tile 0x{source:03X} conflicts at {owner}")
    assignments[source] = raw
    atlas[source * 32:(source + 1) * 32] = raw


def rgb555(value: int) -> tuple[int, int, int]:
    return tuple(((value >> shift) & 31) * 255 // 31 for shift in (0, 5, 10))


def palette_for(state: bytes, bank: int) -> list[tuple[int, int, int]]:
    pal = state[statefmt.STATE_PALETTE:statefmt.STATE_OAM]
    return [rgb555(int.from_bytes(pal[0x200 + (bank * 16 + i) * 2:0x202 + (bank * 16 + i) * 2], "little")) for i in range(16)]


def draw_canvas(image: Image.Image, canvas: list[list[int]], palette: list[tuple[int, int, int]], ox: int, oy: int, scale: int) -> None:
    draw = ImageDraw.Draw(image)
    for y, row in enumerate(canvas):
        for x, value in enumerate(row):
            draw.rectangle((ox + x * scale, oy + y * scale, ox + (x + 1) * scale - 1, oy + (y + 1) * scale - 1), fill=palette[value])


def make_preview(focus: dict[str, list[list[int]]], normal: dict[str, list[list[int]]], states: list[bytes], out: Path) -> None:
    scale, pad, label_h, gap = 4, 16, 22, 20
    fw, fh = 64 * scale, 64 * scale
    nw, nh = 48 * scale, 48 * scale
    image = Image.new("RGB", (pad * 2 + 3 * fw + 2 * gap, pad * 3 + label_h * 2 + fh + nh), (28, 28, 28))
    draw = ImageDraw.Draw(image)
    p_focus, p_normal = palette_for(states[0], 0), palette_for(states[0], 1)
    names = [("operation", "작전"), ("formation", "편성"), ("development", "개발")]
    for i, (key, label) in enumerate(names):
        x = pad + i * (fw + gap)
        draw.text((x, pad), f"FOCUS {label}", fill=(255, 255, 255))
        draw_canvas(image, focus[key], p_focus, x, pad + label_h, scale)
        nx = x + (fw - nw) // 2
        ny = pad * 2 + label_h * 2 + fh
        draw.text((nx, ny - label_h), f"NORMAL {label}", fill=(255, 255, 255))
        draw_canvas(image, normal[key], p_normal, nx, ny, scale)
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out)


def changed_ranges(offsets: list[int]) -> list[list[str]]:
    if not offsets:
        return []
    result, start, previous = [], offsets[0], offsets[0]
    for value in offsets[1:]:
        if value != previous + 1:
            result.append([f"0x{start:08X}", f"0x{previous + 1:08X}"])
            start = value
        previous = value
    result.append([f"0x{start:08X}", f"0x{previous + 1:08X}"])
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=MAIN_ROM)
    parser.add_argument("--sav", type=Path, default=SOURCE_SAV)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--out-sav", type=Path, default=DEFAULT_SAV)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--preview", type=Path, default=DEFAULT_PREVIEW)
    args = parser.parse_args()

    source = args.input.read_bytes()
    gate(sha256(source) == EXPECTED_MAIN_SHA256, f"Main TIP hash drift: {sha256(source)}")
    gate(args.sav.is_file() and args.sav.stat().st_size == 8192, "source SAV must be the expected 8 KiB file")
    states = [statefmt.parse_png_state(path)[0] for path in analysis.STATES]
    atlas_before = bytes(source[ATLAS_START:ATLAS_END])
    gate(len(atlas_before) == ATLAS_TILES * 32, "C493B4 atlas size drift")

    focus_original = {name: extract_focus(states[index]) for name, index in FOCUS_STATES.items()}
    normal_original = {}
    normal_tile_ids = {}
    for name, spec in NONFOCUS_SPECS.items():
        normal_original[name], normal_tile_ids[name] = extract_group(states[spec["state"]], spec["objects"])

    focus_background, focus_missing = infer_background(list(focus_original.values()), (8, 24, 56, 48))
    normal_background, normal_missing = infer_background(list(normal_original.values()), (8, 16, 40, 40))
    with ZipFile(FONT_ZIP) as archive:
        font = fontpair.load_bdf(archive, "Galmuri11.bdf")
    focus_new, normal_new, paint = {}, {}, {}
    for name, text in LABELS.items():
        focus_new[name], focus_report = paint_label(focus_background, text, font, (8, 24, 56, 48), 2)
        normal_new[name], normal_report = paint_label(normal_background, text, font, (8, 16, 40, 32), 1)
        paint[name] = {"focus": focus_report, "normal": normal_report}

    atlas = bytearray(atlas_before)
    assignments: dict[int, bytes] = {}
    mapping_report = {"focus": {}, "normal": {}}
    for name, state_index in FOCUS_STATES.items():
        mappings = []
        for x, y in FOCUS_POSITIONS:
            obj_tile = y * 8 + x
            source_tile = source_for_runtime(atlas_before, runtime_raw(states[state_index], obj_tile),
                                             FOCUS_SOURCE_RANGES[name], f"focus {name} ({x},{y})")
            desired = canvas_tile(focus_new[name], x, y)
            write_source_tile(atlas, assignments, source_tile, desired, f"focus {name}")
            mappings.append({"canvas_tile": [x, y], "obj_tile": f"0x{obj_tile:03X}", "source_tile": f"0x{source_tile:03X}"})
        mapping_report["focus"][name] = mappings

    for name, spec in NONFOCUS_SPECS.items():
        mappings = []
        state = states[spec["state"]]
        for x, y in spec["positions"]:
            obj_tile = normal_tile_ids[name][(x, y)]
            source_tile = source_for_runtime(atlas_before, runtime_raw(state, obj_tile), spec["source"],
                                             f"normal {name} ({x},{y})")
            desired = canvas_tile(normal_new[name], x, y)
            write_source_tile(atlas, assignments, source_tile, desired, f"normal {name}")
            mappings.append({"canvas_tile": [x, y], "obj_tile": f"0x{obj_tile:03X}", "source_tile": f"0x{source_tile:03X}"})
        mapping_report["normal"][name] = mappings

    # Common focus animation/glow tiles are explicitly outside all assignments.
    gate(not set(assignments).intersection(range(0x094, 0x0A7)), "focus overlay tile was assigned")
    candidate = bytearray(source)
    candidate[ATLAS_START:ATLAS_END] = atlas
    changed = [i for i, (old, new) in enumerate(zip(source, candidate)) if old != new]
    gate(changed and all(ATLAS_START <= i < ATLAS_END for i in changed), "test patch escaped C493B4 raw atlas")
    gate(candidate[ATLAS_END:] == source[ATLAS_END:] and candidate[:ATLAS_START] == source[:ATLAS_START],
         "bytes outside C493B4 atlas changed")

    output = bytes(candidate)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(output)
    args.out_sav.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(args.sav, args.out_sav)
    make_preview(focus_new, normal_new, states, args.preview)
    source_sav = args.sav.read_bytes()
    copied_sav = args.out_sav.read_bytes()
    gate(copied_sav == source_sav, "copied SAV is not byte-exact")

    manifest = {
        "schema_version": 1, "kind": "ggen_advance_intermission_menu_ko_tile_test_20260830", "result": "PASS",
        "source": {"rom": str(args.input.relative_to(ROOT)).replace("\\", "/"), "rom_sha256": sha256(source),
                   "sav": str(args.sav.relative_to(ROOT)).replace("\\", "/"), "sav_size": len(source_sav),
                   "sav_sha256": sha256(source_sav), "states": [str(p.relative_to(ROOT)).replace("\\", "/") for p in analysis.STATES]},
        "output": {"rom": str(args.out.relative_to(ROOT)).replace("\\", "/"), "rom_size": len(output),
                   "rom_sha256": sha256(output), "sav": str(args.out_sav.relative_to(ROOT)).replace("\\", "/"),
                   "sav_size": len(copied_sav), "sav_sha256": sha256(copied_sav),
                   "preview": str(args.preview.relative_to(ROOT)).replace("\\", "/")},
        "patch": {"package": "0x08C493B4", "atlas_range": [f"0x{ATLAS_START:08X}", f"0x{ATLAS_END:08X}"],
                  "labels": LABELS, "font": "Galmuri11.bdf; focus 2x native, normal native",
                  "face_index": FACE, "contour_index": CONTOUR,
                  "focus_background_unknown_pixels_inpainted": focus_missing,
                  "normal_background_unknown_pixels_inpainted": normal_missing,
                  "assigned_source_tiles": [f"0x{x:03X}" for x in sorted(assignments)],
                  "mapping": mapping_report, "paint": paint,
                  "changed_bytes": len(changed), "changed_ranges": changed_ranges(changed)},
        "verification": {"result": "PASS", "parent_main_sha_verified": True, "rom_size_preserved": True,
                         "changes_restricted_to_C493B4_raw_atlas": True, "focus_overlay_094_A6_preserved": True,
                         "palette_preserved": True, "all_three_focus_variants_patched": True,
                         "all_three_nonfocus_variants_patched": True, "copied_sav_byte_exact": True,
                         "canonical_main_tip_modified": False},
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "rom": str(args.out), "rom_sha256": sha256(output),
                      "sav": str(args.out_sav), "sav_sha256": sha256(copied_sav),
                      "preview": str(args.preview), "manifest": str(args.manifest),
                      "changed_bytes": len(changed), "assigned_tiles": len(assignments),
                      "background_inpaint": {"focus": focus_missing, "normal": normal_missing}}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
