#!/usr/bin/env python3
"""Build clean-plate Korean all-clear menu badges, including disabled variants.

Unlike the first candidate, this builder does not erase only detected Japanese
pixels.  It first reconstructs a Japanese-free 80x16 badge background plate for
the native active/focus family, derives the native disabled plate from the
proven palette-index remap, replaces the complete text well with that clean
plate, and only then paints Galmuri11 Korean glyphs.

Disabled つづきから / おまけ are animations 18 / 19, proven by the follow-up
savestate.  Resource headers, animation/source lookup records, palettes and all
unrelated animation outputs remain byte-/pixel-exact.
"""
from __future__ import annotations

import binascii
import hashlib
import json
import shutil
import statistics
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from zipfile import ZipFile

from PIL import Image, ImageDraw

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_settings_suspend_ui as sprite
import build_ggen_advance_allclear_menu_badges_ko_candidate_20260904 as old
import test_ggen_advance_font_pair as fontpair
from ggen_advance_project_paths import ADVANCE_ROOT, FONT_ZIP, MAIN_TIP_MANIFEST, MAIN_TIP_ROM, advance_relative

ROM_BASE = 0x08000000
RESOURCE = 0x08CCFE40
FOLLOWUP_ANALYSIS = ADVANCE_ROOT / "analysis" / "ggen_advance_allclear_menu_badges_followup_20260904.json"
OUT_DIR = ADVANCE_ROOT / "outputs" / "20260904_ggen_advance_allclear_menu_badges"
OUT_ROM = OUT_DIR / "ggen_advance_allclear_menu_badges_ko_followup_candidate_20260904.gba"
OUT_SAV = OUT_DIR / "ggen_advance_allclear_menu_badges_ko_followup_candidate_20260904.sav"
OUT_PREVIEW = OUT_DIR / "ggen_advance_allclear_menu_badges_ko_followup_preview_20260904.png"
OUT_MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_allclear_menu_badges_ko_followup_candidate_20260904.json"
SOURCE_SAV = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean)_allclear.sav"
FONT_MEMBER = "Galmuri11.bdf"

TEXT_WELL = (7, 1, 76, 14)  # x0,y0,x1,y1; preserve native chrome outside this field.
ACTIVE_PLATE_ANIMS = list(range(0, 9))
ACTIVE_BACKGROUND_INDICES = set(range(2, 11)) | {0}
GLYPH_ONLY_ACTIVE = {1, 11, 12, 13, 14, 15}
DISABLED_REMAP = {0: 0, 2: 2, 3: 2, 4: 3, 5: 4, 6: 4, 7: 5, 8: 5, 9: 6, 10: 7}

# (source JP, KO, canonical animation, duplicate family, plate style, face index)
VARIANTS = [
    ("はじめから", "처음부터", 0, [0, 9], "active", 14),
    ("つづきから", "이어하기", 1, [1, 10], "active", 14),
    ("おまけ", "부록", 2, [2, 11], "active", 14),
    ("ロード", "로드", 5, [5, 14], "active", 14),
    ("プロフィール", "프로필", 7, [7, 16], "active", 14),
    # animation 21 belongs to the dim/disabled raster family.
    ("コンティニュー", "컨티뉴", 21, [21], "disabled", 4),
    # Follow-up ss1 proves these two disabled title-menu variants.
    ("つづきから[disabled]", "이어하기", 18, [18], "disabled", 4),
    ("おまけ[disabled]", "부록", 19, [19], "disabled", 4),
]
TARGET_ANIMS = {a for _jp, _ko, _canon, fam, _style, _face in VARIANTS for a in fam}


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def pick_mode(values: list[int]) -> tuple[int, int]:
    counts = Counter(values)
    best = max(counts.values())
    tied = sorted(v for v, n in counts.items() if n == best)
    med = statistics.median(values)
    return min(tied, key=lambda v: (abs(v - med), v)), best


