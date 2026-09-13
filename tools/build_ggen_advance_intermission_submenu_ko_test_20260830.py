#!/usr/bin/env python3
"""Add Korean green submenu OBJ rows to the approved intermission circle test."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from zipfile import ZipFile

from PIL import Image, ImageDraw

THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_intermission_submenu_states_20260830 as submenu
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
import test_ggen_advance_font_pair as fontpair

PARENT_ROM = ROOT / "outputs" / "20260830_ggen_advance_intermission_menu" / "ggen_advance_intermission_menu_ko_tile_test_20260830.gba"
SOURCE_SAV = ROOT / "SD Gundam GGeneration Advance (Korean).sav"
FONT_ZIP = ROOT / "assets" / "fonts" / "Galmuri.zip"
OUT_DIR = ROOT / "outputs" / "20260830_ggen_advance_intermission_menu"
DEFAULT_OUT = OUT_DIR / "ggen_advance_intermission_menu_ko_full_bg_test_20260830.gba"
DEFAULT_SAV = OUT_DIR / "ggen_advance_intermission_menu_ko_full_bg_test_20260830.sav"
DEFAULT_MANIFEST = ROOT / "analysis" / "ggen_advance_intermission_menu_ko_full_bg_test_20260830.json"
DEFAULT_PREVIEW = OUT_DIR / "ggen_advance_intermission_submenu_ko_bg_test_preview_20260830.png"

EXPECTED_PARENT_SHA256 = "e29ecdb33979d4641bb3b95768603e48ccf60cfd1c9ab3a9ee270512e31d2ffe"
ATLAS_START = submenu.ATLAS_START
ATLAS_END = submenu.ATLAS_END
FACE = 5
INNER_CONTOUR = 1

TARGETS = {
    1: ["작전", "색적", "진격", "세이브", "로드"],
    2: ["배속", "보급", "일람", "세이브", "로드"],
    3: ["개조", "분해", "설계도", "세이브", "로드"],
}


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def decode_tile(raw: bytes) -> list[list[int]]:
    gate(len(raw) == 32, "4bpp tile size drift")
    return [[(raw[y * 4 + x // 2] >> (4 * (x & 1))) & 15 for x in range(8)] for y in range(8)]


def encode_tile(pixels: list[list[int]]) -> bytes:
    gate(len(pixels) == 8 and all(len(row) == 8 for row in pixels), "4bpp tile canvas drift")
    out = bytearray(32)
    for y in range(8):
        for x in range(0, 8, 2):
            out[y * 4 + x // 2] = pixels[y][x] | (pixels[y][x + 1] << 4)
    return bytes(out)


def put_tile(canvas: list[list[int]], x: int, y: int, raw: bytes) -> None:
    tile = decode_tile(raw)
    for iy in range(8):
        canvas[y * 8 + iy][x * 8:(x + 1) * 8] = tile[iy]


def canvas_tile(canvas: list[list[int]], x: int, y: int) -> bytes:
    return encode_tile([row[x * 8:(x + 1) * 8] for row in canvas[y * 8:(y + 1) * 8]])


def obj_bytes(state: bytes) -> bytes:
    return state[statefmt.STATE_VRAM + statefmt.OBJ_VRAM:statefmt.STATE_IWRAM]


def extract_row(state: bytes, row_index: int) -> tuple[list[list[int]], dict[tuple[int, int], int], int]:
    entries = submenu.row_objects(state)[row_index]
    obj = obj_bytes(state)
    x0 = min(entry["x"] for entry in entries)
    x1 = max(entry["x"] + entry["width"] for entry in entries)
    width = x1 - x0
    canvas = [[0] * width for _ in range(16)]
    tile_ids: dict[tuple[int, int], int] = {}
    for entry in entries:
        cols, rows = entry["width"] // 8, entry["height"] // 8
        for ty in range(rows):
            for tx in range(cols):
                tile = entry["tile"] + ty * cols + tx
                cx, cy = (entry["x"] - x0) // 8 + tx, ty
                put_tile(canvas, cx, cy, bytes(obj[tile * 32:(tile + 1) * 32]))
                tile_ids[(cx, cy)] = tile
    gate(len(tile_ids) == width // 8 * 2, f"row {row_index} tile composition drift")
    return canvas, tile_ids, entries[0]["palette_bank"]


def glyph_mask(text: str, font: fontpair.BdfFont) -> list[list[bool]]:
    glyphs = []
    for char in text:
        glyph = font.glyphs.get(ord(char))
        gate(glyph is not None, f"Galmuri11 glyph missing: {char}")
        image = font.render(char, 12, 12)
        occupied = [(x, y) for y in range(12) for x in range(12) if image.getpixel((x, y))]
        gate(occupied, f"Galmuri11 rendered blank glyph: {char}")
        x0, y0 = min(x for x, _ in occupied), min(y for _, y in occupied)
        x1, y1 = max(x for x, _ in occupied) + 1, max(y for _, y in occupied) + 1
        glyphs.append([[bool(image.getpixel((x, y))) for x in range(x0, x1)] for y in range(y0, y1)])
    gap = 2
    width = sum(len(glyph[0]) for glyph in glyphs) + gap * (len(glyphs) - 1)
    height = max(len(glyph) for glyph in glyphs)
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


def dilate(mask: list[list[bool]], radius: int) -> list[list[bool]]:
    height, width = len(mask), len(mask[0])
    result = [[False] * width for _ in range(height)]
    for y in range(height):
        for x in range(width):
            if not mask[y][x]:
                continue
            for dy in range(-radius, radius + 1):
                for dx in range(-radius, radius + 1):
                    xx, yy = x + dx, y + dy
                    if 0 <= xx < width and 0 <= yy < height:
                        result[yy][xx] = True
    return result


def source_text_bbox(canvas: list[list[int]]) -> tuple[int, int, int, int]:
    points = [(x, y) for y, row in enumerate(canvas) for x, value in enumerate(row) if 1 <= value <= 5]
    gate(points, "source Japanese glyph mask is empty")
    return (min(x for x, _ in points), min(y for _, y in points),
            max(x for x, _ in points), max(y for _, y in points))


def restore_background(canvas: list[list[int]]) -> tuple[list[list[int]], dict]:
    """Remove the Japanese glyph and its warm/cool drop shadow.

    Indices 1..5 are the green/black glyph family.  The adjacent drop shadow
    uses the row background palette, so cover the complete glyph rectangle
    plus its original right/down shadow and extend the clean row color from
    immediately to the right (or left at an edge).
    """
    result = [row[:] for row in canvas]
    x0, y0, x1, y1 = source_text_bbox(canvas)
    start = max(0, x0 - 2)
    end = min(len(canvas[0]) - 1, x1 + 5)
    top = y0
    bottom = min(len(canvas) - 1, y1 + 1)
    samples = []
    for y in range(top, bottom + 1):
        row = canvas[y]
        right = [(x, row[x]) for x in range(end + 1, len(row)) if row[x] >= 6]
        left = [(x, row[x]) for x in range(start - 1, -1, -1) if row[x] >= 6]
        gate(right or left, f"no clean background sample on submenu scanline {y}")
        sample_x, value = (right or left)[0]
        for x in range(start, end + 1):
            result[y][x] = value
        samples.append({"y": y, "source_x": sample_x, "palette_index": value})
    return result, {"source_text_bbox": [x0, y0, x1, y1],
                    "inpaint_rect": [start, top, end, bottom], "scanline_samples": samples}


def render_label(text: str, width: int, font: fontpair.BdfFont,
                 base: list[list[int]], face_origin: tuple[int, int]) -> tuple[list[list[int]], dict]:
    face = glyph_mask(text, font)
    fw, fh = len(face[0]), len(face)
    ox, oy = face_origin
    gate(ox >= 1 and oy >= 1 and ox + fw + 1 <= width and oy + fh + 1 <= 16,
         f"submenu label does not fit at source position {width}x16: {text}")
    ink = [[False] * width for _ in range(16)]
    for y, row in enumerate(face):
        for x, value in enumerate(row):
            if value:
                ink[oy + y][ox + x] = True
    inner = dilate(ink, 1)
    canvas = [row[:] for row in base]
    for y in range(16):
        for x in range(width):
            if inner[y][x]:
                canvas[y][x] = INNER_CONTOUR
            if ink[y][x]:
                canvas[y][x] = FACE
    coords = [(x, y) for y in range(16) for x in range(width) if inner[y][x]]
    return canvas, {"width": width, "ink_pixels": sum(sum(row) for row in ink),
                    "inner_contour_pixels": sum(sum(row) for row in inner) - sum(sum(row) for row in ink),
                    "outer_highlight_pixels": 0, "face_origin": [ox, oy],
                    "bbox": [min(x for x, _ in coords), min(y for _, y in coords),
                             max(x for x, _ in coords), max(y for _, y in coords)]}


def resource_positions(state: bytes, row_index: int) -> list[tuple[int, int, int]]:
    entries = submenu.row_objects(state)[row_index]
    x0 = min(entry["x"] for entry in entries)
    result = []
    for entry in entries:
        cols, rows = entry["width"] // 8, entry["height"] // 8
        for ty in range(rows):
            for tx in range(cols):
                result.append(((entry["x"] - x0) // 8 + tx, ty, entry["tile"] + ty * cols + tx))
    return result


def desired_resource_raws(canvas: list[list[int]], state: bytes, row_index: int) -> list[bytes]:
    return [canvas_tile(canvas, x, y) for x, y, _ in resource_positions(state, row_index)]


def rgb555(value: int) -> tuple[int, int, int]:
    return tuple(((value >> shift) & 31) * 255 // 31 for shift in (0, 5, 10))


def palette_for(state: bytes, bank: int) -> list[tuple[int, int, int]]:
    pal = state[statefmt.STATE_PALETTE:statefmt.STATE_OAM]
    return [rgb555(int.from_bytes(pal[0x200 + (bank * 16 + i) * 2:0x202 + (bank * 16 + i) * 2], "little")) for i in range(16)]


def make_preview(rows: list[dict], states: list[bytes], out: Path) -> None:
    scale, pad, gap, label_h = 4, 16, 12, 22
    max_width = max(len(row["canvas"][0]) for row in rows) * scale
    panel_h = 5 * (16 * scale + gap) - gap
    image = Image.new("RGB", (pad * 2 + 3 * max_width + 2 * 28, pad * 2 + label_h + panel_h), (32, 32, 32))
    draw = ImageDraw.Draw(image)
    for state_number in (1, 2, 3):
        ox = pad + (state_number - 1) * (max_width + 28)
        draw.text((ox, pad), f"STATE {state_number}", fill=(255, 255, 255))
        state_rows = [row for row in rows if row["state"] == state_number]
        for index, row in enumerate(state_rows):
            canvas = row["canvas"]
            palette = palette_for(states[state_number - 1], row["palette"])
            oy = pad + label_h + index * (16 * scale + gap)
            for y, values in enumerate(canvas):
                for x, value in enumerate(values):
                    color = (15, 15, 15) if value == 0 else palette[value]
                    draw.rectangle((ox + x * scale, oy + y * scale,
                                    ox + (x + 1) * scale - 1, oy + (y + 1) * scale - 1), fill=color)
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
    parser.add_argument("--input", type=Path, default=PARENT_ROM)
    parser.add_argument("--sav", type=Path, default=SOURCE_SAV)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--out-sav", type=Path, default=DEFAULT_SAV)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--preview", type=Path, default=DEFAULT_PREVIEW)
    args = parser.parse_args()

    source = args.input.read_bytes()
    gate(sha256(source) == EXPECTED_PARENT_SHA256, f"parent intermission test hash drift: {sha256(source)}")
    gate(args.sav.is_file() and args.sav.stat().st_size == 8192, "source SAV must be 8 KiB")
    states = [statefmt.parse_png_state(path)[0] for path in submenu.STATES]
    atlas_before = bytes(source[ATLAS_START:ATLAS_END])
    gate(len(atlas_before) == 180 * 32, "C512B8 atlas size drift")
    audit = json.loads(submenu.OUT.read_text(encoding="utf-8"))
    gate(audit.get("result") == "PASS", "submenu source audit is not PASS")

    with ZipFile(FONT_ZIP) as archive:
        font = fontpair.load_bdf(archive, "Galmuri11.bdf")
    pool = list(range(0x008, 0x094))
    assignments: dict[int, bytes] = {}
    preview_rows: list[dict] = []
    mapping = []
    paint = []
    row_specs = []
    for state_number in (1, 2, 3):
        state = states[state_number - 1]
        for row_index, text in enumerate(TARGETS[state_number]):
            if state_number > 1 and row_index >= 3:
                continue
            original, tile_ids, palette = extract_row(state, row_index)
            width = max(x for x, _ in tile_ids) * 8 + 8
            restored, background_report = restore_background(original)
            source_bbox = source_text_bbox(original)
            desired, report = render_label(text, width, font, restored,
                                           (source_bbox[0] + 1, source_bbox[1] + 1))
            row_audit = audit["states"][state_number - 1]["rows"][row_index]
            windows = [int(item["file_offset"], 16) for item in row_audit["tilemap_windows"]]
            gate(windows, f"no tilemap window found for state{state_number}/{text}")
            raws = desired_resource_raws(desired, state, row_index)
            gate(all(window + len(raws) * 2 <= ATLAS_START for window in windows),
                 f"tilemap window escapes package metadata for state{state_number}/{text}")
            row_specs.append({"state": state_number, "row": row_index, "text": text,
                              "palette": palette, "canvas": desired, "raws": raws, "windows": windows})
            paint.append({"state": state_number, "row": row_index, "text": text, "palette_bank": palette,
                          "background_restore": background_report, **report})

    unique_raws: list[bytes] = []
    raw_to_tile: dict[bytes, int] = {}
    for spec in row_specs:
        for raw in spec["raws"]:
            if raw not in raw_to_tile:
                unique_raws.append(raw)
                raw_to_tile[raw] = -1
    gate(len(unique_raws) <= len(pool), f"Korean submenu needs {len(unique_raws)} unique tiles; pool has {len(pool)}")
    for tile, raw in zip(pool, unique_raws):
        assignments[tile] = raw
        raw_to_tile[raw] = tile

    atlas = bytearray(atlas_before)
    for tile, raw in assignments.items():
        atlas[tile * 32:(tile + 1) * 32] = raw
    candidate = bytearray(source)
    candidate[ATLAS_START:ATLAS_END] = atlas
    map_byte_owners: dict[int, tuple[int, str]] = {}
    allowed_changed = set(range(ATLAS_START + pool[0] * 32, ATLAS_START + (pool[-1] + 1) * 32))
    for spec in row_specs:
        ids = [raw_to_tile[raw] for raw in spec["raws"]]
        row_map = []
        for (x, y, obj_tile), tile in zip(resource_positions(states[spec["state"] - 1], spec["row"]), ids):
            row_map.append({"canvas_tile": [x, y], "obj_tile": f"0x{obj_tile:03X}",
                            "source_tile": f"0x{tile:03X}"})
        mapping.append({"state": spec["state"], "row": spec["row"], "text": spec["text"],
                        "tilemap_windows": [f"0x{x:08X}" for x in spec["windows"]], "tiles": row_map})
        for window in spec["windows"]:
            for index, tile in enumerate(ids):
                off = window + index * 2
                encoded = tile.to_bytes(2, "little")
                for byte_index, value in enumerate(encoded):
                    target = off + byte_index
                    owner = f"state{spec['state']}/{spec['text']}"
                    if target in map_byte_owners:
                        gate(map_byte_owners[target][0] == value,
                             f"overlapping tilemap conflict at 0x{target:08X}: {map_byte_owners[target][1]} vs {owner}")
                    map_byte_owners[target] = (value, owner)
                    candidate[target] = value
                    allowed_changed.add(target)
    for spec in row_specs:
        expected_ids = [raw_to_tile[raw] for raw in spec["raws"]]
        for window in spec["windows"]:
            actual_ids = [int.from_bytes(candidate[window + i * 2:window + i * 2 + 2], "little")
                          for i in range(len(expected_ids))]
            gate(actual_ids == expected_ids,
                 f"patched tilemap verification failed at 0x{window:08X} for state{spec['state']}/{spec['text']}")
    changed = [i for i, (old, new) in enumerate(zip(source, candidate)) if old != new]
    gate(changed and all(i in allowed_changed for i in changed), "submenu patch escaped allocated atlas/tilemap bytes")
    gate(candidate[ATLAS_START:ATLAS_START + pool[0] * 32] == source[ATLAS_START:ATLAS_START + pool[0] * 32],
         "atlas prefix outside allocation changed")
    gate(candidate[ATLAS_START + (pool[-1] + 1) * 32:ATLAS_END] == source[ATLAS_START + (pool[-1] + 1) * 32:ATLAS_END],
         "atlas suffix outside allocation changed")

    # Reconstruct each row from the assigned source mapping for a deterministic
    # preview and prove every consumer receives the intended Korean tiles.
    for state_number in (1, 2, 3):
        state = states[state_number - 1]
        for row_index, text in enumerate(TARGETS[state_number]):
            original, tile_ids, palette = extract_row(state, row_index)
            width = max(x for x, _ in tile_ids) * 8 + 8
            restored, _ = restore_background(original)
            source_bbox = source_text_bbox(original)
            desired, _ = render_label(text, width, font, restored,
                                      (source_bbox[0] + 1, source_bbox[1] + 1))
            source_state = state_number if row_index < 3 else 1
            spec = next(item for item in row_specs if item["state"] == source_state and item["row"] == row_index)
            ids = [int.from_bytes(candidate[spec["windows"][0] + i * 2:spec["windows"][0] + i * 2 + 2], "little")
                   for i in range(len(spec["raws"]))]
            rebuilt = [[0] * width for _ in range(16)]
            for (x, y, _), source_tile in zip(resource_positions(state, row_index), ids):
                gate(0 <= source_tile < 180, f"patched source tile out of range: 0x{source_tile:03X}")
                put_tile(rebuilt, x, y, bytes(atlas[source_tile * 32:(source_tile + 1) * 32]))
            gate(rebuilt == desired, f"runtime-composed row differs from desired: state{state_number} {text}")
            preview_rows.append({"state": state_number, "row": row_index, "text": text,
                                 "palette": palette, "canvas": rebuilt})

    output = bytes(candidate)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(output)
    args.out_sav.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(args.sav, args.out_sav)
    gate(args.out_sav.read_bytes() == args.sav.read_bytes(), "copied SAV is not byte-exact")
    make_preview(preview_rows, states, args.preview)

    manifest = {"schema_version": 1, "kind": "ggen_advance_intermission_menu_ko_full_bg_test_20260830", "result": "PASS",
                "source": {"parent_rom": str(args.input.relative_to(ROOT)).replace("\\", "/"),
                           "parent_sha256": sha256(source), "submenu_audit": str(submenu.OUT.relative_to(ROOT)).replace("\\", "/"),
                           "sav": str(args.sav.relative_to(ROOT)).replace("\\", "/"), "sav_sha256": sha256(args.sav.read_bytes())},
                "output": {"path": str(args.out.relative_to(ROOT)).replace("\\", "/"),
                           "size": len(output), "sha256": sha256(output),
                           "rom": str(args.out.relative_to(ROOT)).replace("\\", "/"), "rom_size": len(output),
                           "rom_sha256": sha256(output), "sav": str(args.out_sav.relative_to(ROOT)).replace("\\", "/"),
                           "sav_size": args.out_sav.stat().st_size, "sav_sha256": sha256(args.out_sav.read_bytes()),
                           "preview": str(args.preview.relative_to(ROOT)).replace("\\", "/")},
                "patch": {"package": "0x08C512B8", "atlas_range": [f"0x{ATLAS_START:08X}", f"0x{ATLAS_END:08X}"],
                          "allocated_atlas_tile_pool": ["0x008", "0x093"],
                          "targets": TARGETS, "font": "Galmuri11.bdf native 11px",
                          "palette_indices": {"face": FACE, "inner_contour": INNER_CONTOUR,
                                              "outer_highlight": None},
                          "layout": "Korean face anchored to each source Japanese glyph bbox; no additional diagonal offset",
                          "background": "source row retained; Japanese glyph/shadow span scanline-inpainted from adjacent row colors",
                          "assigned_source_tiles": [f"0x{x:03X}" for x in sorted(assignments)],
                          "mapping": mapping, "paint": paint,
                          "changed_bytes": len(changed), "changed_ranges": changed_ranges(changed)},
                "verification": {"result": "PASS", "parent_circle_test_hash_verified": True,
                                 "all_11_unique_rows_patched": True, "save_load_shared_once": True,
                                 "all_15_runtime_rows_reconstructed_exactly": True,
                                 "changes_restricted_to_C512B8_atlas_and_detected_tilemaps": True,
                                 "atlas_tiles_outside_0x008_to_0x093_preserved": True, "palette_modified": False,
                                 "source_background_restored": True, "white_outer_highlight_removed": True,
                                 "no_additional_diagonal_offset": True,
                                 "circle_menu_C493B4_preserved": True, "copied_sav_byte_exact": True,
                                 "canonical_main_tip_modified": False}}
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "rom": str(args.out), "rom_sha256": sha256(output),
                      "sav": str(args.out_sav), "sav_sha256": sha256(args.out_sav.read_bytes()),
                      "preview": str(args.preview), "manifest": str(args.manifest),
                      "assigned_tiles": len(assignments), "changed_bytes": len(changed)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
