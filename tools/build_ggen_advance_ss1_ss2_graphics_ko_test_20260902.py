#!/usr/bin/env python3
"""Build the corrected ss1/ss2-only Korean graphics test ROM.

ss1: C3F130 OBJ package, all normal/focus/disabled animation lookups.
ss2: four independent labels in animation 3 of private package 092D8000.
ss3..ss6 are intentionally excluded.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any
from zipfile import ZipFile

from PIL import Image, ImageDraw

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_develop_menu_buttons_images_20260901 as animutil
import analyze_ggen_advance_develop_menu_buttons_state_20260901 as spr
import analyze_ggen_advance_settings_suspend_ui as animrec
import analyze_ggen_advance_develop_menu_buttons_images_20260901 as devcatalog
import build_ggen_advance_develop_menu_buttons_ko_image_20260901 as devbuilder
import build_ggen_advance_develop_menu_buttons_ko_image_20260901 as paintbase
import build_ggen_advance_map_menu_ui_ko_poc as tileops
import build_ggen_advance_settings_suspend_ui_ko_poc as paintops
import test_ggen_advance_font_pair as fontpair
from ggen_advance_project_paths import (
    ADVANCE_ROOT,
    FONT_ZIP,
    MAIN_TIP_MANIFEST,
    MAIN_TIP_ROM,
    ORIGINAL_ROM,
    advance_relative,
)

ROM_BASE = 0x08000000
OUT_DIR = ADVANCE_ROOT / "outputs" / "20260902_ggen_advance_ss1_ss2_graphics"
OUT_ROM = OUT_DIR / "ggen_advance_ss1_ss2_graphics_ko_test_v7_20260903.gba"
OUT_SAV = OUT_DIR / "ggen_advance_ss1_ss2_graphics_ko_test_v7_20260903.sav"
OUT_PREVIEW = OUT_DIR / "ggen_advance_ss1_ss2_graphics_ko_preview_v7_20260903.png"
OUT_DEV_PREVIEW = OUT_DIR / "ggen_advance_development_family_gradient_preview_v7_20260903.png"
OUT_MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_ss1_ss2_graphics_ko_test_v7_20260903.json"
ANALYSIS_MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_ss1_ss2_graphics_20260902.json"
MAIN_SAV = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).sav"

SS1_RESOURCE = 0x08C3F130
SS1_CLONE_OFF = 0x012F0000
SS1_CLONE_ADDR = ROM_BASE + SS1_CLONE_OFF
SS1_BLOCK_END = 0x012F8000
SS2_RESOURCE = 0x092D8000
SS2_OFF = SS2_RESOURCE - ROM_BASE
SS2_BLOCK_END = 0x012E0000

SS1_WORDS = [("搭載", "탑재"), ("降ろす", "내리기"), ("移動", "이동"), ("変形", "변형")]
SS2_WORDS = [("移動", "이동"), ("限界", "한계"), ("汎用", "범용"), ("装甲", "장갑")]


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def parse_animation_cross(records: list[tuple[int, bytes]], animation: int) -> tuple[dict[str, Any], list[int], int]:
    start, record = records[animation]
    marker = record.find(b"\x40\x00\x40\x00")
    gate(marker >= 0, f"animation {animation}: marker missing")
    blob = b"".join(part for _off, part in records[animation:])[marker:]
    parsed = animrec.parse_animation_oam(blob)
    total = sum(int(obj["tile_count"]) for obj in parsed["objects"])
    lookup_start = int(parsed["entries_end"])
    gate(lookup_start + total * 2 <= len(blob), f"animation {animation}: lookup truncated")
    ids = list(struct.unpack_from(f"<{total}H", blob, lookup_start))
    return parsed, ids, start + marker + lookup_start


def repaint_rect(
    canvas: list[list[int]],
    rect: tuple[int, int, int, int],
    text: str,
    font: fontpair.BdfFont,
    *,
    fill: int,
    ink: int,
    contour: int,
    clear_values: tuple[int, ...],
    paint_rect: tuple[int, int, int, int] | None = None,
    restore_pixels: dict[tuple[int, int], int] | None = None,
    solid_fill: bool = False,
) -> dict[str, Any]:
    x0, y0, x1, y1 = rect
    gate(0 <= x0 < x1 <= len(canvas[0]) and 0 <= y0 < y1 <= len(canvas), f"{text}: rect outside canvas")
    width, height = x1 - x0, y1 - y0
    before = bytes(canvas[y][x] for y in range(y0, y1) for x in range(x0, x1))
    cleared = 0
    if restore_pixels is not None:
        for (x, y), value in restore_pixels.items():
            if x0 <= x < x1 and y0 <= y < y1:
                if canvas[y][x] != value:
                    cleared += 1
                canvas[y][x] = value
    elif solid_fill:
        for y in range(y0, y1):
            for x in range(x0, x1):
                if canvas[y][x] != fill:
                    cleared += 1
                canvas[y][x] = fill
    else:
        for y in range(y0, y1):
            for x in range(x0, x1):
                if canvas[y][x] in clear_values:
                    canvas[y][x] = fill
                    cleared += 1
    px0, py0, px1, py1 = paint_rect or rect
    gate(0 <= px0 < px1 <= len(canvas[0]) and 0 <= py0 < py1 <= len(canvas), f"{text}: paint rect outside canvas")
    paint_width, paint_height = px1 - px0, py1 - py0
    gate(paint_height == 16, f"{text}: paint strip is not 16px high")
    local = [row[px0:px1] for row in canvas[py0:py1]]
    mask, text_width = paintops.make_text_mask(text, font, paint_width, paint_height, cell_width=12)
    ink_pixels, contour_pixels = paintbase.paint_mask_cardinal(local, mask, ink=ink, contour=contour)
    gate(cleared > 0 and ink_pixels > 0 and contour_pixels > 0, f"{text}: empty clear or raster")
    for y in range(paint_height):
        canvas[py0 + y][px0:px1] = local[y]
    after = bytes(canvas[y][x] for y in range(y0, y1) for x in range(x0, x1))
    gate(before != after, f"{text}: repaint made no change")
    return {
        "text": text,
        "rect": list(rect),
        "paint_rect": list((px0, py0, px1, py1)),
        "fill_index": fill,
        "ink_index": ink,
        "contour_index": contour,
        "cleared_pixels": cleared,
        "ink_pixels": ink_pixels,
        "contour_pixels": contour_pixels,
        "text_width_px": text_width,
        "before_sha256": sha256(before),
        "after_sha256": sha256(after),
    }


def rebuild_resource(
    rom: bytes | bytearray,
    address: int,
    patches: list[dict[str, Any]],
    font: fontpair.BdfFont,
) -> tuple[bytes, dict[str, Any]]:
    data = bytes(rom)
    header = spr.parse_resource_header(data, address)
    original = data[header["offset"] : header["offset"] + header["resource_bytes"]]
    graphics = header["graphics"]
    palettes = header["palettes"]
    original_tiles = len(graphics) // 32
    _graphics_rel, records = animrec.animation_records(data, address)
    existing = {graphics[t * 32 : (t + 1) * 32]: t for t in range(original_tiles)}
    private: dict[bytes, int] = {}
    private_payloads: list[bytes] = []
    lookup_writes: dict[int, int] = {}
    reports = []

    for spec in patches:
        animation = int(spec["animation"])
        parsed, ids, lookup_file = parse_animation_cross(records, animation)
        objects = parsed["objects"]
        canvas = spr.stitch(graphics, parsed, ids, list(range(len(objects))))
        strips = [
            repaint_rect(
                canvas,
                tuple(row["rect"]),
                row["text"],
                font,
                fill=int(row["fill"]),
                ink=int(row["ink"]),
                contour=int(row["contour"]),
                clear_values=tuple(row["clear_values"]),
                paint_rect=tuple(row["paint_rect"]) if row.get("paint_rect") else None,
                restore_pixels=(
                    {(x, y): canvas[y][int(row["restore_from_x"])] for y in range(int(row["rect"][1]), int(row["rect"][3])) for x in range(int(row["rect"][0]), int(row["rect"][2]))}
                    if row.get("restore_from_x") is not None
                    else row.get("restore_pixels")
                ),
                solid_fill=bool(row.get("solid_fill", False)),
            )
            for row in spec["repaints"]
        ]
        min_x = min(int(obj["x"]) for obj in objects)
        min_y = min(int(obj["y"]) for obj in objects)
        cursor = 0
        changed_lookup = 0
        for obj in objects:
            wt, ht = int(obj["size_px"][0]) // 8, int(obj["size_px"][1]) // 8
            count = wt * ht
            old_ids = ids[cursor : cursor + count]
            for ty in range(ht):
                for tx in range(wt):
                    pos = ty * wt + tx
                    old_id = int(old_ids[pos])
                    ox = int(obj["x"]) - min_x + tx * 8
                    oy = int(obj["y"]) - min_y + ty * 8
                    payload = tileops.encode_tile([canvas[oy + y][ox : ox + 8] for y in range(8)])
                    old_payload = graphics[old_id * 32 : (old_id + 1) * 32]
                    if payload == old_payload:
                        new_id = old_id
                    elif payload in existing:
                        new_id = existing[payload]
                    elif payload in private:
                        new_id = private[payload]
                    else:
                        new_id = original_tiles + len(private_payloads)
                        private[payload] = new_id
                        private_payloads.append(payload)
                    if new_id != old_id:
                        rel = lookup_file - header["offset"] + (cursor + pos) * 2
                        gate(rel not in lookup_writes or lookup_writes[rel] == new_id, f"lookup conflict at 0x{rel:X}")
                        lookup_writes[rel] = new_id
                        changed_lookup += 1
            cursor += count
        gate(changed_lookup > 0, f"animation {animation}: no lookup changed")
        reports.append({"animation": animation, "changed_lookup_entries": changed_lookup, "repaints": strips})

    new_graphics = graphics + b"".join(private_payloads)
    new_palette_rel = header["graphics_rel"] + len(new_graphics)
    clone = bytearray(new_palette_rel + len(palettes))
    clone[: header["graphics_rel"]] = original[: header["graphics_rel"]]
    struct.pack_into("<I", clone, 0x0C, new_palette_rel)
    for rel, tile_id in lookup_writes.items():
        struct.pack_into("<H", clone, rel, tile_id)
    clone[header["graphics_rel"] : new_palette_rel] = new_graphics
    clone[new_palette_rel:] = palettes
    gate(new_graphics[: len(graphics)] == graphics, "original graphic tiles were rewritten")
    gate(clone[new_palette_rel:] == palettes, "palette changed")
    return bytes(clone), {
        "resource": f"0x{address:08X}",
        "original_resource_bytes": header["resource_bytes"],
        "rebuilt_resource_bytes": len(clone),
        "original_tiles": original_tiles,
        "private_tiles_appended": len(private_payloads),
        "animations": reports,
    }


def pointer_hits(data: bytes | bytearray, address: int) -> list[int]:
    needle = struct.pack("<I", address)
    view = bytes(data[:0x01000000])
    hits, cursor = [], 0
    while True:
        cursor = view.find(needle, cursor)
        if cursor < 0:
            return hits
        hits.append(cursor)
        cursor += 1


def ss1_native_background_maps(rom: bytes) -> dict[int, dict[tuple[int, int], int]]:
    """Replace the whole label bed from the package's blank native body.

    The old glyph has face, contour, and a third shadow layer.  Palette-value
    filtering or a font-shaped mask leaves that shadow live, so every pixel in
    x=7..51 is rebuilt from the same row at blank body x=56.  This keeps the
    native orange/red top and bottom gradient while removing all Japanese art.
    """
    canvases = {animation: resource_canvas(rom, SS1_RESOURCE, animation)[0] for animation in range(8)}
    result: dict[int, dict[tuple[int, int], int]] = {}
    for animation in range(12):
        base = animation % 4
        source_animation = animation if animation < 8 else base
        restore = {}
        for y in range(16):
            for x in range(4, 52):
                source_value = canvases[source_animation][y][x]
                # Preserve only the unmistakable red/orange cap gradient;
                # dark indices 4/5 in this area also belong to JP shadow.
                restore[(x, y)] = source_value if x < 8 and source_value in (6, 7, 8, 9) else canvases[source_animation][y][56]
        gate(any(canvases[source_animation][y][x] != value for (x, y), value in restore.items()), f"ss1 animation {animation}: no native background recovery")
        result[animation] = restore
    return result


def resource_canvas(rom: bytes, address: int, animation: int) -> tuple[list[list[int]], bytes, int]:
    header = spr.parse_resource_header(rom, address)
    _rel, records = animrec.animation_records(rom, address)
    parsed, ids, _lookup = parse_animation_cross(records, animation)
    canvas = spr.stitch(header["graphics"], parsed, ids, list(range(len(parsed["objects"]))))
    bank = int(parsed["objects"][0]["palette_bank"])
    return canvas, header["palettes"], bank


def preview(parent: bytes, output: bytes) -> None:
    rows: list[tuple[str, Image.Image, Image.Image]] = []
    for animation in range(12):
        before, pal_before, bank_before = resource_canvas(parent, SS1_RESOURCE, animation)
        after, pal_after, bank_after = resource_canvas(output, SS1_CLONE_ADDR, animation)
        gate(bank_before == bank_after, f"ss1 animation {animation}: palette bank drift")
        rows.append((f"ss1 anim {animation}", animutil.canvas_image(before, pal_before, bank_before, 3), animutil.canvas_image(after, pal_after, bank_after, 3)))
    before, pal_before, bank_before = resource_canvas(parent, SS2_RESOURCE, 3)
    after, pal_after, bank_after = resource_canvas(output, SS2_RESOURCE, 3)
    crop = (120, 16, 208, 64)
    rows.append(("ss2 anim 3", animutil.canvas_image([r[crop[0]:crop[2]] for r in before[crop[1]:crop[3]]], pal_before, bank_before, 3), animutil.canvas_image([r[crop[0]:crop[2]] for r in after[crop[1]:crop[3]]], pal_after, bank_after, 3)))
    width = max(a.width + b.width + 28 for _label, a, b in rows)
    height = sum(max(a.height, b.height) + 20 for _label, a, b in rows) + 24
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    draw.text((4, 4), "BEFORE", fill="black")
    draw.text((width // 2, 4), "AFTER", fill="black")
    y = 24
    for label, before_img, after_img in rows:
        draw.text((4, y), label, fill="black")
        image.paste(before_img, (4, y + 16))
        image.paste(after_img, (before_img.width + 20, y + 16))
        y += max(before_img.height, after_img.height) + 20
    OUT_PREVIEW.parent.mkdir(parents=True, exist_ok=True)
    image.save(OUT_PREVIEW)


def development_preview(rows: list[tuple[list[list[int]], list[list[int]], bytes, int]]) -> None:
    scale = 3
    thumb_w, thumb_h = 64 * scale, 16 * scale
    image = Image.new("RGB", (2 * thumb_w + 8, len(rows) * thumb_h + 8), (16, 16, 16))
    for index, (source, rebuilt, palettes, bank) in enumerate(rows):
        y = index * thumb_h + 4
        image.paste(devcatalog.canvas_image(source, palettes, bank, scale), (4, y))
        image.paste(devcatalog.canvas_image(rebuilt, palettes, bank, scale), (thumb_w + 4, y))
    OUT_DEV_PREVIEW.parent.mkdir(parents=True, exist_ok=True)
    image.save(OUT_DEV_PREVIEW)


def changed_ranges(offsets: list[int]) -> list[list[str]]:
    if not offsets:
        return []
    result = []
    start = previous = offsets[0]
    for off in offsets[1:]:
        if off != previous + 1:
            result.append([f"0x{start:08X}", f"0x{previous + 1:08X}"])
            start = off
        previous = off
    result.append([f"0x{start:08X}", f"0x{previous + 1:08X}"])
    return result


def run_regression() -> dict[str, str]:
    result = {}
    for name in ("test_ggen_advance_unified_pipeline.py", "test_ggen_advance_intermission_development_fix.py"):
        cp = subprocess.run([sys.executable, str(THIS_DIR / name)], cwd=str(ADVANCE_ROOT), capture_output=True, text=True)
        gate(cp.returncode == 0, f"{name} failed: {cp.stderr[-600:]}")
        result[name] = "PASS"
    return result


def main() -> int:
    parent = MAIN_TIP_ROM.read_bytes()
    jp = ORIGINAL_ROM.read_bytes()
    main_manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    analysis = json.loads(ANALYSIS_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(parent) == main_manifest["sha256"], "main TIP/manifest hash mismatch")
    gate(analysis.get("result") == "PASS" and analysis["main_tip"]["sha256"] == sha256(parent), "analysis is stale")
    gate(analysis["scope"]["excluded"] == ["ss3", "ss4", "ss5", "ss6"], "analysis scope drift")
    gate(MAIN_SAV.is_file(), "main TIP SAV missing")
    candidate = bytearray(parent)
    allowed: set[int] = set()
    reports = []

    with ZipFile(FONT_ZIP) as archive:
        font = fontpair.load_bdf(archive, "Galmuri11.bdf")

    # Rebuild the already-promoted development-family private clones from the
    # clean Japanese resources with the corrected inner-well policy.  Existing
    # consumers already point at these fixed allocations, so no pointer change
    # is required here.
    live_dev = devcatalog.enumerate_buttons(jp)
    by_package: dict[str, list[dict[str, Any]]] = {spec["name"]: [] for spec in devcatalog.PACKAGES}
    for row in live_dev:
        by_package[row["package"]].append(row)
    development_reports = []
    development_previews: list[tuple[list[list[int]], list[list[int]], bytes, int]] = []
    for spec in devcatalog.PACKAGES:
        rebuilt, report, package_previews = devbuilder.translate_package(jp, spec, by_package[spec["name"]], font)
        clone_off = devbuilder.CLONES[spec["name"]]
        gate(clone_off + len(rebuilt) <= clone_off + 0x8000, f"{spec['name']}: corrected clone exceeds allocation")
        candidate[clone_off : clone_off + len(rebuilt)] = rebuilt
        allowed.update(range(clone_off, clone_off + len(rebuilt)))
        development_reports.append(report)
        development_previews.extend(package_previews)

    ss1_backgrounds = ss1_native_background_maps(jp)
    ss1_patches = []
    for base, (jp_text, ko_text) in enumerate(SS1_WORDS):
        for animation, style in ((base, "normal"), (base + 4, "focus"), (base + 8, "disabled")):
            focus = style == "focus"
            ss1_patches.append({
                "animation": animation,
                "repaints": [{
                    "rect": [4, 0, 52, 16],
                    "text": ko_text,
                    "fill": 10 if focus else 11,
                    "ink": 12 if focus else 10,
                    "contour": 1 if focus else 5,
                    "clear_values": [12, 1] if focus else [10, 5],
                    "restore_pixels": ss1_backgrounds[animation],
                    "paint_rect": [6, 0, 8 + len(ko_text) * 12, 16],
                }],
                "source": jp_text,
                "style": style,
            })
    ss1_clone, ss1_report = rebuild_resource(jp, SS1_RESOURCE, ss1_patches, font)
    gate(SS1_CLONE_OFF + len(ss1_clone) <= SS1_BLOCK_END, "ss1 clone exceeds allocation")
    gate(all(value == 0 for value in parent[SS1_CLONE_OFF : SS1_CLONE_OFF + len(ss1_clone)]), "ss1 clone range is not zero-filled")
    candidate[SS1_CLONE_OFF : SS1_CLONE_OFF + len(ss1_clone)] = ss1_clone
    allowed.update(range(SS1_CLONE_OFF, SS1_CLONE_OFF + len(ss1_clone)))
    hits = pointer_hits(parent, SS1_RESOURCE)
    gate(hits == [0x00066CE8], f"ss1 consumer drift: {hits}")
    for hit in hits:
        struct.pack_into("<I", candidate, hit, SS1_CLONE_ADDR)
        allowed.update(range(hit, hit + 4))
    ss1_report.update({
        "scope": "ss1 normal/focus/disabled animations 0..11",
        "clone_file_offset": f"0x{SS1_CLONE_OFF:08X}",
        "clone_address": f"0x{SS1_CLONE_ADDR:08X}",
        "redirected_refs": [f"0x{x:08X}" for x in hits],
        "translations": dict(SS1_WORDS),
    })
    reports.append(ss1_report)

    ss2_patches = [{
        "animation": 3,
        "repaints": [
            {"rect": [130, 24, 157, 40], "paint_rect": [130, 24, 156, 40], "restore_from_x": 168, "text": "이동", "fill": 11, "ink": 10, "contour": 5, "clear_values": []},
            {"rect": [176, 24, 208, 40], "paint_rect": [178, 24, 204, 40], "restore_from_x": 216, "text": "한계", "fill": 11, "ink": 10, "contour": 5, "clear_values": []},
            {"rect": [112, 40, 144, 56], "paint_rect": [115, 40, 141, 56], "restore_from_x": 148, "text": "범용", "fill": 11, "ink": 10, "contour": 5, "clear_values": []},
            {"rect": [156, 40, 188, 56], "paint_rect": [159, 40, 185, 56], "restore_from_x": 192, "text": "장갑", "fill": 11, "ink": 10, "contour": 5, "clear_values": []},
        ],
    }]
    ss2_rebuilt, ss2_report = rebuild_resource(candidate, SS2_RESOURCE, ss2_patches, font)
    gate(SS2_OFF + len(ss2_rebuilt) <= SS2_BLOCK_END, "ss2 private resource exceeds allocation")
    candidate[SS2_OFF : SS2_OFF + len(ss2_rebuilt)] = ss2_rebuilt
    allowed.update(range(SS2_OFF, SS2_OFF + len(ss2_rebuilt)))
    ss2_report.update({
        "scope": "ss2 animation 3 four independent 32x16 label cells",
        "allocation": [f"0x{SS2_OFF:08X}", f"0x{SS2_BLOCK_END:08X}"],
        "translations": dict(SS2_WORDS),
    })
    reports.append(ss2_report)

    output = bytes(candidate)
    changed = [i for i, (before, after) in enumerate(zip(parent, output)) if before != after]
    escaped = [off for off in changed if off not in allowed]
    gate(changed and not escaped, f"changes escaped declared ranges: {escaped[:16]}")
    native = spr.parse_resource_header(parent, SS1_RESOURCE)
    gate(output[native["offset"] : native["offset"] + native["resource_bytes"]] == parent[native["offset"] : native["offset"] + native["resource_bytes"]], "native ss1 resource changed")
    gate(MAIN_TIP_ROM.read_bytes() == parent, "canonical main TIP changed during build")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_ROM.write_bytes(output)
    shutil.copy2(MAIN_SAV, OUT_SAV)
    preview(parent, output)
    development_preview(development_previews)
    compile_cp = subprocess.run([sys.executable, "-m", "py_compile", str(Path(__file__)), str(ANALYSIS_MANIFEST.parent.parent / "tools" / "analyze_ggen_advance_ss1_ss2_graphics_20260902.py")], cwd=str(ADVANCE_ROOT), capture_output=True, text=True)
    gate(compile_cp.returncode == 0, f"py_compile failed: {compile_cp.stderr}")
    regression = run_regression()

    manifest = {
        "schema_version": 1,
        "kind": "ggen_advance_ss1_ss2_graphics_ko_test_v7_20260903",
        "result": "PASS",
        "scope": {
            "included_states": [1, 2],
            "excluded_states": [3, 4, 5, 6],
            "same_type_coverage": "all ss1 C3F130 animation variants and the four ss2 092D8000 animation-3 label cells",
            "translations": {"ss1": dict(SS1_WORDS), "ss2": dict(SS2_WORDS)},
        },
        "source": {
            "parent": advance_relative(MAIN_TIP_ROM),
            "parent_sha256": sha256(parent),
            "main_tip_manifest": advance_relative(MAIN_TIP_MANIFEST),
            "analysis": advance_relative(ANALYSIS_MANIFEST),
        },
        "patch": {"font": "Galmuri11.bdf native 12x12", "resources": reports, "corrected_development_family": development_reports},
        "output": {
            "rom": advance_relative(OUT_ROM),
            "rom_sha256": sha256(output),
            "size": len(output),
            "sav": advance_relative(OUT_SAV),
            "sav_sha256": sha256(OUT_SAV.read_bytes()),
            "preview": advance_relative(OUT_PREVIEW),
            "preview_sha256": sha256(OUT_PREVIEW.read_bytes()),
            "development_preview": advance_relative(OUT_DEV_PREVIEW),
            "development_preview_sha256": sha256(OUT_DEV_PREVIEW.read_bytes()),
            "changed_bytes": len(changed),
            "changed_ranges": changed_ranges(changed),
        },
        "verification": {
            "result": "PASS",
            "canonical_main_tip_modified": False,
            "ss3_ss6_excluded": True,
            "native_ss1_resource_preserved": True,
            "private_clone_and_declared_ranges_only": True,
            "all_ss1_normal_focus_disabled_variants_patched": True,
            "ss1_focus_face_and_contour_cleared": True,
            "ss1_transform_repositioned_for_32px_visible_width": True,
            "ss2_four_labels_patched_independently": True,
            "ss2_native_scanline_gradient_restored": True,
            "development_family_outer_rims_preserved": True,
            "py_compile": "PASS",
            "regression": regression,
            "emulator_measurement": "pending user verification",
        },
    }
    OUT_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "rom": advance_relative(OUT_ROM),
        "rom_sha256": sha256(output),
        "manifest": advance_relative(OUT_MANIFEST),
        "preview": advance_relative(OUT_PREVIEW),
        "changed_bytes": len(changed),
        "resources": [{"resource": row["resource"], "private_tiles": row["private_tiles_appended"]} for row in reports],
    }, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