def build_active_clean_plate(canvases: list[list[list[int]]]) -> tuple[list[list[int]], dict[str, Any]]:
    gate(len(canvases) >= 7, "not enough active badge samples")
    x0, y0, x1, y1 = TEXT_WELL
    plate = [row[:] for row in canvases[0]]
    support = [[99] * 80 for _ in range(16)]
    missing: set[tuple[int, int]] = set()

    for y in range(y0, y1):
        for x in range(x0, x1):
            values = [canvas[y][x] for canvas in canvases if canvas[y][x] in ACTIVE_BACKGROUND_INDICES]
            if values:
                value, count = pick_mode(values)
                plate[y][x] = value
                support[y][x] = count
            else:
                missing.add((x, y))
                support[y][x] = 0

    # Fill coordinates where every sample is covered by Japanese ink/shadow.
    # Use only already-clean background neighbors; iterate until the well is full.
    iterations = 0
    while missing:
        iterations += 1
        gate(iterations <= 20, f"clean-plate fill stalled with {len(missing)} pixels")
        updates: list[tuple[int, int, int]] = []
        for x, y in sorted(missing, key=lambda p: (p[1], p[0])):
            neighbors = []
            for radius in (1, 2, 3):
                for ny in range(max(y0, y - radius), min(y1, y + radius + 1)):
                    for nx in range(max(x0, x - radius), min(x1, x + radius + 1)):
                        if (nx, ny) in missing or (nx == x and ny == y):
                            continue
                        value = plate[ny][nx]
                        if value in ACTIVE_BACKGROUND_INDICES:
                            neighbors.append(value)
                if neighbors:
                    break
            if neighbors:
                value, _ = pick_mode(neighbors)
                updates.append((x, y, value))
        gate(updates, "clean-plate missing pixels have no background neighbors")
        for x, y, value in updates:
            plate[y][x] = value
            support[y][x] = 0
            missing.remove((x, y))

    # Weakly-supported single-label pixels are the main way Japanese color can
    # leak through the consensus.  Replace only those weak points with the
    # median/mode of nearby stronger clean-plate pixels.  Strong native chrome
    # samples stay untouched.
    smoothed = 0
    for _pass in range(2):
        replacements: list[tuple[int, int, int]] = []
        for y in range(y0 + 1, y1 - 1):
            for x in range(x0 + 1, x1 - 1):
                if support[y][x] >= 2:
                    continue
                neighbors = [
                    plate[ny][nx]
                    for ny in range(y - 1, y + 2)
                    for nx in range(x - 1, x + 2)
                    if not (nx == x and ny == y)
                    and plate[ny][nx] in ACTIVE_BACKGROUND_INDICES
                    and support[ny][nx] >= 2
                ]
                if len(neighbors) < 3:
                    continue
                value, _ = pick_mode(neighbors)
                if value != plate[y][x]:
                    replacements.append((x, y, value))
        for x, y, value in replacements:
            plate[y][x] = value
            support[y][x] = 2
            smoothed += 1

    residue = [(x, y, plate[y][x]) for y in range(y0, y1) for x in range(x0, x1) if plate[y][x] in GLYPH_ONLY_ACTIVE]
    gate(not residue, f"active clean plate retains glyph-only indices: {residue[:8]}")
    return plate, {
        "text_well": list(TEXT_WELL),
        "samples": len(canvases),
        "background_indices": sorted(ACTIVE_BACKGROUND_INDICES),
        "initial_missing_pixels": sum(1 for y in range(y0, y1) for x in range(x0, x1) if support[y][x] == 0),
        "fill_iterations": iterations,
        "weak_pixels_smoothed": smoothed,
        "glyph_only_residue": 0,
    }


def build_disabled_clean_plate(active_plate: list[list[int]]) -> list[list[int]]:
    x0, y0, x1, y1 = TEXT_WELL
    plate = [row[:] for row in active_plate]
    for y in range(y0, y1):
        for x in range(x0, x1):
            value = active_plate[y][x]
            gate(value in DISABLED_REMAP, f"no disabled remap for clean active index {value} at {x},{y}")
            plate[y][x] = DISABLED_REMAP[value]
    return plate


