#!/usr/bin/env python3
"""Replace the LANDFORM 回避 32x16 badge with Galmuri11 회피.

ss2 binds the 4x2 to unique uncompressed tiles 55-58 / 67-70 in the private
sheet at 0x000E3154.  Each tile payload has exactly one ROM hit, so the
Japanese kanji can be painted in place.  Palette bank 11 roles follow
luminance: 11 pale-yellow background, 10 gold face, 5 dark-brown shadow.
Terrain-name text (海) is left untouched; that path is deferred.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path
from zipfile import ZipFile

from PIL import Image

THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
import build_ggen_advance_turn_ability_overlays_20260905 as raster
import test_ggen_advance_font_pair as fontpair
from ggen_advance_project_paths import (
    FONT_ZIP,
    MAIN_TIP_MANIFEST,
    MAIN_TIP_ROM,
    ORIGINAL_ROM,
    advance_relative,
)

EXPECTED_MAIN_SHA256 = "33a0ade03bbf336097b8c41384213a20c45bfeeda05449a9776b6ca3a6072824"
EXPECTED_JP_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"
GFX = 0x000E3154
EVADE_TILES = (55, 56, 57, 58, 67, 68, 69, 70)
# ss2 BG bank 11 luminance: 11 pale yellow, 10 gold, 5 dark brown.
BACKGROUND = 11
FACE = 10
SHADOW = 5
ORIGIN = (4, 2)
CELL = 12
MAIN_SAV = ROOT / "SD Gundam GGeneration Advance (Korean).sav"
STATE = ROOT / "SD Gundam GGeneration Advance (Korean).ss2"
OUT_DIR = ROOT / "outputs" / "20260905_ggen_advance_landform"
OUTPUT = OUT_DIR / "ggen_advance_landform_evade_ko_candidate_20260905.gba"
OUT_SAV = OUT_DIR / "ggen_advance_landform_evade_ko_candidate_20260905.sav"
REPORT = ROOT / "analysis" / "ggen_advance_landform_evade_ko_candidate_20260905.json"
PREVIEW = OUT_DIR / "landform_evade_ko_preview_20260905.png"


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def tile_off(tile: int) -> int:
    return GFX + tile * 32


def find_all(hay: bytes, needle: bytes, limit: int = 8) -> list[int]:
    hits: list[int] = []
    start = 0
    while len(hits) < limit:
        pos = hay.find(needle, start)
        if pos < 0:
            return hits
        hits.append(pos)
        start = pos + 1
    return hits


def stitch(rom: bytes) -> list[list[int]]:
    canvas = [[0] * 32 for _ in range(16)]
    for index, tile in enumerate(EVADE_TILES):
        tx, ty = index % 4, index // 4
        pix = raster.decode_tile(bytes(rom[tile_off(tile) : tile_off(tile) + 32]))
        for y in range(8):
            canvas[ty * 8 + y][tx * 8 : tx * 8 + 8] = pix[y]
    return canvas


def split(canvas: list[list[int]]) -> dict[int, bytes]:
    out: dict[int, bytes] = {}
    for index, tile in enumerate(EVADE_TILES):
        tx, ty = index % 4, index // 4
        pix = [row[tx * 8 : tx * 8 + 8] for row in canvas[ty * 8 : ty * 8 + 8]]
        out[tile] = raster.encode_tile(pix)
    return out


def live_palette(state_path: Path) -> list[tuple[int, int, int]]:
    state, _ = statefmt.parse_png_state(state_path)
    pal = state[statefmt.STATE_PALETTE : statefmt.STATE_OAM]
    return raster.palette_rgb(bytes(pal[11 * 32 : 12 * 32]))


def paint(canvas: list[list[int]], font: fontpair.BdfFont) -> dict[str, object]:
    after = [[BACKGROUND] * 32 for _ in range(16)]
    ink: set[tuple[int, int]] = set()
    x0, y0 = ORIGIN
    for index, char in enumerate("회피"):
        glyph = fontpair.render_12x12_basic(char, font)
        for y in range(CELL):
            for x in range(CELL):
                if glyph.getpixel((x, y)):
                    ink.add((x0 + index * CELL + x, y0 + y))
    gate(ink, "회피 ink is empty")
    dilated = raster.dilate(ink, 32, 16)
    outline_only = dilated - ink
    gate(all(0 <= x < 32 and 0 <= y < 16 for x, y in dilated), "회피 ink/outline leaves the 32x16 badge")
    for x, y in outline_only:
        after[y][x] = SHADOW
    for x, y in ink:
        after[y][x] = FACE
    return {
        "canvas": after,
        "restored_background_pixels": 32 * 16,
        "ink_pixels": len(ink),
        "shadow_pixels": len(outline_only),
        "origin": list(ORIGIN),
        "font": "Galmuri11.bdf",
        "face_index": FACE,
        "shadow_index": SHADOW,
        "background_index": BACKGROUND,
    }


def save_preview(
    before: list[list[int]],
    after: list[list[int]],
    colors: list[tuple[int, int, int]],
    path: Path,
) -> None:
    left = raster.render_canvas(before, colors).resize((256, 128), Image.NEAREST)
    right = raster.render_canvas(after, colors).resize((256, 128), Image.NEAREST)
    gap = Image.new("RGB", (16, 128), (0, 0, 0))
    image = Image.new("RGB", (256 + 16 + 256, 128), (0, 0, 0))
    image.paste(left, (0, 0))
    image.paste(gap, (256, 0))
    image.paste(right, (272, 0))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    japan = ORIGINAL_ROM.read_bytes()
    parent = MAIN_TIP_ROM.read_bytes()
    manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(japan) == EXPECTED_JP_SHA256, "Japanese ROM hash drift")
    gate(len(parent) == 32 * 1024 * 1024, "main TIP size drift")
    gate(sha256(parent) == EXPECTED_MAIN_SHA256, "main TIP hash drift")
    gate(sha256(parent) == manifest["sha256"], "main TIP / manifest drift")
    gate(MAIN_SAV.exists(), "current main SAV missing")

    uniqueness = []
    for tile in EVADE_TILES:
        off = tile_off(tile)
        raw = bytes(parent[off : off + 32])
        gate(raw == bytes(japan[off : off + 32]), f"tile {tile} already diverges from JP")
        jp_hits = find_all(japan, raw)
        main_hits = find_all(parent, raw)
        gate(jp_hits == [off], f"tile {tile} is not unique in JP: {jp_hits}")
        gate(main_hits == [off], f"tile {tile} is not unique in main: {main_hits}")
        uniqueness.append({"tile": tile, "offset": hex(off), "jp_hits": 1, "main_hits": 1})

    before = stitch(parent)
    counts = [0] * 16
    for y in range(16):
        for x in range(32):
            counts[before[y][x]] += 1
    used = {i for i, n in enumerate(counts) if n}
    gate(used == {BACKGROUND, FACE, SHADOW}, "回避 badge uses unexpected palette indices")
    gate(counts[BACKGROUND] > 0 and counts[FACE] > 0 and counts[SHADOW] > 0, "回避 badge is missing a palette role")

    with ZipFile(FONT_ZIP) as archive:
        font = fontpair.load_bdf(archive, "Galmuri11.bdf")
    painted = paint(before, font)
    after = painted["canvas"]
    updates = split(after)
    candidate = bytearray(parent)
    allowed: set[int] = set()
    for tile, payload in updates.items():
        off = tile_off(tile)
        gate(payload != bytes(parent[off : off + 32]), f"tile {tile} did not change")
        gate(find_all(parent, payload) == [], f"painted tile {tile} collides with an existing ROM tile")
        candidate[off : off + 32] = payload
        allowed.update(range(off, off + 32))
        gate(bytes(candidate[off : off + 32]) == payload, f"tile {tile} write failed")
        gate(find_all(bytes(candidate), payload) == [off], f"painted tile {tile} is not unique in candidate")

    changed = [index for index, (a, b) in enumerate(zip(parent, candidate)) if a != b]
    gate(set(changed) <= allowed, "candidate changed outside the unique 回避 tiles")
    gate(sha256(MAIN_TIP_ROM.read_bytes()) == EXPECTED_MAIN_SHA256, "builder mutated main TIP")

    colors = live_palette(STATE)

    def luminance(rgb: tuple[int, int, int]) -> float:
        r, g, b = rgb
        return 0.299 * r + 0.587 * g + 0.114 * b

    gate(luminance(colors[SHADOW]) < luminance(colors[FACE]) < luminance(colors[BACKGROUND]), "ss2 bank 11 luminance order is not shadow < face < background")
    after_counts = [0] * 16
    for y in range(16):
        for x in range(32):
            after_counts[after[y][x]] += 1
    gate(after_counts[BACKGROUND] > after_counts[FACE] > 0, "Korean badge lost the pale-yellow background")
    gate(after_counts[SHADOW] > 0, "Korean badge has no brown shadow")
    save_preview(before, after, colors, PREVIEW)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(candidate)
    shutil.copyfile(MAIN_SAV, OUT_SAV)
    gate(OUT_SAV.read_bytes() == MAIN_SAV.read_bytes(), "companion SAV is not a byte-exact copy of main SAV")
    gate(sha256(MAIN_TIP_ROM.read_bytes()) == EXPECTED_MAIN_SHA256, "main TIP changed after write")

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_landform_evade_ko_candidate_20260905",
        "source": {
            "parent": advance_relative(MAIN_TIP_ROM),
            "parent_sha256": EXPECTED_MAIN_SHA256,
            "japan_sha256": EXPECTED_JP_SHA256,
            "state": advance_relative(STATE),
        },
        "sheet": {"gfx": hex(GFX), "tiles": list(EVADE_TILES), "uniqueness": uniqueness},
        "paint": {k: v for k, v in painted.items() if k != "canvas"},
        "palette_roles": {
            "background": {"index": BACKGROUND, "rgb": list(colors[BACKGROUND])},
            "face": {"index": FACE, "rgb": list(colors[FACE])},
            "shadow": {"index": SHADOW, "rgb": list(colors[SHADOW])},
        },
        "palette_index_counts_before": counts,
        "palette_index_counts_after": after_counts,
        "preview": advance_relative(PREVIEW),
        "output": {"path": advance_relative(OUTPUT), "size": len(candidate), "sha256": sha256(candidate)},
        "sav": {"path": advance_relative(OUT_SAV), "byte_exact_copy": True},
        "deferred": "LANDFORM 海 text and sibling terrain names are not in this candidate",
        "verification": {
            "result": "PASS",
            "unique_source_tiles": True,
            "in_place_paint": True,
            "changed_bytes": len(changed),
            "main_tip_not_modified": True,
        },
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "result": "PASS",
                "candidate": advance_relative(OUTPUT),
                "sha256": sha256(candidate),
                "changed_bytes": len(changed),
                "preview": advance_relative(PREVIEW),
                "label": "회피",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
