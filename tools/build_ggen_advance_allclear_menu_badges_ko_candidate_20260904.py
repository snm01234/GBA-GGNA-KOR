#!/usr/bin/env python3
"""Build Korean title/submenu badge graphics from the all-clear state analysis.

Only source tiles used by the six requested labels in sprite resource
0x08CCFE40 are changed in place.  Resource headers, animation/source lookup
records, palettes, pointer consumers, and every non-target animation must remain
byte-/pixel-exact.
"""
from __future__ import annotations

import binascii
import hashlib
import json
import struct
import sys
from collections import Counter
from pathlib import Path
from typing import Any
from zipfile import ZipFile

from PIL import Image, ImageDraw

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_settings_suspend_ui as sprite
import test_ggen_advance_font_pair as fontpair
from ggen_advance_project_paths import ADVANCE_ROOT, FONT_ZIP, MAIN_TIP_MANIFEST, MAIN_TIP_ROM, advance_relative

ROM_BASE = 0x08000000
RESOURCE = 0x08CCFE40
ANALYSIS = ADVANCE_ROOT / "analysis" / "ggen_advance_allclear_menu_badges_20260904.json"
OUT_DIR = ADVANCE_ROOT / "outputs" / "20260904_ggen_advance_allclear_menu_badges"
OUT_ROM = OUT_DIR / "ggen_advance_allclear_menu_badges_ko_candidate_20260904.gba"
OUT_PREVIEW = OUT_DIR / "ggen_advance_allclear_menu_badges_ko_preview_20260904.png"
OUT_MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_allclear_menu_badges_ko_candidate_20260904.json"
FONT_MEMBER = "Galmuri11.bdf"

