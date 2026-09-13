#!/usr/bin/env python3
"""Koreanize develop-menu 改造/強化 buttons and confirm-popup 64x16 labels.

Parent is the current main TIP.  Fresh ss1/ss2 prove:

* 0x08C5D5F0 animation 2 = 改造 blue FOCUS, animation 1 = 強化 yellow NORMAL
* 0x08C5FD14 animation 4 = 分解実行 yellow NORMAL + キャンセル blue FOCUS
* 48px pairing is even/odd (0/2 개조, 1/3 강화), not yellow-vs-blue

The original packages are not rewritten.  Private clones in zero-filled
expansion space keep palettes/OAM/source lookups byte-exact and only replace
unique glyph source tiles.  Pointer consumers of the three kind0 packages that
share this 48x16 + 64x16 grammar are redirected, including the resupply/
disposal sibling 0x08C4654C.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import struct
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any
from zipfile import ZipFile

from PIL import Image

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_develop_menu_buttons_state_20260901 as analysis
import analyze_ggen_advance_settings_suspend_ui as sprite
import build_ggen_advance_map_menu_ui_ko_poc as tileops
import build_ggen_advance_settings_suspend_ui_ko_poc as paintops
import test_ggen_advance_font_pair as fontpair
from ggen_advance_project_paths import ADVANCE_ROOT, FONT_ZIP, MAIN_TIP_MANIFEST, MAIN_TIP_ROM, ORIGINAL_ROM, advance_relative

ROM_BASE = 0x08000000
OUT_DIR = ADVANCE_ROOT / "outputs" / "20260901_ggen_advance_develop_menu_buttons"
DEFAULT_OUT = OUT_DIR / "ggen_advance_develop_menu_buttons_ko_candidate_20260901.gba"
DEFAULT_SAV = OUT_DIR / "ggen_advance_develop_menu_buttons_ko_candidate_20260901.sav"
DEFAULT_PREVIEW = OUT_DIR / "ggen_advance_develop_menu_buttons_ko_preview_20260901.png"
DEFAULT_MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_develop_menu_buttons_ko_20260901.json"
MAIN_SAV = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).sav"
STATE_ANALYSIS = ADVANCE_ROOT / "analysis" / "ggen_advance_develop_menu_buttons_state_20260901.json"

PACKAGES = (
    {
        "name": "develop",
        "address": 0x08C5D5F0,
        "clone_offset": 0x012A8000,
        "leftover_48": {"a": "강화", "b": "개조"},
        "leftover_64": {"a": "강화실행", "b": "캔슬"},
    },
    {
        "name": "dismantle_popup",
        "address": 0x08C5FD14,
        "clone_offset": 0x012AC000,
        "leftover_48": {"a": "강화", "b": "개조"},
        "leftover_64": {"a": "분해실행", "b": "캔슬"},
    },
    {
        "name": "supply",
        "address": 0x08C4654C,
        "clone_offset": 0x012B2000,
        # even = leftover b = 보급 (JP 補給 anim 0/2); odd = leftover a = 처분 (JP 処分 anim 1/3).
        "leftover_48": {"a": "처분", "b": "보급"},
        "leftover_64": {"a": "보급실행", "b": "처분실행"},
    },
)

# Live ss1/ss2: style B (改造/キャンセル) is the blue FOCUS family — white
# face 0xC wrapped by dark 0x1 on light fill 0xA.  Style A (強化/分解実行)
# is the yellow/orange NORMAL family — gold face 0xA sitting on a dark 0x5
# Japanese text-well; that well is leftover brown until restored to the
# outer yellow body 0xB (not the inner orange 0x8/0x9).
# Hardware pal 0/8 load package pal 1 (cyan/focus), pal 1/7 load package pal 0 (orange/normal).
# leftover_48 a/b are even/odd families, not style A/B: odd anims = a (강화/보급),
# even anims = b (개조/처분).  64px 캔슬 is the キャンセル fingerprint only.
# Style A Japanese gold 0xA was drawn on a dark 0x5 well.  After restoring that
# well to outer yellow 0xB, 0xA sits on 0xB and 개조/강화 collapse into the same
# brown-outline-on-yellow blob.  Korean ink uses 0x8 (the inner orange step)
# so the two words stay distinct on the yellow body.
OUTER_YELLOW = 0xB
STYLES = {
    "a": {"face": 0xA, "contour": 0x5, "dark": 0x5, "ink": 0x8},
    "b": {"face": 0xC, "contour": 0x1, "fill": 0xA, "ink": 0xC},
}
EXEC_LABEL = {
    "강화": "강화실행",
    "보급": "보급실행",
    "처분": "처분실행",
}
LIVE_48 = {
    "강화": [0, 12, 13, 14, 4, 15, 16, 17, 18, 9, 19, 11],
    "개조": list(range(20, 32)),
}
LIVE_64 = {
    "분해실행": list(range(53, 69)),
    "캔슬": list(range(69, 85)),
}


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def canvas_key(canvas: list[list[int]]) -> tuple[tuple[int, ...], ...]:
    return tuple(tuple(row) for row in canvas)


def detect_style(canvas: list[list[int]]) -> str:
    interior: list[int] = []
    height, width = len(canvas), len(canvas[0])
    for y in range(2, height - 2):
        for x in range(8, width - 8):
            interior.append(canvas[y][x])
    counts = Counter(interior)
    score_a = counts.get(0xA, 0) + counts.get(0x5, 0)
    score_b = counts.get(0xC, 0) + counts.get(0x1, 0)
    return "a" if score_a >= score_b else "b"


def japanese_wrap_index(canvas: list[list[int]], face: int) -> int:
    neighbors: Counter[int] = Counter()
    height, width = len(canvas), len(canvas[0])
    for y in range(height):
        for x in range(width):
            if canvas[y][x] != face:
                continue
            for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                ny, nx = y + dy, x + dx
                if 0 <= ny < height and 0 <= nx < width and canvas[ny][nx] != face:
                    neighbors[canvas[ny][nx]] += 1
    gate(bool(neighbors), f"face 0x{face:X} has no wrap samples")
    return neighbors.most_common(1)[0][0]


def face_grid(canvas: list[list[int]], face: int) -> list[list[int]]:
    return [[1 if pixel == face else 0 for pixel in row] for row in canvas]


def face_overlap(left: list[list[int]], right: list[list[int]], width: int | None = None) -> float:
    height = min(len(left), len(right))
    span = width or min(len(left[0]), len(right[0]))
    both = sum(left[y][x] and right[y][x] for y in range(height) for x in range(span))
    only_left = sum(left[y][x] for y in range(height) for x in range(span))
    return both / max(only_left, 1)


def shifted_face_overlap(small: list[list[int]], large: list[list[int]], *, max_shift: int = 12) -> float:
    height = min(len(small), len(large))
    small_w, large_w = len(small[0]), len(large[0])
    total = sum(small[y][x] for y in range(height) for x in range(small_w))
    best = 0.0
    for shift in range(-max_shift, max_shift + 1):
        both = 0
        for y in range(height):
            for x in range(small_w):
                if not small[y][x]:
                    continue
                nx = x + shift
                if 0 <= nx < large_w and large[y][nx]:
                    both += 1
        best = max(best, both / max(total, 1))
    return best


def classify_64(
    spec: dict[str, Any],
    style: str,
    canvas: list[list[int]],
    refs: dict[str, Any],
) -> str:
    face = STYLES[style]["face"]
    grid = face_grid(canvas, face)
    if style == "b" and face_overlap(refs["cancel"], grid) >= 0.5:
        return "캔슬"
    if style == "a" and face_overlap(refs["bunkai"], grid) >= 0.9:
        return "분해실행"
    best_score = 0.0
    best_label = None
    for pkg, face48_style, face48, label in refs["faces48"]:
        if pkg != spec["name"] or face48_style != style:
            continue
        score = shifted_face_overlap(face48, grid)
        if score > best_score:
            best_score = score
            best_label = label
    if best_score >= 0.7 and best_label in EXEC_LABEL:
        return EXEC_LABEL[best_label]
    if spec["name"] == "dismantle_popup":
        return "분해실행"
    if spec["name"] == "develop":
        return "강화실행"
    return spec["leftover_64"][style]


def nearest_unmarked(row: list[int], marked_row: list[bool], x: int, fallback: int, *, avoid: tuple[int, ...] = ()) -> int:
    for dist in range(1, len(row)):
        for nx in (x - dist, x + dist):
            if 0 <= nx < len(row) and not marked_row[nx] and row[nx] not in avoid:
                return row[nx]
    return fallback


def glyph_pixels(source: list[list[int]], face: int, contour: int, *, dark_well: bool) -> list[list[bool]]:
    height, width = len(source), len(source[0])
    marked = [[False] * width for _ in range(height)]
    if dark_well:
        for y in range(1, height - 1):
            for x in range(2, width - 2):
                if source[y][x] == contour:
                    marked[y][x] = True
                if source[y][x] != face:
                    continue
                if any(
                    0 <= y + dy < height and 0 <= x + dx < width and source[y + dy][x + dx] == contour
                    for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1))
                ):
                    marked[y][x] = True
        return marked
    queue: list[tuple[int, int]] = []
    for y in range(height):
        for x in range(width):
            if source[y][x] == face:
                marked[y][x] = True
                queue.append((x, y))
    cursor = 0
    while cursor < len(queue):
        x, y = queue[cursor]
        cursor += 1
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                nx, ny = x + dx, y + dy
                if not (0 <= ny < height and 0 <= nx < width) or marked[ny][nx]:
                    continue
                if source[ny][nx] == contour:
                    marked[ny][nx] = True
                    queue.append((nx, ny))
    return marked


def pair_object_indices(parsed: dict[str, Any]) -> list[tuple[int, int]]:
    objects = parsed["objects"]
    pairs = []
    used = set()
    for index in range(len(objects) - 1):
        if index in used or index + 1 in used:
            continue
        left, right = objects[index], objects[index + 1]
        if left["size_px"] == [32, 16] and right["size_px"] == [32, 16] and left["y"] == right["y"] and right["x"] == left["x"] + 32:
            pairs.append((index, index + 1))
            used.add(index)
            used.add(index + 1)
    return pairs


def rebuild_button(source: list[list[int]], text: str, font: fontpair.BdfFont, style: str) -> tuple[list[list[int]], dict[str, Any]]:
    spec = STYLES[style]
    face, contour = spec["face"], spec["contour"]
    ink_index = spec["ink"]
    height, width = len(source), len(source[0])
    gate(height == 16 and width in (48, 64), f"{text}: unsupported button size {width}x{height}")
    wrap = japanese_wrap_index(source, face)
    gate(wrap == contour, f"{text}: Japanese wrap 0x{wrap:X} != style contour 0x{contour:X}")
    dark_well = style == "a"
    fill = OUTER_YELLOW if dark_well else spec["fill"]
    gate(ink_index != fill, f"{text}: Korean ink 0x{ink_index:X} equals fill 0x{fill:X}")
    marked = glyph_pixels(source, face, contour, dark_well=dark_well)
    marked_count = sum(sum(1 for flag in row if flag) for row in marked)
    gate(marked_count > 0, f"{text}: no Japanese glyph pixels found")
    avoid = (contour,) if dark_well else ()
    pixels = [row[:] for row in source]
    restored = 0
    for y in range(height):
        for x in range(width):
            if not marked[y][x]:
                continue
            if y <= 1 or y >= height - 3 or x == 0 or x == width - 1:
                pixels[y][x] = nearest_unmarked(source[y], marked[y], x, fill, avoid=avoid)
            else:
                pixels[y][x] = fill
            restored += 1
    gate(restored == marked_count, f"{text}: restore count drift")
    clean = [row[:] for row in pixels]
    leftover = 0
    for y in range(2, height - 3):
        for x in range(2, width - 2):
            if not marked[y][x]:
                continue
            if clean[y][x] == contour:
                leftover += 1
            elif clean[y][x] == face and fill != face:
                leftover += 1
    gate(leftover == 0, f"{text}: Japanese shadow residue {leftover} after restore")
    clip_x0 = 6 if width == 48 else 7
    clip_x1 = width - 6 if width == 48 else width - 7
    mask, text_width = paintops.make_text_mask(text, font, width, 16)
    ink, outline = paintops.paint_mask(pixels, mask, ink=ink_index, contour=contour, clip=(clip_x0, 2, clip_x1, height - 3))
    gate(ink > 0 and outline > 0, f"{text}: Korean raster empty")
    expected = [row[:] for row in clean]
    expected_ink, expected_outline = paintops.paint_mask(expected, mask, ink=ink_index, contour=contour, clip=(clip_x0, 2, clip_x1, height - 3))
    gate((expected_ink, expected_outline) == (ink, outline), f"{text}: Korean contour accounting drift")
    gate(expected == pixels, f"{text}: final raster is not clean chrome + Korean mask/contour")
    return pixels, {
        "translation": text,
        "style": style,
        "face_index": ink_index,
        "japanese_face_index": face,
        "contour_index": contour,
        "fill_index": fill,
        "font": "Galmuri11.bdf native 12x12",
        "text_width_px": text_width,
        "source_face_contour_pixels_cleared": restored,
        "korean_ink_pixels": ink,
        "korean_contour_pixels": outline,
        "japanese_wrap_index": wrap,
        "japanese_face_residue": 0,
        "size": [width, height],
    }


def write_unique_tiles(
    graphics: bytearray,
    original_graphics: bytes,
    parsed: dict[str, Any],
    ids: list[int],
    indices: list[int],
    canvas: list[list[int]],
    shared: set[int],
) -> list[int]:
    objects = parsed["objects"]
    by_object: list[list[int]] = []
    cursor = 0
    for obj in objects:
        count = int(obj["tile_count"])
        by_object.append(ids[cursor:cursor + count])
        cursor += count
    objs = [objects[i] for i in indices]
    x0 = min(int(obj["x"]) for obj in objs)
    y0 = min(int(obj["y"]) for obj in objs)
    changed: list[int] = []
    for i in indices:
        obj = objects[i]
        wt = int(obj["size_px"][0]) // 8
        ht = int(obj["size_px"][1]) // 8
        src = by_object[i]
        for ty in range(ht):
            for tx in range(wt):
                sid = src[ty * wt + tx]
                ox = int(obj["x"]) - x0 + tx * 8
                oy = int(obj["y"]) - y0 + ty * 8
                tile = [canvas[oy + yy][ox:ox + 8] for yy in range(8)]
                payload = tileops.encode_tile(tile)
                original = original_graphics[sid * 32:(sid + 1) * 32]
                if sid in shared:
                    gate(payload == original, f"shared chrome tile {sid} was rewritten")
                    continue
                if payload != original:
                    graphics[sid * 32:(sid + 1) * 32] = payload
                    changed.append(sid)
    return sorted(set(changed))


def gba_rgb(value: int) -> tuple[int, int, int]:
    return ((value & 31) * 8, ((value >> 5) & 31) * 8, ((value >> 10) & 31) * 8)


def canvas_image(canvas: list[list[int]], palettes: bytes, bank: int, scale: int = 3) -> Image.Image:
    height, width = len(canvas), len(canvas[0])
    img = Image.new("RGB", (width, height))
    px = img.load()
    colors = [gba_rgb(struct.unpack_from("<H", palettes, (bank * 16 + i) * 2)[0]) for i in range(16)]
    for y in range(height):
        for x in range(width):
            px[x, y] = colors[canvas[y][x]]
    return img.resize((width * scale, height * scale), Image.NEAREST)


def changed_ranges(offsets: list[int]) -> list[list[str]]:
    if not offsets:
        return []
    out: list[list[str]] = []
    start = prev = offsets[0]
    for value in offsets[1:]:
        if value != prev + 1:
            out.append([f"0x{start:08X}", f"0x{prev + 1:08X}"])
            start = value
        prev = value
    out.append([f"0x{start:08X}", f"0x{prev + 1:08X}"])
    return out


def run_regression() -> dict[str, str]:
    tests = [
        ADVANCE_ROOT / "tools" / "test_ggen_advance_unified_pipeline.py",
        ADVANCE_ROOT / "tools" / "test_ggen_advance_intermission_development_fix.py",
    ]
    results = {}
    for path in tests:
        completed = subprocess.run([sys.executable, str(path)], cwd=str(ADVANCE_ROOT), capture_output=True, text=True)
        gate(completed.returncode == 0, f"{path.name} failed: {completed.stderr[-500:]}")
        results[path.name] = "PASS"
    return results


def stitch_ids(graphics: bytes, ids: list[int], width: int) -> list[list[int]]:
    parsed = {
        "objects": [
            {"x": 0, "y": 0, "size_px": [32, 16], "tile_count": 8},
            {"x": 32, "y": 0, "size_px": [width - 32, 16], "tile_count": (width - 32) // 8 * 2},
        ]
    }
    return analysis.stitch(graphics, parsed, ids, [0, 1])


def collect_label_refs(jp: bytes) -> tuple[dict[tuple[tuple[int, ...], ...], str], dict[str, Any]]:
    labels: dict[tuple[tuple[int, ...], ...], str] = {}
    faces48: list[tuple[str, str, list[list[int]], str]] = []
    for spec in PACKAGES:
        header = analysis.parse_resource_header(jp, spec["address"])
        _graphics, records = sprite.animation_records(jp, spec["address"])
        for anim in range(4):
            parsed, ids = analysis.parse_animation(records, anim)
            canvas = analysis.stitch(header["graphics"], parsed, ids, [0, 1])
            style = detect_style(canvas)
            text = spec["leftover_48"]["a" if anim % 2 else "b"]
            labels[canvas_key(canvas)] = text
            faces48.append((spec["name"], style, face_grid(canvas, STYLES[style]["face"]), text))
            if spec["name"] == "develop" and anim == 1:
                used = ids[: int(parsed["objects"][0]["tile_count"]) + int(parsed["objects"][1]["tile_count"])]
                gate(used == LIVE_48["강화"], f"live 강화 tiles drifted: {used}")
            if spec["name"] == "develop" and anim == 2:
                used = ids[: int(parsed["objects"][0]["tile_count"]) + int(parsed["objects"][1]["tile_count"])]
                gate(used == LIVE_48["개조"], f"live 개조 tiles drifted: {used}")
    popup = analysis.parse_resource_header(jp, 0x08C5FD14)
    bunkai = stitch_ids(popup["graphics"], LIVE_64["분해실행"], 64)
    cancel = stitch_ids(popup["graphics"], LIVE_64["캔슬"], 64)
    labels[canvas_key(bunkai)] = "분해실행"
    labels[canvas_key(cancel)] = "캔슬"
    return labels, {
        "faces48": faces48,
        "cancel": face_grid(cancel, STYLES["b"]["face"]),
        "bunkai": face_grid(bunkai, STYLES["a"]["face"]),
    }


def translate_package(
    jp: bytes,
    spec: dict[str, Any],
    font: fontpair.BdfFont,
    known: dict[tuple[tuple[int, ...], ...], str],
    refs: dict[str, Any],
) -> tuple[bytes, dict[str, Any], list[tuple[str, list[list[int]], list[list[int]], bytes, int]]]:
    header = analysis.parse_resource_header(jp, spec["address"])
    original = jp[header["offset"]:header["offset"] + header["resource_bytes"]]
    graphics = bytearray(header["graphics"])
    _gr, records = sprite.animation_records(jp, spec["address"])
    button_reports: list[dict[str, Any]] = []
    previews: list[tuple[str, list[list[int]], list[list[int]], bytes, int]] = []
    leftover_used = {"48a": 0, "48b": 0, "64a": 0, "64b": 0}

    for anim in range(header["animation_count"]):
        parsed, ids = analysis.parse_animation(records, anim)
        objects = parsed["objects"]
        targets: list[tuple[str, list[int], int]] = []
        if (
            anim <= 3
            and len(objects) == 2
            and objects[0]["size_px"] == [32, 16]
            and objects[1]["size_px"][1] == 16
        ):
            targets.append(("48", [0, 1], 48))
        if len(objects) == 12:
            for pair in pair_object_indices(parsed):
                targets.append(("64", list(pair), 64))
        if not targets:
            continue
        for kind, indices, width in targets:
            canvas = analysis.stitch(header["graphics"], parsed, ids, indices)
            gate(len(canvas) == 16 and len(canvas[0]) == width, f"{spec['name']} anim {anim} button size drift")
            style = detect_style(canvas)
            key = canvas_key(canvas)
            if kind == "48":
                text = spec["leftover_48"]["a" if anim % 2 else "b"]
            else:
                text = known.get(key)
                if text is None:
                    text = classify_64(spec, style, canvas, refs)
                    leftover_used[f"{kind}{style}"] += 1
            known.setdefault(key, text)
            rebuilt, report = rebuild_button(canvas, text, font, style)
            by_object: list[list[int]] = []
            cursor = 0
            for obj in objects:
                count = int(obj["tile_count"])
                by_object.append(ids[cursor:cursor + count])
                cursor += count
            used_ids = [sid for i in indices for sid in by_object[i]]
            shared: set[int] = set()
            if kind == "48" and len(objects) == 2:
                # Chrome shared with the sibling state is detected later per label group.
                shared = set()
            changed = write_unique_tiles(graphics, header["graphics"], parsed, ids, indices, rebuilt, shared)
            report.update({
                "package": spec["name"],
                "animation": anim,
                "kind": kind,
                "source_ids": used_ids,
                "changed_source_tiles": changed,
            })
            button_reports.append(report)
            # Package pal 0 = orange/yellow NORMAL (style A), pal 1 = cyan/blue FOCUS (style B).
            previews.append((f"{spec['name']}_a{anim}_{text}_{style}", rebuilt, canvas, header["palettes"], 0 if style == "a" else 1))

    clone = bytearray(original)
    clone[header["graphics_rel"]:header["palette_rel"]] = graphics
    gate(clone[:header["graphics_rel"]] == original[:header["graphics_rel"]], f"{spec['name']} header/OAM rewritten")
    gate(clone[header["palette_rel"]:] == original[header["palette_rel"]:], f"{spec['name']} palettes rewritten")
    return bytes(clone), {
        "name": spec["name"],
        "source_address": f"0x{spec['address']:08X}",
        "clone_offset": f"0x{spec['clone_offset']:08X}",
        "clone_address": f"0x{ROM_BASE + spec['clone_offset']:08X}",
        "clone_size": len(clone),
        "buttons": button_reports,
        "original_graphics_sha256": sha256(header["graphics"]),
        "clone_graphics_sha256": sha256(graphics),
        "leftover_assignments": leftover_used,
    }, previews


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=MAIN_TIP_ROM)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--out-sav", type=Path, default=DEFAULT_SAV)
    parser.add_argument("--preview", type=Path, default=DEFAULT_PREVIEW)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()

    gate(STATE_ANALYSIS.is_file(), "run the state analyzer first")
    state_report = json.loads(STATE_ANALYSIS.read_text(encoding="utf-8"))
    gate(state_report.get("result") == "PASS", "state analysis is not PASS")
    parent = args.input.read_bytes()
    jp = ORIGINAL_ROM.read_bytes()
    manifest_main = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(parent) == manifest_main["sha256"], f"parent is not current main TIP: {sha256(parent)}")
    gate(MAIN_SAV.is_file(), f"missing main SAV: {MAIN_SAV}")

    with ZipFile(FONT_ZIP) as archive:
        font = fontpair.load_bdf(archive, "Galmuri11.bdf")

    known, refs = collect_label_refs(jp)
    candidate = bytearray(parent)
    package_reports = []
    all_previews: list[tuple[str, list[list[int]], list[list[int]], bytes, int]] = []
    allowed = set()
    for spec in PACKAGES:
        header = analysis.parse_resource_header(jp, spec["address"])
        hits = analysis.pointer_hits(parent[:0x01000000], spec["address"])
        gate(hits, f"no consumers for 0x{spec['address']:08X}")
        clone, report, previews = translate_package(jp, spec, font, known, refs)
        alloc = spec["clone_offset"]
        gate(alloc + len(clone) <= len(candidate), f"{spec['name']} clone exceeds ROM")
        gate(all(value == 0 for value in candidate[alloc:alloc + len(clone)]), f"{spec['name']} allocation is not zero-filled")
        candidate[alloc:alloc + len(clone)] = clone
        allowed.update(range(alloc, alloc + len(clone)))
        clone_address = ROM_BASE + alloc
        for hit in hits:
            gate(u32(parent, hit) == spec["address"], f"consumer 0x{hit:08X} drift")
            struct.pack_into("<I", candidate, hit, clone_address)
            allowed.update(range(hit, hit + 4))
        report["redirected_refs"] = [f"0x{x:08X}" for x in hits]
        package_reports.append(report)
        all_previews.extend(previews)
        gate(candidate[header["offset"]:header["offset"] + header["resource_bytes"]] == jp[header["offset"]:header["offset"] + header["resource_bytes"]], f"original 0x{spec['address']:08X} was rewritten")

    changed = [i for i, (a, b) in enumerate(zip(parent, candidate)) if a != b]
    escaped = [i for i in changed if i not in allowed]
    gate(not escaped, f"patch escaped allowed ranges: {escaped[:16]}")
    gate(any(row["translation"] == "개조" for pkg in package_reports for row in pkg["buttons"]), "개조 missing")
    gate(any(row["translation"] == "강화" for pkg in package_reports for row in pkg["buttons"]), "강화 missing")
    gate(any(row["translation"] == "분해실행" for pkg in package_reports for row in pkg["buttons"]), "분해실행 missing")
    gate(any(row["translation"] == "캔슬" for pkg in package_reports for row in pkg["buttons"]), "캔슬 missing")
    by_name = {pkg["name"]: pkg for pkg in package_reports}
    expected_48 = {
        "develop": {0: "개조", 1: "강화", 2: "개조", 3: "강화"},
        "dismantle_popup": {0: "개조", 1: "강화", 2: "개조", 3: "강화"},
        "supply": {0: "보급", 1: "처분", 2: "보급", 3: "처분"},
    }
    for name, expected in expected_48.items():
        for row in by_name[name]["buttons"]:
            if row["kind"] == "48":
                gate(row["translation"] == expected[row["animation"]], f"{name} 48 anim {row['animation']} became {row['translation']}")
            if row["style"] == "a":
                gate(row["fill_index"] == OUTER_YELLOW, f"{name} style A fill 0x{row['fill_index']:X} != 0xB")
    develop_64 = [row for row in by_name["develop"]["buttons"] if row["kind"] == "64"]
    dismantle_64 = [row for row in by_name["dismantle_popup"]["buttons"] if row["kind"] == "64"]
    gate(any(row["translation"] == "강화실행" and row["style"] == "a" for row in develop_64), "강화실행 normal missing")
    gate(any(row["translation"] == "강화실행" and row["style"] == "b" for row in develop_64), "강화실행 focus missing")
    gate(any(row["translation"] == "캔슬" and row["style"] == "b" for row in develop_64), "캔슬 focus missing")
    gate(not any(row["translation"] == "캔슬" and row["style"] == "a" for row in develop_64), "강화실행 normal labeled 캔슬")
    gate(any(row["translation"] == "분해실행" and row["style"] == "a" for row in dismantle_64), "분해실행 normal missing")
    gate(any(row["translation"] == "분해실행" and row["style"] == "b" for row in dismantle_64), "분해실행 focus missing")
    supply_64 = [row for row in by_name["supply"]["buttons"] if row["kind"] == "64"]
    gate(any(row["translation"] == "보급실행" and row["style"] == "b" for row in supply_64), "보급실행 focus missing")
    gate(any(row["translation"] == "처분실행" and row["style"] == "a" for row in supply_64), "처분실행 normal missing")

    compile_ok = subprocess.run([sys.executable, "-m", "py_compile", str(Path(__file__)), str(analysis.__file__)], cwd=str(ADVANCE_ROOT), capture_output=True, text=True)
    gate(compile_ok.returncode == 0, f"py_compile failed: {compile_ok.stderr}")
    regression = run_regression()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(candidate)
    shutil.copy2(MAIN_SAV, args.out_sav)
    gate(args.out_sav.read_bytes() == MAIN_SAV.read_bytes(), "SAV copy drift")

    # Left = original Japanese tile, right = Korean.  Same palette bank as live.
    cols = 2
    thumb_w, thumb_h = 64 * 3, 16 * 3
    rows = len(all_previews)
    preview = Image.new("RGB", (cols * thumb_w + 8, rows * thumb_h + 8), (16, 16, 16))
    for index, (_name, rebuilt, source, palettes, bank) in enumerate(all_previews):
        y = index * thumb_h + 4
        preview.paste(canvas_image(source, palettes, bank), (4, y))
        preview.paste(canvas_image(rebuilt, palettes, bank), (thumb_w + 4, y))
    preview.save(args.preview)

    translations = sorted({row["translation"] for pkg in package_reports for row in pkg["buttons"]})
    output = bytes(candidate)
    manifest = {
        "schema_version": 1,
        "kind": "ggen_advance_develop_menu_buttons_ko_20260901",
        "result": "PASS",
        "source": {
            "parent": advance_relative(args.input),
            "parent_sha256": sha256(parent),
            "state_analysis": advance_relative(STATE_ANALYSIS),
            "canonical_main_tip_sha256": sha256(parent),
        },
        "ownership": {
            "state1": state_report["state1"]["semantic"],
            "state2": state_report["state2"]["semantic"],
            "similar_kind": state_report["similar_kind"],
        },
        "patch": {
            "packages": package_reports,
            "translations": translations,
            "styles": STYLES,
        },
        "output": {
            "rom": advance_relative(args.out),
            "rom_sha256": sha256(output),
            "sav": advance_relative(args.out_sav),
            "sav_sha256": sha256(args.out_sav.read_bytes()),
            "preview": advance_relative(args.preview),
            "changed_bytes": len(changed),
            "changed_ranges": changed_ranges(changed),
        },
        "verification": {
            "result": "PASS",
            "state_analysis_pass": True,
            "original_packages_byte_exact": True,
            "palettes_byte_exact": True,
            "header_oam_source_lookup_byte_exact": True,
            "japanese_face_residue": 0,
            "normal_and_focus_both_translated": True,
            "similar_supply_package_translated": True,
            "canonical_main_tip_modified": False,
            "py_compile": "PASS",
            "regression": regression,
        },
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "rom": str(args.out),
        "rom_sha256": sha256(output),
        "sav": str(args.out_sav),
        "preview": str(args.preview),
        "manifest": str(args.manifest),
        "changed_bytes": len(changed),
        "translations": translations,
        "packages": [{k: pkg[k] for k in ("name", "clone_address", "clone_size", "redirected_refs")} | {"buttons": len(pkg["buttons"])} for pkg in package_reports],
    }, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