def remap_evidence(canvases: dict[int, list[list[int]]]) -> dict[str, Any]:
    counts: dict[int, Counter[int]] = defaultdict(Counter)
    for normal, disabled in ((1, 18), (2, 19)):
        left, right = canvases[normal], canvases[disabled]
        for y in range(16):
            for x in range(80):
                value = left[y][x]
                if value in ACTIVE_BACKGROUND_INDICES:
                    counts[value][right[y][x]] += 1
    rows = {}
    for value, mapped in sorted(DISABLED_REMAP.items()):
        c = counts[value]
        if not c:
            rows[str(value)] = {"mapped": mapped, "samples": 0, "matching": 0}
            continue
        rows[str(value)] = {"mapped": mapped, "samples": sum(c.values()), "matching": c[mapped], "top": c.most_common(4)}
    return rows


def apply_plate(source: list[list[int]], plate: list[list[int]]) -> list[list[int]]:
    x0, y0, x1, y1 = TEXT_WELL
    clean = [row[:] for row in source]
    for y in range(y0, y1):
        clean[y][x0:x1] = plate[y][x0:x1]
    return clean


def render_korean(clean: list[list[int]], text: str, font: fontpair.BdfFont, face: int) -> tuple[list[list[int]], dict[str, Any]]:
    ink, x0, width = old.render_korean(text, font)
    outline = {
        (x + dx, y + dy)
        for x, y in ink
        for dy in (-1, 0, 1)
        for dx in (-1, 0, 1)
        if not (dx == 0 and dy == 0)
        if 0 <= x + dx < 80 and 0 <= y + dy < 16
    } - ink
    out = [row[:] for row in clean]
    for x, y in outline:
        out[y][x] = 1
    for x, y in ink:
        out[y][x] = face
    return out, {"font": FONT_MEMBER, "face_index": face, "outline_index": 1, "origin": [x0, 2], "text_width": width, "ink_pixels": len(ink), "outline_pixels": len(outline)}