# Canonical animation IDs for each distinct source-tile label.
TARGETS = {
    "はじめから": {"ko": "처음부터", "animation": 0, "family": [0, 9]},
    "つづきから": {"ko": "이어하기", "animation": 1, "family": [1, 10]},
    "おまけ": {"ko": "부록", "animation": 2, "family": [2, 11]},
    "ロード": {"ko": "로드", "animation": 5, "family": [5, 14]},
    "コンティニュー": {"ko": "컨티뉴", "animation": 21, "family": [21]},
    "プロフィール": {"ko": "프로필", "animation": 7, "family": [7, 16]},
}
TARGET_ANIMATIONS = {anim for spec in TARGETS.values() for anim in spec["family"]}
# The resource has two chrome families.  Animations 18..21 use a visibly
# different edge/background raster, so they must not donate pixels to 0..17.
DONOR_FAMILY_A = [0, 1, 2, 3, 4, 5, 6, 7, 8, 22, 23]
DONOR_FAMILY_B = [18, 19, 20, 21]


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def decode_tile(raw: bytes) -> list[list[int]]:
    gate(len(raw) == 32, "4bpp tile length drift")
    return [
        [((raw[y * 4 + x // 2] >> (4 * (x & 1))) & 0xF) for x in range(8)]
        for y in range(8)
    ]


def encode_tile(pixels: list[list[int]]) -> bytes:
    gate(len(pixels) == 8 and all(len(row) == 8 for row in pixels), "4bpp tile shape drift")
    out = bytearray(32)
    for y in range(8):
        for x in range(8):
            value = pixels[y][x] & 0xF
            pos = y * 4 + x // 2
            if x & 1:
                out[pos] |= value << 4
            else:
                out[pos] |= value
    return bytes(out)


def animation_info(records: list[tuple[int, bytes]], index: int) -> dict[str, Any]:
    blob = b"".join(record for _off, record in records[index:])
    marker = blob.find(b"\x40\x00\x40\x00")
    gate(marker >= 0, f"animation {index} marker missing")
    parsed = sprite.parse_animation_oam(blob[marker:])
    total = sum(int(obj["tile_count"]) for obj in parsed["objects"])
    source_start = marker + int(parsed["entries_end"])
    source_end = source_start + total * 2
    gate(source_end <= len(blob), f"animation {index} source table truncated")
    ids = list(struct.unpack_from(f"<{total}H", blob, source_start))
    by_object: list[list[int]] = []
    cursor = 0
    positions: list[tuple[int, int, int]] = []
    for obj in parsed["objects"]:
        count = int(obj["tile_count"])
        source_ids = ids[cursor:cursor + count]
        by_object.append(source_ids)
        wt = int(obj["size_px"][0]) // 8
        ht = int(obj["size_px"][1]) // 8
        for ty in range(ht):
            for tx in range(wt):
                positions.append((source_ids[ty * wt + tx], int(obj["x"]) + 40 + tx * 8, int(obj["y"]) + 8 + ty * 8))
        cursor += count
    gate(cursor == total, f"animation {index} source count drift")
    gate(len(positions) == 20, f"animation {index} expected 20 source tiles")
    return {
        "objects": parsed["objects"],
        "source_ids": ids,
        "source_by_object": by_object,
        "positions": positions,
    }


def canvas_for(graphics: bytes | bytearray, anim: dict[str, Any]) -> list[list[int]]:
    canvas = [[0] * 80 for _ in range(16)]
    for source_id, ox, oy in anim["positions"]:
        raw = bytes(graphics[source_id * 32:(source_id + 1) * 32])
        tile = decode_tile(raw)
        for y in range(8):
            canvas[oy + y][ox:ox + 8] = tile[y]
    return canvas


def japanese_mask(canvas: list[list[int]]) -> set[tuple[int, int]]:
    """Native glyph face/shade (E/B) plus adjacent one-pixel dark contour (1)."""
    base = {
        (x, y)
        for y in range(2, 14)
        for x in range(4, 76)
        if canvas[y][x] in (0xB, 0xE)
    }
    gate(base, "Japanese face/shade mask is empty")
    contour = {
        (nx, ny)
        for x, y in base
        for dy in (-1, 0, 1)
        for dx in (-1, 0, 1)
        if not (dx == 0 and dy == 0)
        for nx, ny in ((x + dx, y + dy),)
        if 0 <= nx < 80 and 0 <= ny < 16 and canvas[ny][nx] == 0x1
    }
    return base | contour


def fallback_background(canvas: list[list[int]], mask: set[tuple[int, int]], x: int, y: int) -> int:
    for radius in range(1, 13):
        samples = []
        for nx in range(max(0, x - radius), min(80, x + radius + 1)):
            for ny in (y - radius, y + radius):
                if 0 <= ny < 16 and (nx, ny) not in mask and canvas[ny][nx] not in (0xB, 0xE):
                    samples.append(canvas[ny][nx])
        for ny in range(max(0, y - radius + 1), min(16, y + radius)):
            for nx in (x - radius, x + radius):
                if 0 <= nx < 80 and (nx, ny) not in mask and canvas[ny][nx] not in (0xB, 0xE):
                    samples.append(canvas[ny][nx])
        if samples:
            return Counter(samples).most_common(1)[0][0]
    return 0x1


def clean_japanese(
    source: list[list[int]],
    donors: list[list[list[int]]],
) -> tuple[list[list[int]], dict[str, Any]]:
    mask = japanese_mask(source)
    donor_masks = [japanese_mask(canvas) for canvas in donors]
    cleaned = [row[:] for row in source]
    donor_restored = 0
    fallback_restored = 0
    for x, y in sorted(mask, key=lambda point: (point[1], point[0])):
        candidates = [
            canvas[y][x]
            for canvas, other_mask in zip(donors, donor_masks)
            if (x, y) not in other_mask and canvas[y][x] not in (0xB, 0xE)
        ]
        if candidates:
            cleaned[y][x] = Counter(candidates).most_common(1)[0][0]
            donor_restored += 1
        else:
            cleaned[y][x] = fallback_background(source, mask, x, y)
            fallback_restored += 1
    # All native B/E face/shade pixels inside the exact cleared mask must be gone.
    residue = sum(1 for x, y in mask if cleaned[y][x] in (0xB, 0xE))
    gate(residue == 0, f"Japanese face/shade residue after cleanup: {residue}")
    return cleaned, {
        "cleared_pixels": len(mask),
        "donor_restored": donor_restored,
        "fallback_restored": fallback_restored,
        "native_face_shade_residue": residue,
        "mask_bbox": [min(x for x, _y in mask), min(y for _x, y in mask), max(x for x, _y in mask) + 1, max(y for _x, y in mask) + 1],
    }


def render_korean(text: str, font: fontpair.BdfFont) -> tuple[set[tuple[int, int]], int, int]:
    cell_w, cell_h = 12, 12
    width = len(text) * cell_w
    x0 = (80 - width) // 2
    y0 = 2
    ink: set[tuple[int, int]] = set()
    for index, char in enumerate(text):
        glyph = font.render(char, cell_w, cell_h)
        for y in range(cell_h):
            for x in range(cell_w):
                if glyph.getpixel((x, y)):
                    ink.add((x0 + index * cell_w + x, y0 + y))
    gate(ink and all(4 <= x < 76 and 1 <= y < 15 for x, y in ink), f"{text}: Korean glyph overflow")
    return ink, x0, width


def paint_korean(cleaned: list[list[int]], text: str, font: fontpair.BdfFont) -> tuple[list[list[int]], dict[str, Any]]:
    ink, x0, width = render_korean(text, font)
    outline = {
        (x + dx, y + dy)
        for x, y in ink
        for dy in (-1, 0, 1)
        for dx in (-1, 0, 1)
        if not (dx == 0 and dy == 0)
        if 0 <= x + dx < 80 and 0 <= y + dy < 16
    } - ink
    out = [row[:] for row in cleaned]
    for x, y in outline:
        out[y][x] = 0x1
    for x, y in ink:
        out[y][x] = 0xE
    return out, {
        "font": FONT_MEMBER,
        "cell": [12, 12],
        "text_width": width,
        "origin": [x0, 2],
        "ink_index": 14,
        "outline_index": 1,
        "ink_pixels": len(ink),
        "outline_pixels": len(outline),
    }


def palette_rgb(raw: bytes) -> list[tuple[int, int, int]]:
    colors = []
    for index in range(16):
        value = struct.unpack_from("<H", raw, index * 2)[0]
        colors.append(((value & 31) * 255 // 31, ((value >> 5) & 31) * 255 // 31, ((value >> 10) & 31) * 255 // 31))
    return colors


def canvas_image(canvas: list[list[int]], palette: bytes, scale: int = 4) -> Image.Image:
    colors = palette_rgb(palette)
    image = Image.new("RGB", (80, 16))
    image.putdata([colors[value] for row in canvas for value in row])
    return image.resize((80 * scale, 16 * scale), Image.Resampling.NEAREST)


def main() -> int:
    report = json.loads(ANALYSIS.read_text(encoding="utf-8"))
    gate(report.get("result") == "PASS", "allclear analysis is not PASS")
    parent = MAIN_TIP_ROM.read_bytes()
    main_manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(parent) == main_manifest["sha256"], "parent is not current main TIP")
    gate(report["current_main_tip"]["sha256"] == sha256(parent), "analysis was not run against current main TIP")

    resource_off = RESOURCE - ROM_BASE
    kind, palette_count, graphics_rel, palette_rel, animation_count = struct.unpack_from("<5I", parent, resource_off)
    gate((kind, palette_count, graphics_rel, palette_rel, animation_count) == (0, 6, 0x0DE4, 0x2BE4, 26), "resource layout drift")
    original_resource = parent[resource_off:resource_off + palette_rel + palette_count * 32]
    original_graphics = parent[resource_off + graphics_rel:resource_off + palette_rel]
    palettes = parent[resource_off + palette_rel:resource_off + palette_rel + palette_count * 32]
    gate(len(original_graphics) == 240 * 32, "source tile count drift")

    _gr, records = sprite.animation_records(parent, RESOURCE)
    animations = {index: animation_info(records, index) for index in range(animation_count)}
    before_canvases = {index: canvas_for(original_graphics, animations[index]) for index in range(animation_count)}

    with ZipFile(FONT_ZIP) as archive:
        font = fontpair.load_bdf(archive, FONT_MEMBER)

    desired: dict[str, list[list[int]]] = {}
    label_reports: dict[str, Any] = {}
    for jp, spec in TARGETS.items():
        anim = int(spec["animation"])
        donor_indices = DONOR_FAMILY_B if anim >= 18 else DONOR_FAMILY_A
        donors = [before_canvases[index] for index in donor_indices if index != anim]
        cleaned, cleanup_meta = clean_japanese(before_canvases[anim], donors)
        painted, paint_meta = paint_korean(cleaned, str(spec["ko"]), font)
        desired[jp] = painted
        label_reports[jp] = {
            "translation": spec["ko"],
            "animation_family": spec["family"],
            "source_ids": animations[anim]["source_ids"],
            "cleanup": cleanup_meta,
            "paint": paint_meta,
        }

    # Convert desired canvases into source-tile updates.  Shared chrome tiles
    # must either remain original or agree byte-exact across all target labels.
    updates: dict[int, bytes] = {}
    update_owners: dict[int, list[str]] = {}
    source_users: dict[int, set[int]] = {tile: set() for tile in range(240)}
    for anim_index, anim in animations.items():
        for source_id in anim["source_ids"]:
            source_users[source_id].add(anim_index)

    for jp, spec in TARGETS.items():
        anim_index = int(spec["animation"])
        canvas = desired[jp]
        for source_id, ox, oy in animations[anim_index]["positions"]:
            payload = encode_tile([canvas[oy + y][ox:ox + 8] for y in range(8)])
            original = original_graphics[source_id * 32:(source_id + 1) * 32]
            if payload == original:
                continue
            non_target_users = source_users[source_id] - TARGET_ANIMATIONS
            gate(not non_target_users, f"{jp}: source tile {source_id} would alter non-target animations {sorted(non_target_users)}")
            if source_id in updates:
                gate(updates[source_id] == payload, f"source tile {source_id} has conflicting Korean target payloads")
            else:
                updates[source_id] = payload
            update_owners.setdefault(source_id, []).append(jp)

    gate(updates, "no source tiles changed")
    patched_graphics = bytearray(original_graphics)
    for source_id, payload in updates.items():
        patched_graphics[source_id * 32:(source_id + 1) * 32] = payload

    after_canvases = {index: canvas_for(patched_graphics, animations[index]) for index in range(animation_count)}
    changed_non_target = [
        index for index in range(animation_count)
        if index not in TARGET_ANIMATIONS and after_canvases[index] != before_canvases[index]
    ]
    gate(not changed_non_target, f"non-target animations changed: {changed_non_target}")
    # Duplicate members of each target family must render identically after the patch.
    for spec in TARGETS.values():
        family = [int(value) for value in spec["family"]]
        for index in family[1:]:
            gate(after_canvases[index] == after_canvases[family[0]], f"target duplicate animation drift {family[0]}/{index}")

    candidate = bytearray(parent)
    candidate[resource_off + graphics_rel:resource_off + palette_rel] = patched_graphics
    out = bytes(candidate)
    # Everything outside the graphics payload must remain byte-exact.
    start = resource_off + graphics_rel
    end = resource_off + palette_rel
    changed_offsets = [i for i, (left, right) in enumerate(zip(parent, out)) if left != right]
    gate(changed_offsets and all(start <= offset < end for offset in changed_offsets), "change escaped resource graphics payload")
    gate(out[resource_off:resource_off + graphics_rel] == parent[resource_off:resource_off + graphics_rel], "resource header/animation records changed")
    gate(out[end:resource_off + palette_rel + palette_count * 32] == parent[end:resource_off + palette_rel + palette_count * 32], "resource palettes changed")

    # Preview: native grayscale NORMAL, then blue FOCUS for the Korean result.
    scale = 4
    row_h = 16 * scale
    sheet = Image.new("RGB", (80 * scale * 3 + 32, len(TARGETS) * (row_h + 26) + 34), (20, 20, 20))
    draw = ImageDraw.Draw(sheet)
    draw.text((8, 8), "all-clear menu badges: JP before / KO normal / KO focus", fill=(255, 255, 255))
    y = 30
    preview_rows = []
    normal_palette = palettes[0:32]
    focus_palette = palettes[32:64]
    for jp, spec in TARGETS.items():
        anim = int(spec["animation"])
        before = canvas_image(before_canvases[anim], normal_palette, scale)
        after_normal = canvas_image(after_canvases[anim], normal_palette, scale)
        after_focus = canvas_image(after_canvases[anim], focus_palette, scale)
        sheet.paste(before, (0, y))
        sheet.paste(after_normal, (80 * scale + 16, y))
        sheet.paste(after_focus, (160 * scale + 32, y))
        draw.text((4, y + row_h + 3), f"{jp} -> {spec['ko']}", fill=(235, 235, 235))
        preview_rows.append({"source": jp, "translation": spec["ko"], "animation": anim})
        y += row_h + 26

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_ROM.write_bytes(out)
    sheet.save(OUT_PREVIEW)

    manifest = {
        "schema_version": 1,
        "kind": "ggen_advance_allclear_menu_badges_ko_candidate_20260904",
        "result": "PASS",
        "base": {
            "path": advance_relative(MAIN_TIP_ROM),
            "sha256": sha256(parent),
            "crc32": f"0x{binascii.crc32(parent) & 0xFFFFFFFF:08X}",
        },
        "output": {
            "path": advance_relative(OUT_ROM),
            "sha256": sha256(out),
            "crc32": f"0x{binascii.crc32(out) & 0xFFFFFFFF:08X}",
            "bytes": len(out),
        },
        "preview": advance_relative(OUT_PREVIEW),
        "analysis": advance_relative(ANALYSIS),
        "resource": {
            "address": f"0x{RESOURCE:08X}",
            "graphics_span": [f"0x{start:08X}", f"0x{end:08X}"],
            "font": FONT_MEMBER,
            "header_animation_records_unchanged": True,
            "palettes_unchanged": True,
            "non_target_animations_unchanged": True,
            "non_target_live_ss3_animation_8_unchanged": after_canvases[8] == before_canvases[8],
        },
        "labels": label_reports,
        "source_tile_updates": {
            "count": len(updates),
            "ids": sorted(updates),
            "owners": {str(tile): owners for tile, owners in sorted(update_owners.items())},
        },
        "diff": {
            "changed_byte_count": len(changed_offsets),
            "first_changed": f"0x{min(changed_offsets):08X}",
            "last_changed_exclusive": f"0x{max(changed_offsets) + 1:08X}",
            "all_changes_within_resource_graphics": True,
        },
        "verification": {
            "result": "PASS",
            "target_animation_families_updated": sorted(TARGET_ANIMATIONS),
            "changed_non_target_animations": changed_non_target,
            "preview_rows": preview_rows,
        },
    }
    OUT_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "rom": advance_relative(OUT_ROM),
        "preview": advance_relative(OUT_PREVIEW),
        "manifest": advance_relative(OUT_MANIFEST),
        "sha256": manifest["output"]["sha256"],
        "crc32": manifest["output"]["crc32"],
        "source_tiles_changed": len(updates),
        "changed_bytes": len(changed_offsets),
        "non_target_animations_unchanged": True,
        "ss3_animation_8_unchanged": manifest["resource"]["non_target_live_ss3_animation_8_unchanged"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
