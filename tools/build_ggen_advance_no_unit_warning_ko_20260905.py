#!/usr/bin/env python3
"""Koreanize the develop/remodel 'no selectable units' warning popup.

Live owner is sprite package 0x08CD9250 animation 0, bound from current main
TIP Korean.ss3 (14 OBJ, 126/126 source tiles).  Animation 1 is the sibling
パーツがありません plate.  Animation 2 is an empty band template without the
native right-edge 6/7 rounding, so it is not used as a donor.

Japanese face (index 11) and attached brown shadow (index 5) are cleared by
row-restore from unmarked pixels on the same scanline.  Columns 112..127 — the
original rounded cap — stay byte-exact.  Galmuri11 Regular is painted with a
1px 8-neighbour shadow that fully surrounds each glyph, matching the original
JP plates rather than a bottom-right-only drop shadow.

Original 0x08CD9250 is not rewritten.  A private clone is placed in zero-filled
expansion and the unique consumer literal is redirected.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import struct
import sys
from collections import Counter
from pathlib import Path
from typing import Any
from zipfile import ZipFile

from PIL import Image

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_cd9250_warning_family_20260905 as fam
import analyze_ggen_advance_develop_menu_buttons_state_20260901 as analysis
import analyze_ggen_advance_settings_suspend_ui as sprite
import analyze_ggen_advance_ss3_no_unit_warning_20260905 as dump
import build_ggen_advance_map_menu_ui_ko_poc as tileops
import build_ggen_advance_turn_ability_overlays_20260905 as raster
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
RESOURCE = 0x08CD9250
CONSUMER = 0x000642FC
CLONE_OFFSET = 0x01300000
CLONE_ADDRESS = ROM_BASE + CLONE_OFFSET
ALLOC_SPAN = 0x4000
OUT_DIR = ADVANCE_ROOT / "outputs" / "20260905_ggen_advance_no_unit_warning"
DEFAULT_OUT = OUT_DIR / "ggen_advance_no_unit_warning_ko_candidate_20260905.gba"
DEFAULT_SAV = OUT_DIR / "ggen_advance_no_unit_warning_ko_candidate_20260905.sav"
DEFAULT_MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_no_unit_warning_ko_candidate_20260905.json"
MAIN_SAV = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).sav"
STATE = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).ss3"

FACE = 11
SHADOW = 5
ROUND_X0 = 112

TARGETS: tuple[dict[str, Any], ...] = (
    {
        "anim": 0,
        "jp": "選択可能なユニットがありません",
        "lines": ("선택 가능한 유닛이", "없습니다"),
        "y_origins": (6, 18),
    },
    {
        "anim": 1,
        "jp": "パーツがありません",
        "lines": ("부품이 없습니다",),
        "y_origins": (10,),
    },
)


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def pointer_hits(data: bytes, address: int) -> list[int]:
    needle = struct.pack("<I", address)
    hits: list[int] = []
    cursor = 0
    while True:
        found = data.find(needle, cursor)
        if found < 0:
            return hits
        hits.append(found)
        cursor = found + 1


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


def parse_anim(rom: bytes, address: int, anim: int) -> dict[str, Any]:
    _gfx_rel, records = sprite.animation_records(rom, address)
    start, record = records[anim]
    marker = analysis.find_marker(record)
    gate(marker is not None, f"animation {anim} marker missing")
    sliced = record[marker:]
    parsed = sprite.parse_animation_oam(sliced)
    total = sum(int(obj["tile_count"]) for obj in parsed["objects"])
    blob = b"".join(item[1] for item in records[anim:])[marker:]
    gate(parsed["entries_end"] + total * 2 <= len(blob), f"animation {anim} lookup truncated")
    ids = list(struct.unpack_from(f"<{total}H", blob, parsed["entries_end"]))
    lookup_rel = start + marker + int(parsed["entries_end"]) - (address - ROM_BASE)
    by_object: list[list[int]] = []
    cursor = 0
    for obj in parsed["objects"]:
        count = int(obj["tile_count"])
        by_object.append(ids[cursor : cursor + count])
        cursor += count
    text_idx = fam.text_object_indices(parsed)
    return {
        "parsed": parsed,
        "ids": ids,
        "by_object": by_object,
        "lookup_rel": lookup_rel,
        "text_idx": text_idx,
    }


def glyph_mask(canvas: list[list[int]], radius: int = 2) -> set[tuple[int, int]]:
    height, width = len(canvas), len(canvas[0])
    face = {(x, y) for y in range(height) for x in range(width) if canvas[y][x] == FACE}
    attached: set[tuple[int, int]] = set()
    for x, y in face:
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                xx, yy = x + dx, y + dy
                if 0 <= xx < width and 0 <= yy < height and canvas[yy][xx] == SHADOW:
                    attached.add((xx, yy))
    return face | attached


def restore_native_rounds(source: list[list[int]]) -> tuple[list[list[int]], dict[str, Any]]:
    """Clear JP face+shadow; keep unmarked chrome including the right round cap."""
    height, width = len(source), len(source[0])
    gate(width == 128 and height == 32, "warning text plane must be 128x32")
    mask = glyph_mask(source)
    gate(mask, "no Japanese face/shadow pixels")
    gate(all(x < ROUND_X0 for x, _y in mask), "glyph mask overlaps native round cap")
    restored = [row[:] for row in source]
    row_donors: list[dict[str, int]] = []
    for y in range(height):
        unmarked = [x for x in range(width) if (x, y) not in mask]
        gate(unmarked, f"scanline {y} has no native chrome sample")
        # Prefer an interior unmarked pixel so the 6/7 cap is not smeared left.
        interior = [x for x in unmarked if x < ROUND_X0]
        donor_x = max(interior) if interior else min(unmarked)
        donor = source[y][donor_x]
        row_donors.append({"y": y, "donor_x": donor_x, "index": donor})
        for x in range(width):
            if (x, y) in mask:
                restored[y][x] = donor
    gate(
        [row[ROUND_X0:] for row in restored] == [row[ROUND_X0:] for row in source],
        "right-edge rounding was rewritten",
    )
    gate(not any(pixel == FACE for row in restored for pixel in row), "Japanese face remained")
    gate(not any(pixel == SHADOW for row in restored for pixel in row), "Japanese shadow remained")
    return restored, {
        "mask_pixels": len(mask),
        "round_x0": ROUND_X0,
        "row_donors": row_donors,
        "right_cap_byte_exact": True,
    }


def paint_full_outline(
    canvas: list[list[int]],
    font: fontpair.BdfFont,
    lines: tuple[str, ...],
    y_origins: tuple[int, ...],
    clip_x1: int,
) -> dict[str, Any]:
    height, width = len(canvas), len(canvas[0])
    reports: list[dict[str, Any]] = []
    for text, y0 in zip(lines, y_origins):
        ink, text_w, text_h = raster.native_ink(font, text)
        x0 = 1 + (clip_x1 - 2 - text_w) // 2
        gate(x0 >= 1, f"{text!r} does not fit interior width {clip_x1}")
        gate(y0 >= 1 and y0 + text_h + 1 <= height, f"{text!r} vertical overflow")
        gate(x0 + text_w + 1 <= clip_x1, f"{text!r} outline would overlap round cap")
        shifted = {(x0 + x, y0 + y) for x, y in ink}
        outline = raster.dilate(shifted, clip_x1, height) - shifted
        shadow_px = 0
        face_px = 0
        for x, y in outline:
            if 0 <= y < height and 0 <= x < clip_x1:
                canvas[y][x] = SHADOW
                shadow_px += 1
        for x, y in shifted:
            if 0 <= y < height and 0 <= x < clip_x1:
                canvas[y][x] = FACE
                face_px += 1
        for x, y in shifted:
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    nx, ny = x + dx, y + dy
                    if not (0 <= ny < height and 0 <= nx < clip_x1):
                        continue
                    gate(canvas[ny][nx] in {FACE, SHADOW}, f"{text!r} missing 1px shadow at {(nx, ny)}")
        reports.append({
            "text": text,
            "origin": [x0, y0],
            "ink_size": [text_w, text_h],
            "face_pixels": face_px,
            "shadow_pixels": shadow_px,
            "outline": "8-neighbour 1px",
        })
    return {"clip_x1": clip_x1, "lines": reports}


def materialize(
    original_graphics: bytes,
    parsed: dict[str, Any],
    ids: list[int],
    text_idx: list[int],
    plane: list[list[int]],
    lookup_rel: int,
    existing: dict[bytes, int],
    private: list[bytes],
) -> tuple[list[int], int]:
    objects = parsed["objects"]
    by_object: list[list[int]] = []
    cursor = 0
    for obj in objects:
        count = int(obj["tile_count"])
        by_object.append(ids[cursor : cursor + count])
        cursor += count
    objs = [objects[i] for i in text_idx]
    x0 = min(int(obj["x"]) for obj in objs)
    y0 = min(int(obj["y"]) for obj in objs)
    remapped = list(ids)
    changed = 0
    original_tiles = len(original_graphics) // 32
    for index in text_idx:
        obj = objects[index]
        wt = int(obj["size_px"][0]) // 8
        ht = int(obj["size_px"][1]) // 8
        obj_base = sum(int(objects[j]["tile_count"]) for j in range(index))
        for ty in range(ht):
            for tx in range(wt):
                ox = int(obj["x"]) - x0 + tx * 8
                oy = int(obj["y"]) - y0 + ty * 8
                tile = [plane[oy + yy][ox : ox + 8] for yy in range(8)]
                payload = tileops.encode_tile(tile)
                old_id = by_object[index][ty * wt + tx]
                if payload in existing:
                    new_id = existing[payload]
                else:
                    new_id = original_tiles + len(private)
                    existing[payload] = new_id
                    private.append(payload)
                slot = obj_base + ty * wt + tx
                remapped[slot] = new_id
                if new_id != old_id:
                    changed += 1
    return remapped, changed


def canvas_preview(before: list[list[int]], clean: list[list[int]], after: list[list[int]], palettes: bytes) -> Image.Image:
    colors = [dump.rgb555(struct.unpack_from("<H", palettes, i * 2)[0]) for i in range(16)]
    frames = [
        dump.canvas_image(before, colors, 4),
        dump.canvas_image(clean, colors, 4),
        dump.canvas_image(after, colors, 4),
    ]
    gap = 8
    width = frames[0].width
    height = frames[0].height
    sheet = Image.new("RGB", (width, height * 3 + gap * 2), (16, 16, 16))
    for index, frame in enumerate(frames):
        sheet.paste(frame, (0, index * (height + gap)))
    return sheet


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=MAIN_TIP_ROM)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--out-sav", type=Path, default=DEFAULT_SAV)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    parent = args.input.read_bytes()
    jp = ORIGINAL_ROM.read_bytes()
    manifest_main = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(parent) == manifest_main["sha256"], f"parent is not current main TIP: {sha256(parent)}")
    gate(MAIN_SAV.is_file(), f"missing main SAV: {MAIN_SAV}")
    header = analysis.parse_resource_header(parent, RESOURCE)
    jp_header = analysis.parse_resource_header(jp, RESOURCE)
    gate(header["graphics"] == jp_header["graphics"], "current main CD9250 graphics are not JP byte-exact")
    gate(header["palettes"] == jp_header["palettes"], "current main CD9250 palettes are not JP byte-exact")
    hits = pointer_hits(parent, RESOURCE)
    gate(hits == [CONSUMER], f"CD9250 consumers drifted: {[hex(x) for x in hits]}")
    gate(u32(parent, CONSUMER) == RESOURCE, "consumer literal drift")
    gate(all(value == 0 for value in parent[CLONE_OFFSET:CLONE_OFFSET + ALLOC_SPAN]), "clone allocation is not zero-filled")

    with ZipFile(FONT_ZIP) as archive:
        font = fontpair.load_bdf(archive, "Galmuri11.bdf")

    original_graphics = header["graphics"]
    palettes = header["palettes"]
    existing = {original_graphics[i * 32:(i + 1) * 32]: i for i in range(header["source_tiles"])}
    private: list[bytes] = []
    lookup_writes: dict[int, int] = {}
    reports: list[dict[str, Any]] = []
    previews: list[tuple[list[list[int]], list[list[int]], list[list[int]]]] = []

    for spec in TARGETS:
        info = parse_anim(parent, RESOURCE, spec["anim"])
        parsed, ids, text_idx, lookup_rel = info["parsed"], info["ids"], info["text_idx"], info["lookup_rel"]
        source = analysis.stitch(original_graphics, parsed, ids, text_idx)
        cap_before = [row[ROUND_X0:] for row in source]
        clean, restore_report = restore_native_rounds(source)
        painted = [row[:] for row in clean]
        paint_report = paint_full_outline(painted, font, spec["lines"], spec["y_origins"], ROUND_X0)
        gate([row[ROUND_X0:] for row in painted] == cap_before, f"anim {spec['anim']} paint rewrote round cap")
        gate(any(pixel == FACE for row in painted for pixel in row), f"anim {spec['anim']} Korean face missing")
        remapped, changed = materialize(
            original_graphics, parsed, ids, text_idx, painted, lookup_rel, existing, private,
        )
        for slot, new_id in enumerate(remapped):
            if new_id != ids[slot]:
                lookup_writes[lookup_rel + slot * 2] = new_id
        rebuilt = analysis.stitch(original_graphics + b"".join(private), parsed, remapped, text_idx)
        gate(rebuilt == painted, f"anim {spec['anim']} remapped plane drift")
        reports.append({
            "animation": spec["anim"],
            "jp": spec["jp"],
            "ko_lines": list(spec["lines"]),
            "text_objects": text_idx,
            "lookup_rel": hex(lookup_rel),
            "restore": {k: v for k, v in restore_report.items() if k != "row_donors"},
            "row_donors": restore_report["row_donors"],
            "paint": paint_report,
            "lookup_entries_changed": changed,
            "right_cap_preserved": True,
        })
        previews.append((source, clean, painted))
        dump.canvas_image(
            clean,
            [dump.rgb555(struct.unpack_from("<H", palettes, i * 2)[0]) for i in range(16)],
            4,
        ).save(OUT_DIR / f"cd9250_anim{spec['anim']}_clean_round.png")

    graphics = original_graphics + b"".join(private)
    new_palette_rel = header["graphics_rel"] + len(graphics)
    clone = bytearray(new_palette_rel + len(palettes))
    clone[: header["graphics_rel"]] = parent[header["offset"]: header["offset"] + header["graphics_rel"]]
    struct.pack_into("<I", clone, 0x0C, new_palette_rel)
    for rel, new_id in lookup_writes.items():
        struct.pack_into("<H", clone, rel, new_id)
    clone[header["graphics_rel"]: new_palette_rel] = graphics
    clone[new_palette_rel:] = palettes
    gate(graphics[: len(original_graphics)] == original_graphics, "clone rewrote original source tiles")
    gate(clone[new_palette_rel:] == palettes, "clone palettes rewritten")
    gate(len(clone) <= ALLOC_SPAN, f"clone {len(clone)} exceeds allocation {ALLOC_SPAN}")

    candidate = bytearray(parent)
    candidate[CLONE_OFFSET: CLONE_OFFSET + len(clone)] = clone
    struct.pack_into("<I", candidate, CONSUMER, CLONE_ADDRESS)
    allowed = set(range(CLONE_OFFSET, CLONE_OFFSET + len(clone))) | set(range(CONSUMER, CONSUMER + 4))
    changed = [i for i, (a, b) in enumerate(zip(parent, candidate)) if a != b]
    escaped = [i for i in changed if i not in allowed]
    gate(not escaped, f"patch escaped allowed ranges: {escaped[:16]}")
    gate(candidate[header["offset"]: header["offset"] + header["resource_bytes"]] == parent[header["offset"]: header["offset"] + header["resource_bytes"]], "original CD9250 rewritten")
    gate(pointer_hits(bytes(candidate), RESOURCE) == [], "original CD9250 consumer remains")
    gate(u32(candidate, CONSUMER) == CLONE_ADDRESS, "consumer was not redirected to clone")

    info0 = parse_anim(parent, RESOURCE, 2)
    empty = analysis.stitch(original_graphics, info0["parsed"], info0["ids"], info0["text_idx"])
    clone_empty = analysis.stitch(graphics, info0["parsed"], info0["ids"], info0["text_idx"])
    gate(empty == clone_empty, "animation 2 empty plane was remapped")
    gate(not any(pixel == FACE for row in empty for pixel in row), "animation 2 unexpectedly has face ink")

    compile_ok = __import__("subprocess").run(
        [sys.executable, "-m", "py_compile", str(Path(__file__))],
        cwd=str(ADVANCE_ROOT),
        capture_output=True,
        text=True,
    )
    gate(compile_ok.returncode == 0, f"py_compile failed: {compile_ok.stderr}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(candidate)
    shutil.copy2(MAIN_SAV, args.out_sav)
    gate(args.out_sav.read_bytes() == MAIN_SAV.read_bytes(), "SAV copy drift")

    preview = canvas_preview(*previews[0], palettes)
    preview_path = OUT_DIR / "ggen_advance_no_unit_warning_ko_preview_20260905.png"
    preview.save(preview_path)
    if len(previews) > 1:
        canvas_preview(*previews[1], palettes).save(OUT_DIR / "ggen_advance_no_parts_warning_ko_preview_20260905.png")

    full_info = parse_anim(parent, RESOURCE, 0)
    full_before = analysis.stitch(original_graphics, full_info["parsed"], full_info["ids"], list(range(full_info["parsed"]["object_count"])))
    full_after = analysis.stitch(
        graphics,
        full_info["parsed"],
        parse_anim(bytes(candidate), CLONE_ADDRESS, 0)["ids"],
        list(range(full_info["parsed"]["object_count"])),
    )
    colors = [dump.rgb555(struct.unpack_from("<H", palettes, i * 2)[0]) for i in range(16)]
    dump.canvas_image(full_before, colors, 3).save(OUT_DIR / "cd9250_anim0_full_before.png")
    dump.canvas_image(full_after, colors, 3).save(OUT_DIR / "cd9250_anim0_full_after.png")

    output = bytes(candidate)
    manifest = {
        "schema_version": 1,
        "kind": "ggen_advance_no_unit_warning_ko_20260905",
        "result": "PASS",
        "source": {
            "parent": advance_relative(args.input),
            "parent_sha256": sha256(parent),
            "canonical_main_tip_sha256": sha256(parent),
            "state": advance_relative(STATE),
            "resource": hex(RESOURCE),
        },
        "patch": {
            "method": "clone CD9250; row-restore JP face+shadow from unmarked interior; keep x>=112 round cap; Galmuri11 8-neighbour 1px shadow; remap text lookups only",
            "clone_offset": hex(CLONE_OFFSET),
            "clone_address": hex(CLONE_ADDRESS),
            "clone_size": len(clone),
            "original_source_tiles": header["source_tiles"],
            "private_source_tiles_appended": len(private),
            "consumer": hex(CONSUMER),
            "animations": reports,
            "animation_2_untouched": True,
            "original_resource_byte_exact": True,
        },
        "output": {
            "rom": advance_relative(args.out),
            "rom_sha256": sha256(output),
            "sha256": sha256(output),
            "size": len(output),
            "sav": advance_relative(args.out_sav),
            "sav_sha256": sha256(args.out_sav.read_bytes()),
            "preview": advance_relative(preview_path),
            "changed_bytes": len(changed),
            "changed_ranges": changed_ranges(changed),
        },
        "verification": {
            "result": "PASS",
            "py_compile": "PASS",
            "original_CD9250_byte_exact": True,
            "right_round_cap_preserved": True,
            "anim2_not_used_as_donor": True,
        },
    }
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "rom": advance_relative(args.out),
        "rom_sha256": sha256(output),
        "sav": advance_relative(args.out_sav),
        "preview": advance_relative(preview_path),
        "changed_bytes": len(changed),
        "private_tiles": len(private),
        "lines": [spec["lines"] for spec in TARGETS],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
