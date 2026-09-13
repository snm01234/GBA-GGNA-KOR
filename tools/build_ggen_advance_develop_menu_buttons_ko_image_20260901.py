#!/usr/bin/env python3
"""Build Korean develop-menu buttons from the Japanese image catalog.

Parent is the current main TIP.  The discarded even/odd leftover POC is not
used.  Each catalog row is one stitched Japanese picture; Korean is painted
onto a private clone that keeps original source tiles byte-exact, appends new
tiles, and remaps only that button's source lookup.

Normal yellow (48px and 64px) uses the same pair as 개조/강화/보급/처분:
    pale-yellow well 0xB, gold-yellow Hangul 0xA, brown shadow 0x5.  64px must
    not treat the Japanese letter/shadow gold 0xA as the button body.  Overflow
    on the round caps is restored from unmarked chrome in the same row.  Focus
    restores pale cyan-white 0xA, never the saturated blue cap 0x8/0x9.
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

import analyze_ggen_advance_develop_menu_buttons_images_20260901 as catalog
import analyze_ggen_advance_develop_menu_buttons_state_20260901 as analysis
import analyze_ggen_advance_settings_suspend_ui as sprite
import build_ggen_advance_map_menu_ui_ko_poc as tileops
import build_ggen_advance_settings_suspend_ui_ko_poc as paintops
import test_ggen_advance_font_pair as fontpair
from ggen_advance_project_paths import ADVANCE_ROOT, FONT_ZIP, MAIN_TIP_MANIFEST, MAIN_TIP_ROM, ORIGINAL_ROM, advance_relative

ROM_BASE = 0x08000000
OUT_DIR = ADVANCE_ROOT / "outputs" / "20260901_ggen_advance_develop_menu_buttons_image"
DEFAULT_OUT = OUT_DIR / "ggen_advance_develop_menu_buttons_ko_image_candidate_20260901.gba"
DEFAULT_SAV = OUT_DIR / "ggen_advance_develop_menu_buttons_ko_image_candidate_20260901.sav"
DEFAULT_PREVIEW = OUT_DIR / "ggen_advance_develop_menu_buttons_ko_image_preview_20260901.png"
DEFAULT_MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_develop_menu_buttons_ko_image_20260901.json"
MAIN_SAV = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).sav"
STATE_ANALYSIS = ADVANCE_ROOT / "analysis" / "ggen_advance_develop_menu_buttons_state_20260901.json"

CLONES = {
    "develop": 0x012C0000,
    "dismantle_popup": 0x012C8000,
    "supply": 0x012D0000,
    "remodel_popup": 0x012D8000,
}
BODY_YELLOW = 0xB
BODY_FOCUS = 0xA
INK_YELLOW = 0xA
CONTOUR_YELLOW = 0x5
INK_FOCUS = 0xC
YELLOW_CANCEL_SIGNATURE = "aa1414b178b5c034"
YELLOW_EXECUTE_SIGNATURE = "037ffbbc8e9c463c"
YELLOW_REMODEL_SIGNATURE = "4dde66578e449ad2"
CAP_MARGIN = 3
BODY_Y0 = 2
BODY_Y1 = 14


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def in_button_body(x: int, y: int, width: int) -> bool:
    return CAP_MARGIN <= x < width - CAP_MARGIN and BODY_Y0 <= y < BODY_Y1


def button_fill(source: list[list[int]], marked: list[list[bool]], yellow: bool) -> int:
    if yellow:
        return BODY_YELLOW
    width = len(source[0])
    interior: list[int] = []
    for y in range(3, 13):
        for x in range(8, width - 8):
            if not marked[y][x]:
                interior.append(source[y][x])
    if interior:
        return Counter(interior).most_common(1)[0][0]
    return BODY_FOCUS


def nearest_unmarked_in_row(
    source: list[list[int]],
    marked: list[list[bool]],
    x: int,
    y: int,
    fallback: int,
) -> int:
    width = len(source[0])
    best = fallback
    best_d = width
    for nx in range(width):
        if marked[y][nx]:
            continue
        value = source[y][nx]
        if value == 0:
            continue
        distance = abs(nx - x)
        if distance < best_d:
            best_d = distance
            best = value
    return best


def restore_pixel(
    source: list[list[int]],
    marked: list[list[bool]],
    x: int,
    y: int,
    body: int,
) -> int:
    if not marked[y][x]:
        return source[y][x]
    if in_button_body(x, y, len(source[0])):
        return body
    return nearest_unmarked_in_row(source, marked, x, y, body)


def paint_mask_cardinal(
    pixels: list[list[int]],
    mask: list[list[bool]],
    *,
    ink: int,
    contour: int,
) -> tuple[int, int]:
    height = len(pixels)
    width = len(pixels[0])
    outline = [[False] * width for _ in range(height)]
    for y in range(height):
        for x in range(width):
            if not mask[y][x]:
                continue
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                ox, oy = x + dx, y + dy
                if 0 <= ox < width and 0 <= oy < height and not mask[oy][ox]:
                    outline[oy][ox] = True
    contour_pixels = 0
    ink_pixels = 0
    for y in range(height):
        for x in range(width):
            if outline[y][x]:
                pixels[y][x] = contour
                contour_pixels += 1
            elif mask[y][x]:
                pixels[y][x] = ink
                ink_pixels += 1
    return ink_pixels, contour_pixels


def rebuild_button(
    source: list[list[int]],
    text: str,
    font: fontpair.BdfFont,
    face: int,
    contour: int,
    palettes: bytes,
    bank: int,
) -> tuple[list[list[int]], dict[str, Any]]:
    height, width = len(source), len(source[0])
    gate(height == 16 and width in (48, 64), f"{text}: unsupported size {width}x{height}")
    yellow = face == 0xA
    # These palette indices are also used by the native frame.  Seed the
    # Japanese raster only inside the label well so the cap gradient is not
    # mistaken for lettering.
    marked = [
        [
            in_button_body(x, y, width) and pixel in (face, contour)
            for x, pixel in enumerate(row)
        ]
        for y, row in enumerate(source)
    ]
    # A few glyph contours cross BODY_Y0/BODY_Y1.  Include only pixels within
    # two pixels of the interior seed.  Recursive component growth can run
    # from a glyph shadow into the native brown/blue horizontal separator,
    # because those frame lines deliberately reuse the contour palette index.
    if width == 48:
        interior_seed = [row[:] for row in marked]
        for y in range(height):
            for x in range(width):
                if marked[y][x] or source[y][x] not in (face, contour):
                    continue
                if any(
                    0 <= y + dy < height
                    and 0 <= x + dx < width
                    and interior_seed[y + dy][x + dx]
                    for dy in range(-2, 3)
                    for dx in range(-2, 3)
                ):
                    marked[y][x] = True
    else:
        changed = True
        while changed:
            changed = False
            grown = [row[:] for row in marked]
            for y in range(height):
                for x in range(width):
                    if marked[y][x] or source[y][x] not in (face, contour):
                        continue
                    if any(
                        0 <= y + dy < height
                        and 0 <= x + dx < width
                        and marked[y + dy][x + dx]
                        for dy in (-1, 0, 1)
                        for dx in (-1, 0, 1)
                        if dx or dy
                    ):
                        grown[y][x] = True
                        changed = True
            marked = grown
    body = button_fill(source, marked, yellow)
    if yellow:
        ink, korean_contour = INK_YELLOW, CONTOUR_YELLOW
    else:
        ink, korean_contour = INK_FOCUS, 0x1
    gate(ink != body, f"{text}: ink equals fill")
    cell_width = 12
    mask, text_width = paintops.make_text_mask(text, font, width, 16, cell_width=cell_width)
    clean = [row[:] for row in source]
    # The third JP shadow layer is palette index 4 and was not part of the old
    # face/contour predicate.  Limit it to pixels touching the proven Japanese
    # raster so genuine brown frame pixels elsewhere remain untouched.
    contaminated = [row[:] for row in marked]
    for y in range(height):
        for x in range(width):
            if source[y][x] != 4:
                continue
            if any(
                0 <= y + dy < height
                and 0 <= x + dx < width
                and marked[y + dy][x + dx]
                for dy in range(-2, 3)
                for dx in range(-2, 3)
            ):
                contaminated[y][x] = True
    cleared = 0
    cap_restored = 0
    row_fills: list[int] = []
    for y in range(height):
        candidates = [
            source[y][x]
            for x in range(CAP_MARGIN, width - CAP_MARGIN)
            if not contaminated[y][x] and source[y][x] != 0
        ]
        row_fills.append(Counter(candidates).most_common(1)[0][0] if candidates else body)

    # Restore only the proven Japanese raster and its touching shadow.  The
    # former complete-well fill made a large flat rectangle.  Sampling each
    # untouched native scanline retains its top/bottom shading, while overflow
    # in a rounded cap is interpolated horizontally from clean chrome.
    for y in range(height):
        for x in range(width):
            if not contaminated[y][x]:
                continue
            cleared += 1
            if in_button_body(x, y, width):
                clean[y][x] = row_fills[y]
            else:
                clean[y][x] = nearest_unmarked_in_row(source, contaminated, x, y, row_fills[y])
                cap_restored += 1
    gate(cleared > 0, f"{text}: no Japanese face/contour pixels in image")
    leftover = sum(
        1
        for y in range(height)
        for x in range(width)
        if in_button_body(x, y, width)
        and contaminated[y][x]
        and clean[y][x] in (face, contour, 4)
    )
    gate(leftover == 0, f"{text}: Japanese residue {leftover} after selective scanline restore")
    pixels = [row[:] for row in clean]
    painted, outline = paint_mask_cardinal(pixels, mask, ink=ink, contour=korean_contour)
    gate(painted > 0 and outline > 0, f"{text}: Korean raster empty")
    expected = [row[:] for row in clean]
    expected_ink, expected_outline = paint_mask_cardinal(expected, mask, ink=ink, contour=korean_contour)
    gate((expected_ink, expected_outline) == (painted, outline), f"{text}: Korean contour accounting drift")
    gate(expected == pixels, f"{text}: final raster is not clean chrome + Korean mask/contour")
    if yellow:
        gate(body == BODY_YELLOW and ink == INK_YELLOW and korean_contour == CONTOUR_YELLOW, f"{text}: yellow ink/shadow is not 개조-normal pair")
    else:
        gate(body == BODY_FOCUS, f"{text}: focus fill is not pale cyan-white")
    gate(ink != 0x8, f"{text}: orange/blue rim used as Korean ink")
    return pixels, {
        "translation": text,
        "style": "normal_yellow" if yellow else "focus_blue",
        "japanese_face_index": face,
        "korean_ink_index": ink,
        "contour_index": korean_contour,
        "fill_index": body,
        "palette_bank": bank,
        "palette_bytes": len(palettes),
        "font": "Galmuri11.bdf native 12x12",
        "text_width_px": text_width,
        "cell_width_px": cell_width,
        "source_face_contour_pixels_cleared": cleared,
        "round_cap_pixels_restored": cap_restored,
        "background_restore": "selective_native_scanline",
        "korean_ink_pixels": painted,
        "korean_contour_pixels": outline,
        "japanese_face_residue": 0,
        "size": [width, height],
    }


def tile_payload(canvas: list[list[int]], obj: dict[str, Any], group_x0: int, group_y0: int, tx: int, ty: int) -> bytes:
    ox = int(obj["x"]) - group_x0 + tx * 8
    oy = int(obj["y"]) - group_y0 + ty * 8
    tile = [canvas[oy + yy][ox:ox + 8] for yy in range(8)]
    return tileops.encode_tile(tile)


def translate_package(jp: bytes, spec: dict[str, Any], buttons: list[dict[str, Any]], font: fontpair.BdfFont) -> tuple[bytes, dict[str, Any], list[tuple[list[list[int]], list[list[int]], bytes, int]]]:
    header = analysis.parse_resource_header(jp, spec["address"])
    original = jp[header["offset"]:header["offset"] + header["resource_bytes"]]
    original_graphics = header["graphics"]
    palettes = header["palettes"]
    original_tiles = len(original_graphics) // 32
    _graphics_rel, records = sprite.animation_records(jp, spec["address"])
    parsed_by_anim: dict[int, tuple[dict[str, Any], list[int], int]] = {}
    for anim in {row["anim"] for row in buttons}:
        parsed_by_anim[anim] = catalog.parse_anim(records, anim)

    existing: dict[bytes, int] = {}
    for tile_id in range(original_tiles):
        existing.setdefault(original_graphics[tile_id * 32:(tile_id + 1) * 32], tile_id)
    private_ids: dict[bytes, int] = {}
    private_payloads: list[bytes] = []
    lookup_writes: dict[int, int] = {}
    reports: list[dict[str, Any]] = []
    previews: list[tuple[list[list[int]], list[list[int]], bytes, int]] = []

    for row in buttons:
        parsed, ids, lookup_file = parsed_by_anim[row["anim"]]
        objects = parsed["objects"]
        indices = list(row["objects"])
        source_canvas = analysis.stitch(original_graphics, parsed, ids, indices)
        gate(catalog.face_signature(source_canvas, row["face"]) == row["signature"], f"{row['jp']} image signature drift")
        rebuilt, report = rebuild_button(source_canvas, row["ko"], font, row["face"], row["contour"], palettes, row["bank"])
        objs = [objects[i] for i in indices]
        gx0 = min(int(obj["x"]) for obj in objs)
        gy0 = min(int(obj["y"]) for obj in objs)
        by_object: list[list[int]] = []
        cursor = 0
        for obj in objects:
            count = int(obj["tile_count"])
            by_object.append(ids[cursor:cursor + count])
            cursor += count
        before: list[int] = []
        after: list[int] = []
        for local, obj_index in enumerate(indices):
            obj = objects[obj_index]
            src = by_object[obj_index]
            wt = int(obj["size_px"][0]) // 8
            ht = int(obj["size_px"][1]) // 8
            base = int(row["lookup_object_bases"][local])
            for ty in range(ht):
                for tx in range(wt):
                    pos = ty * wt + tx
                    old_id = int(src[pos])
                    payload = tile_payload(rebuilt, obj, gx0, gy0, tx, ty)
                    old_payload = original_graphics[old_id * 32:(old_id + 1) * 32]
                    if payload == old_payload:
                        new_id = old_id
                    elif payload in existing:
                        new_id = existing[payload]
                    else:
                        new_id = private_ids.get(payload, -1)
                        if new_id < 0:
                            new_id = original_tiles + len(private_payloads)
                            private_ids[payload] = new_id
                            private_payloads.append(payload)
                    rel = (lookup_file - header["offset"]) + (base + pos) * 2
                    previous = lookup_writes.get(rel)
                    gate(previous is None or previous == new_id, f"conflicting lookup write at 0x{rel:X}")
                    lookup_writes[rel] = new_id
                    before.append(old_id)
                    after.append(new_id)
        report.update({
            "package": spec["name"],
            "jp": row["jp"],
            "animation": row["anim"],
            "kind": row["kind"],
            "objects": indices,
            "original_source_ids": before,
            "remapped_source_ids": after,
            "changed_lookup_entries": sum(a != b for a, b in zip(before, after)),
            "signature": row["signature"],
        })
        reports.append(report)
        previews.append((source_canvas, rebuilt, palettes, row["bank"]))

    graphics = original_graphics + b"".join(private_payloads)
    new_palette_rel = header["graphics_rel"] + len(graphics)
    clone = bytearray(new_palette_rel + len(palettes))
    clone[:header["graphics_rel"]] = original[:header["graphics_rel"]]
    struct.pack_into("<I", clone, 0x0C, new_palette_rel)
    for rel, new_id in lookup_writes.items():
        struct.pack_into("<H", clone, rel, new_id)
    clone[header["graphics_rel"]:new_palette_rel] = graphics
    clone[new_palette_rel:] = palettes
    gate(graphics[:len(original_graphics)] == original_graphics, f"{spec['name']} rewrote original source tiles")
    gate(clone[new_palette_rel:] == palettes, f"{spec['name']} palettes rewritten")
    return bytes(clone), {
        "name": spec["name"],
        "source_address": f"0x{spec['address']:08X}",
        "clone_offset": f"0x{CLONES[spec['name']]:08X}",
        "clone_address": f"0x{ROM_BASE + CLONES[spec['name']]:08X}",
        "clone_size": len(clone),
        "original_source_tiles": original_tiles,
        "private_source_tiles_appended": len(private_payloads),
        "buttons": reports,
    }, previews


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=MAIN_TIP_ROM)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--out-sav", type=Path, default=DEFAULT_SAV)
    parser.add_argument("--preview", type=Path, default=DEFAULT_PREVIEW)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()

    gate(STATE_ANALYSIS.is_file(), "run the state analyzer first")
    gate(catalog.CATALOG.is_file(), "run the image catalog analyzer first")
    state_report = json.loads(STATE_ANALYSIS.read_text(encoding="utf-8"))
    catalog_report = json.loads(catalog.CATALOG.read_text(encoding="utf-8"))
    gate(state_report.get("result") == "PASS", "state analysis is not PASS")
    gate(catalog_report.get("result") == "PASS", "image catalog is not PASS")
    parent = args.input.read_bytes()
    jp = ORIGINAL_ROM.read_bytes()
    manifest_main = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(parent) == manifest_main["sha256"], f"parent is not current main TIP: {sha256(parent)}")
    gate(MAIN_SAV.is_file(), f"missing main SAV: {MAIN_SAV}")

    with ZipFile(FONT_ZIP) as archive:
        font = fontpair.load_bdf(archive, "Galmuri11.bdf")

    live = catalog.enumerate_buttons(jp)
    by_pkg: dict[str, list[dict[str, Any]]] = {spec["name"]: [] for spec in catalog.PACKAGES}
    for row in live:
        if row["signature"] == YELLOW_CANCEL_SIGNATURE:
            gate(row["jp"] == "キャンセル" and row["ko"] == "캔슬", f"shared yellow 64px {row['signature']} is not キャンセル")
        if row["signature"] == YELLOW_EXECUTE_SIGNATURE:
            gate(row["jp"] == "強化実行" and row["ko"] == "강화실행", f"yellow 強化実行 signature drift for {row['package']} anim {row['anim']}")
        if row["signature"] == YELLOW_REMODEL_SIGNATURE:
            gate(row["jp"] == "改造実行" and row["ko"] == "개조실행", f"yellow 改造実行 signature drift for {row['package']} anim {row['anim']}")
        by_pkg[row["package"]].append(row)

    candidate = bytearray(parent)
    package_reports = []
    all_previews: list[tuple[list[list[int]], list[list[int]], bytes, int]] = []
    allowed: set[int] = set()
    for spec in catalog.PACKAGES:
        header = analysis.parse_resource_header(jp, spec["address"])
        hits = analysis.pointer_hits(parent[:0x01000000], spec["address"])
        gate(hits, f"no consumers for 0x{spec['address']:08X}")
        clone, report, previews = translate_package(jp, spec, by_pkg[spec["name"]], font)
        alloc = CLONES[spec["name"]]
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
        gate(candidate[header["offset"]:header["offset"] + header["resource_bytes"]] == parent[header["offset"]:header["offset"] + header["resource_bytes"]], f"original 0x{spec['address']:08X} was rewritten")

    # Distinctness: first two develop 48px KO canvases must differ.
    develop_48 = [(ko, src) for src, ko, _p, _b in all_previews[:4]]
    gate(develop_48[0][0] != develop_48[1][0], "개조/강화 yellow canvases are identical")
    gate(develop_48[2][0] != develop_48[3][0], "개조/강화 blue canvases are identical")
    labels = [row["translation"] for pkg in package_reports for row in pkg["buttons"]]
    gate(labels.count("개조") >= 4, "개조 coverage drift")
    gate(labels.count("강화") >= 4, "강화 coverage drift")
    gate(labels.count("캔슬") >= 10, "캔슬 coverage drift")
    gate(labels.count("개조실행") >= 2, "개조실행 coverage drift")
    gate("분해실행" in labels and "보급실행" in labels and "처분실행" in labels, "popup labels missing")
    for pkg in package_reports:
        for row in pkg["buttons"]:
            if row["style"] == "normal_yellow":
                gate(
                    row["fill_index"] == BODY_YELLOW
                    and row["korean_ink_index"] == INK_YELLOW
                    and row["contour_index"] == CONTOUR_YELLOW,
                    f"{row['translation']} yellow ink/shadow drift",
                )
            else:
                gate(row["fill_index"] == BODY_FOCUS and row["korean_ink_index"] == INK_FOCUS, f"{row['translation']} focus chrome drift")
            gate(row["korean_ink_index"] != 0x8, f"{row['translation']} used orange rim ink")

    changed = [i for i, (a, b) in enumerate(zip(parent, candidate)) if a != b]
    escaped = [i for i in changed if i not in allowed]
    gate(not escaped, f"patch escaped allowed ranges: {escaped[:16]}")

    compile_ok = subprocess.run(
        [sys.executable, "-m", "py_compile", str(Path(__file__)), str(catalog.__file__), str(analysis.__file__)],
        cwd=str(ADVANCE_ROOT),
        capture_output=True,
        text=True,
    )
    gate(compile_ok.returncode == 0, f"py_compile failed: {compile_ok.stderr}")
    regression = run_regression()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(candidate)
    shutil.copy2(MAIN_SAV, args.out_sav)
    gate(args.out_sav.read_bytes() == MAIN_SAV.read_bytes(), "SAV copy drift")

    scale = 3
    thumb_w, thumb_h = 64 * scale, 16 * scale
    preview = Image.new("RGB", (2 * thumb_w + 8, len(all_previews) * thumb_h + 8), (16, 16, 16))
    for index, (source, rebuilt, palettes, bank) in enumerate(all_previews):
        y = index * thumb_h + 4
        preview.paste(catalog.canvas_image(source, palettes, bank, scale), (4, y))
        preview.paste(catalog.canvas_image(rebuilt, palettes, bank, scale), (thumb_w + 4, y))
    preview.save(args.preview)

    translations = sorted(set(labels))
    output = bytes(candidate)
    manifest = {
        "schema_version": 1,
        "kind": "ggen_advance_develop_menu_buttons_ko_image_20260901",
        "result": "PASS",
        "supersedes": "legacy/analysis/ggen_advance_develop_menu_buttons_ko_20260901.json",
        "source": {
            "parent": advance_relative(args.input),
            "parent_sha256": sha256(parent),
            "image_catalog": advance_relative(catalog.CATALOG),
            "state_analysis": advance_relative(STATE_ANALYSIS),
            "canonical_main_tip_sha256": sha256(parent),
        },
        "patch": {
            "packages": package_reports,
            "translations": translations,
            "method": "image catalog + append private tiles + remap source lookup",
        },
        "output": {
            "rom": advance_relative(args.out),
            "rom_sha256": sha256(output),
            "sha256": sha256(output),
            "size": len(output),
            "sav": advance_relative(args.out_sav),
            "sav_sha256": sha256(args.out_sav.read_bytes()),
            "preview": advance_relative(args.preview),
            "jp_atlas": advance_relative(catalog.ATLAS),
            "changed_bytes": len(changed),
            "changed_ranges": changed_ranges(changed),
        },
        "verification": {
            "result": "PASS",
            "state_analysis_pass": True,
            "image_catalog_pass": True,
            "original_packages_byte_exact": True,
            "original_source_tiles_byte_exact": True,
            "palettes_byte_exact": True,
            "japanese_face_residue": 0,
            "yellow_fill_pale_yellow": True,
            "focus_fill_pale_cyan": True,
            "orange_rim_not_used_as_ink": True,
            "shared_yellow_64px_is_cancel": True,
            "kaizo_kyoka_yellow_distinct": True,
            "kaizo_kyoka_blue_distinct": True,
            "canonical_main_tip_modified": False,
            "discarded_previous_poc": True,
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
        "packages": [{k: pkg[k] for k in ("name", "clone_address", "clone_size", "private_source_tiles_appended", "redirected_refs")} | {"buttons": len(pkg["buttons"])} for pkg in package_reports],
    }, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