def palette_rgb(raw: bytes) -> list[tuple[int, int, int]]:
    colors = []
    for i in range(16):
        value = struct.unpack_from("<H", raw, i * 2)[0]
        colors.append(((value & 31) * 255 // 31, ((value >> 5) & 31) * 255 // 31, ((value >> 10) & 31) * 255 // 31))
    return colors


def image_for(canvas: list[list[int]], palette: bytes, scale: int = 4) -> Image.Image:
    colors = palette_rgb(palette)
    image = Image.new("RGB", (80, 16))
    image.putdata([colors[v] for row in canvas for v in row])
    return image.resize((80 * scale, 16 * scale), Image.Resampling.NEAREST)


def main() -> int:
    analysis = json.loads(FOLLOWUP_ANALYSIS.read_text(encoding="utf-8"))
    gate(analysis.get("result") == "PASS", "follow-up analysis is not PASS")
    parent = MAIN_TIP_ROM.read_bytes()
    manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(parent) == manifest["sha256"], "parent main TIP/manifest mismatch")
    gate(analysis["current_main_tip"]["sha256"] == sha256(parent), "follow-up analysis parent drift")

    off = RESOURCE - ROM_BASE
    kind, pal_count, grel, prel, anim_count = struct.unpack_from("<5I", parent, off)
    gate((kind, pal_count, grel, prel, anim_count) == (0, 6, 0x0DE4, 0x2BE4, 26), "resource layout drift")
    original_graphics = parent[off + grel:off + prel]
    palettes = parent[off + prel:off + prel + pal_count * 32]
    gate(len(original_graphics) == 240 * 32, "graphics tile count drift")

    _gr, records = sprite.animation_records(parent, RESOURCE)
    anim = {i: old.animation_info(records, i) for i in range(anim_count)}
    before = {i: old.canvas_for(original_graphics, anim[i]) for i in range(anim_count)}
    active_plate, active_plate_meta = build_active_clean_plate([before[i] for i in ACTIVE_PLATE_ANIMS])
    disabled_plate = build_disabled_clean_plate(active_plate)
    remap_meta = remap_evidence(before)

    with ZipFile(FONT_ZIP) as archive:
        font = fontpair.load_bdf(archive, FONT_MEMBER)

    desired: dict[int, list[list[int]]] = {}
    clean_before_paint: dict[int, list[list[int]]] = {}
    korean_pixels: dict[int, set[tuple[int, int]]] = {}
    variant_reports = []
    for jp, ko, canonical, family, style, face in VARIANTS:
        plate = active_plate if style == "active" else disabled_plate
        clean = apply_plate(before[canonical], plate)
        painted, paint = render_korean(clean, ko, font, face)
        desired[canonical] = painted
        clean_before_paint[canonical] = clean
        korean_pixels[canonical] = {
            (x, y)
            for y in range(16)
            for x in range(80)
            if painted[y][x] != clean[y][x]
        }
        variant_reports.append({"source": jp, "translation": ko, "canonical_animation": canonical, "animation_family": family, "style": style, "clean_plate": "active" if style == "active" else "disabled", "paint": paint})

    source_users: dict[int, set[int]] = {tile: set() for tile in range(240)}
    for index, info in anim.items():
        for sid in info["source_ids"]:
            source_users[int(sid)].add(index)

    updates: dict[int, bytes] = {}
    owners: dict[int, list[str]] = defaultdict(list)
    skipped_shared: dict[int, list[int]] = {}
    for report in variant_reports:
        canonical = int(report["canonical_animation"])
        canvas = desired[canonical]
        for sid, ox, oy in anim[canonical]["positions"]:
            sid = int(sid)
            payload = old.encode_tile([canvas[oy + y][ox:ox + 8] for y in range(8)])
            original = original_graphics[sid * 32:(sid + 1) * 32]
            if payload == original:
                continue
            non_target = source_users[sid] - TARGET_ANIMS
            if non_target:
                # Shared source tiles are common chrome/background fragments.
                # Do not rewrite them: that would change unrelated animations.
                # A shared tile is skippable only when no Korean ink/outline
                # touches its 8x8 destination rectangle.
                touches_korean = any(
                    ox <= x < ox + 8 and oy <= y < oy + 8
                    for x, y in korean_pixels[canonical]
                )
                gate(not touches_korean, f"shared source tile {sid} carries Korean pixels for animation {canonical}")
                skipped_shared[sid] = sorted(non_target)
                continue
            if sid in updates:
                gate(updates[sid] == payload, f"conflicting clean/Korean payload for source tile {sid}")
            updates[sid] = payload
            owners[sid].append(str(report["source"]))

    gate(updates, "no graphics updates generated")
    patched = bytearray(original_graphics)
    for sid, payload in updates.items():
        patched[sid * 32:(sid + 1) * 32] = payload

    after = {i: old.canvas_for(patched, anim[i]) for i in range(anim_count)}
    # Canonical/duplicate outputs may differ from the ideal clean plate only in
    # skipped shared chrome tiles.  Korean glyph pixels themselves must match
    # the desired raster exactly.
    for _jp, _ko, canonical, family, _style, _face in VARIANTS:
        allowed_shared_coords: set[tuple[int, int]] = set()
        for sid, ox, oy in anim[canonical]["positions"]:
            if int(sid) in skipped_shared:
                allowed_shared_coords.update((x, y) for y in range(oy, oy + 8) for x in range(ox, ox + 8))
        for member in family:
            diffs = {
                (x, y)
                for y in range(16)
                for x in range(80)
                if after[member][y][x] != desired[canonical][y][x]
            }
            gate(diffs <= allowed_shared_coords, f"animation {member} differs from desired outside shared chrome: {sorted(diffs - allowed_shared_coords)[:8]}")
            gate(not (diffs & korean_pixels[canonical]), f"animation {member} lost Korean glyph pixels")

    changed_non_target = [i for i in range(anim_count) if i not in TARGET_ANIMS and after[i] != before[i]]
    gate(not changed_non_target, f"non-target animations changed: {changed_non_target}")
    gate(after[8] == before[8], "ss3 non-target animation 8 changed")
    gate(after[20] == before[20], "disabled sibling animation 20 changed")

    candidate = bytearray(parent)
    candidate[off + grel:off + prel] = patched
    out = bytes(candidate)
    changed_offsets = [i for i, (a, b) in enumerate(zip(parent, out)) if a != b]
    start, end = off + grel, off + prel
    gate(changed_offsets and all(start <= x < end for x in changed_offsets), "change escaped resource graphics")
    gate(out[off:off + grel] == parent[off:off + grel], "resource header/animation records changed")
    gate(out[off + prel:off + prel + pal_count * 32] == parent[off + prel:off + prel + pal_count * 32], "palettes changed")

    # Preview clean plates and representative active/disabled Korean badges.
    scale = 4
    rows = [
        ("ACTIVE CLEAN PLATE", active_plate, 0),
        ("DISABLED CLEAN PLATE", disabled_plate, 0),
        ("처음부터 active", desired[0], 0),
        ("이어하기 active", desired[1], 0),
        ("이어하기 disabled", desired[18], 0),
        ("부록 active", desired[2], 0),
        ("부록 disabled", desired[19], 0),
        ("로드 focus palette", desired[5], 1),
        ("컨티뉴 dim", desired[21], 0),
        ("프로필", desired[7], 0),
    ]
    row_h = 16 * scale
    sheet = Image.new("RGB", (80 * scale + 260, len(rows) * (row_h + 8) + 30), (18, 18, 18))
    draw = ImageDraw.Draw(sheet)
    draw.text((8, 8), "all-clear badge clean-plate follow-up", fill=(255, 255, 255))
    y = 28
    for label, canvas, pal in rows:
        sheet.paste(image_for(canvas, palettes[pal * 32:(pal + 1) * 32], scale), (0, y))
        draw.text((80 * scale + 10, y + 20), label, fill=(235, 235, 235))
        y += row_h + 8

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_ROM.write_bytes(out)
    sheet.save(OUT_PREVIEW)
    if SOURCE_SAV.is_file():
        shutil.copy2(SOURCE_SAV, OUT_SAV)

    manifest_out = {
        "schema_version": 1,
        "kind": "ggen_advance_allclear_menu_badges_ko_followup_candidate_20260904",
        "result": "PASS",
        "base": {"path": advance_relative(MAIN_TIP_ROM), "sha256": sha256(parent), "crc32": f"0x{binascii.crc32(parent) & 0xFFFFFFFF:08X}"},
        "output": {"path": advance_relative(OUT_ROM), "sha256": sha256(out), "crc32": f"0x{binascii.crc32(out) & 0xFFFFFFFF:08X}", "bytes": len(out), "sav": advance_relative(OUT_SAV) if OUT_SAV.exists() else None},
        "preview": advance_relative(OUT_PREVIEW),
        "analysis": advance_relative(FOLLOWUP_ANALYSIS),
        "resource": {"address": f"0x{RESOURCE:08X}", "font": FONT_MEMBER, "text_well": list(TEXT_WELL), "header_animation_records_unchanged": True, "palettes_unchanged": True},
        "clean_plate": {"policy": "replace the complete native text well with a Japanese-free reconstructed background before drawing any Korean glyph", "active": active_plate_meta, "disabled_index_remap": DISABLED_REMAP, "disabled_remap_evidence": remap_meta},
        "variants": variant_reports,
        "disabled_followup": {"つづきから": {"animation": 18, "translation": "이어하기"}, "おまけ": {"animation": 19, "translation": "부록"}},
        "source_tile_updates": {"count": len(updates), "ids": sorted(updates), "owners": {str(k): v for k, v in sorted(owners.items())}, "skipped_shared_chrome": {str(k): v for k, v in sorted(skipped_shared.items())}},
        "diff": {"changed_byte_count": len(changed_offsets), "all_changes_within_resource_graphics": True, "first_changed": f"0x{min(changed_offsets):08X}", "last_changed_exclusive": f"0x{max(changed_offsets)+1:08X}"},
        "verification": {"result": "PASS", "target_animations": sorted(TARGET_ANIMS), "changed_non_target_animations": changed_non_target, "ss3_animation_8_unchanged": True, "disabled_animation_20_unchanged": True, "clean_plate_first": True},
    }
    OUT_MANIFEST.write_text(json.dumps(manifest_out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "rom": advance_relative(OUT_ROM), "preview": advance_relative(OUT_PREVIEW), "manifest": advance_relative(OUT_MANIFEST), "sha256": manifest_out["output"]["sha256"], "crc32": manifest_out["output"]["crc32"], "source_tiles_changed": len(updates), "changed_bytes": len(changed_offsets), "disabled_18_19": True, "clean_plate_first": True}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
