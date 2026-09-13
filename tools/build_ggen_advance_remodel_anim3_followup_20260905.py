#!/usr/bin/env python3
"""Build the user-requested remodel anim3 follow-up on top of approved main TIP.

Scope is deliberately limited to sprite resource 0x092D8000 animation 3.

Requested changes:
* 運動 slot: correct the previously misapplied Korean 이동 -> 운동 while keeping
  the exact Galmuri11/cardinal-outline style used by the existing main TIP.
* 移動 slot: Koreanize to 이동 with the same Galmuri11 style while preserving the
  original Japanese left rounded cap byte/pixel-exact.
* 持 slot: Koreanize to 지 using Galmuri9; preserve the original left 4px round.
* 装甲 slot: restore only the original Japanese left 4px rounded chrome.
* 残り回数 slot: Koreanize to 남은횟수 with the existing Galmuri11 style while
  preserving the 13px left join/round and using the adjacent clean same-row
  panel body as the text-area background donor.

The active C43 direct graphics and E0518 atlas are outside this resource and are
therefore not touched.  Existing source tiles are never rewritten: changed
animation-3 cells are rebound to appended private tiles, preserving other
animations and any shared source tiles.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import struct
import sys
from pathlib import Path
from typing import Any
from zipfile import ZipFile

from PIL import Image, ImageDraw

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_develop_menu_buttons_images_20260901 as animutil
import build_ggen_advance_ss1_ss2_graphics_ko_test_20260902 as ss12
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

KO_RES = 0x092D8000
JP_RES = 0x08C64140
ALLOC_END = 0x012E0000
OUT_DIR = ADVANCE_ROOT / "outputs" / "20260905_ggen_advance_remodel_anim3_followup"
RESULT = OUT_DIR / "ggen_advance_remodel_anim3_followup_candidate_20260905.gba"
SAV = RESULT.with_suffix(".sav")
PREVIEW = OUT_DIR / "ggen_advance_remodel_anim3_followup_preview_20260905.png"
MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_remodel_anim3_followup_candidate_20260905.json"
MAIN_SAV = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).sav"

INK = 10
CONTOUR = 5
GLYPHISH = {4, 5, 10}

RECT_MOTION = (128, 24, 160, 40)
RECT_ARMOR = (156, 40, 188, 56)
RECT_MOVE = (56, 40, 88, 56)
RECT_HOLD = (56, 56, 72, 72)
RECT_REMAIN = (152, 56, 216, 72)


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def cut(canvas: list[list[int]], rect: tuple[int, int, int, int]) -> list[list[int]]:
    x0, y0, x1, y1 = rect
    return [row[x0:x1] for row in canvas[y0:y1]]


def changed_pixels(a: list[list[int]], b: list[list[int]]) -> int:
    return sum(x != y for ra, rb in zip(a, b) for x, y in zip(ra, rb))


def paint_text(
    canvas: list[list[int]],
    rect: tuple[int, int, int, int],
    text: str,
    font: fontpair.BdfFont,
    *,
    cell_width: int = 12,
) -> dict[str, Any]:
    x0, y0, x1, y1 = rect
    width, height = x1 - x0, y1 - y0
    gate(height == 16, f"{text}: paint height must be 16")
    local = [row[x0:x1] for row in canvas[y0:y1]]
    mask, text_width = ss12.paintops.make_text_mask(text, font, width, height, cell_width=cell_width)
    ink_pixels, contour_pixels = ss12.paintbase.paint_mask_cardinal(
        local, mask, ink=INK, contour=CONTOUR
    )
    gate(ink_pixels > 0 and contour_pixels > 0, f"{text}: empty raster")
    for y in range(height):
        canvas[y0 + y][x0:x1] = local[y]
    return {
        "text": text,
        "paint_rect": list(rect),
        "text_width_px": text_width,
        "ink_pixels": ink_pixels,
        "contour_pixels": contour_pixels,
    }


def paint_native_cardinal(
    canvas: list[list[int]],
    text: str,
    font: fontpair.BdfFont,
    origin_x: int,
    origin_y: int,
    clip: tuple[int, int, int, int],
) -> dict[str, Any]:
    ink, width, height = raster.native_ink(font, text)
    ink = {(origin_x + x, origin_y + y) for x, y in ink}
    x0, y0, x1, y1 = clip
    outline: set[tuple[int, int]] = set()
    for x, y in ink:
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            p = (x + dx, y + dy)
            if p not in ink:
                outline.add(p)
    for x, y in outline:
        if x0 <= x < x1 and y0 <= y < y1:
            canvas[y][x] = CONTOUR
    for x, y in ink:
        if x0 <= x < x1 and y0 <= y < y1:
            canvas[y][x] = INK
    return {
        "text": text,
        "paint_rect": list(clip),
        "origin": [origin_x, origin_y],
        "glyph_size": [width, height],
        "ink_pixels": len(ink),
        "contour_pixels": sum(1 for x, y in outline if x0 <= x < x1 and y0 <= y < y1),
    }


def main() -> int:
    parent = MAIN_TIP_ROM.read_bytes()
    jp = ORIGINAL_ROM.read_bytes()
    meta = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(parent) == meta["sha256"], "approved main TIP hash mismatch")
    gate(len(parent) == 32 * 1024 * 1024, "main TIP size drift")
    gate(MAIN_SAV.is_file(), "main SAV missing")

    before_canvas, before_pal, before_bank = ss12.resource_canvas(parent, KO_RES, 3)
    jp_canvas, jp_pal, jp_bank = ss12.resource_canvas(jp, JP_RES, 3)
    gate((len(before_canvas), len(before_canvas[0])) == (len(jp_canvas), len(jp_canvas[0])), "anim3 canvas size drift")
    gate(before_bank == jp_bank, "anim3 palette bank drift")

    # Baseline proof: these three requested labels are still byte/pixel-exact JP
    # before this follow-up, while the 運動 slot was already modified in main TIP.
    for label, rect in (("移動", RECT_MOVE), ("持", RECT_HOLD), ("残り回数", RECT_REMAIN)):
        gate(cut(before_canvas, rect) == cut(jp_canvas, rect), f"{label}: expected untouched JP baseline drift")
    gate(cut(before_canvas, RECT_MOTION) != cut(jp_canvas, RECT_MOTION), "運動: existing Korean slot unexpectedly equals JP")

    canvas = [row[:] for row in before_canvas]
    reports: list[dict[str, Any]] = []

    with ZipFile(FONT_ZIP) as archive:
        font11 = fontpair.load_bdf(archive, "Galmuri11.bdf")
        font9 = fontpair.load_bdf(archive, "Galmuri9.bdf")

    # 1) Existing main-TIP 運動 slot currently says 이동.  Reuse the exact donor
    # column and paint geometry from the historical approved ss2 pass, changing
    # only the Korean text to 운동.
    motion_before = cut(canvas, RECT_MOTION)
    for y in range(24, 40):
        donor = canvas[y][168]
        gate(donor in {6, 9, 10, 11}, f"운동 donor colour drift y={y}: {donor}")
        for x in range(130, 157):
            canvas[y][x] = donor
    motion_paint = paint_text(canvas, (130, 24, 156, 40), "운동", font11)
    reports.append({
        "label": "운동",
        "source": "運動",
        "operation": "correct existing 이동 -> 운동 using historical main-TIP donor/paint geometry",
        "rect": list(RECT_MOTION),
        "background_donor_column": 168,
        "font": "Galmuri11.bdf",
        **motion_paint,
        "changed_pixels": changed_pixels(motion_before, cut(canvas, RECT_MOTION)),
    })

    # 2) Restore only the left four pixels of the 装甲 plaque from the original
    # Japanese anim3.  The approved Korean 장갑 text/body remains untouched.
    armor_before = cut(canvas, RECT_ARMOR)
    for y in range(40, 56):
        for x in range(156, 160):
            canvas[y][x] = jp_canvas[y][x]
    armor_after = cut(canvas, RECT_ARMOR)
    gate(
        all(armor_after[y][x] == armor_before[y][x] for y in range(16) for x in range(4, 32)),
        "장갑: pixels outside left 4px changed",
    )
    gate(
        all(armor_after[y][x] == cut(jp_canvas, RECT_ARMOR)[y][x] for y in range(16) for x in range(4)),
        "장갑: left round is not JP-exact",
    )
    reports.append({
        "label": "장갑",
        "source": "装甲",
        "operation": "restore original JP left 4px rounded chrome only",
        "rect": list(RECT_ARMOR),
        "font": "existing main TIP unchanged",
        "changed_pixels": changed_pixels(armor_before, armor_after),
    })

    # 3) 移動 -> 이동.  Keep the original JP left 4px byte/pixel exact.  The
    # Japanese text/body to the right is replaced with the clean same-row panel
    # profile sampled immediately to the right at x=92, then painted with the
    # same Galmuri11/cardinal-outline path as the existing main TIP.
    move_before = cut(canvas, RECT_MOVE)
    for y in range(40, 56):
        donor = canvas[y][92]
        gate(donor in {6, 9, 10, 11}, f"이동 donor colour drift y={y}: {donor}")
        for x in range(60, 88):
            canvas[y][x] = donor
    move_paint = paint_text(canvas, (60, 40, 86, 56), "이동", font11)
    move_after = cut(canvas, RECT_MOVE)
    move_jp = cut(jp_canvas, RECT_MOVE)
    gate(
        all(move_after[y][x] == move_jp[y][x] for y in range(16) for x in range(4)),
        "이동: original JP left 4px round not preserved",
    )
    reports.append({
        "label": "이동",
        "source": "移動",
        "operation": "preserve JP left 4px round; clean text body from same-row x=92 donor; paint Korean",
        "rect": list(RECT_MOVE),
        "background_donor_column": 92,
        "font": "Galmuri11.bdf",
        **move_paint,
        "changed_pixels": changed_pixels(move_before, move_after),
    })

    # 4) 持 -> 지, explicitly Galmuri9.  Preserve the original left four pixels.
    # Within the central 8px, only Japanese glyph/shadow/face-like palette values
    # (4/5/10) are replaced by the clean same-row body from x=72.  Structural
    # orange 6/7/8/9 pixels therefore survive.  Paint in x=60..71 so the left
    # round cannot be touched by the outline.
    hold_before = cut(canvas, RECT_HOLD)
    hold_jp = cut(jp_canvas, RECT_HOLD)
    hold_cleared = 0
    for y in range(56, 72):
        donor = canvas[y][72]
        gate(donor in {6, 9, 10, 11}, f"지 donor colour drift y={y}: {donor}")
        for x in range(60, 68):
            if canvas[y][x] in GLYPHISH:
                if canvas[y][x] != donor:
                    hold_cleared += 1
                canvas[y][x] = donor
    hold_paint = paint_native_cardinal(
        canvas, "지", font9,
        origin_x=61, origin_y=59,
        clip=(60, 56, 72, 72),
    )
    hold_after = cut(canvas, RECT_HOLD)
    gate(
        all(hold_after[y][x] == hold_jp[y][x] for y in range(16) for x in range(4)),
        "지: original JP left 4px round not preserved",
    )
    reports.append({
        "label": "지",
        "source": "持",
        "operation": "preserve JP left 4px; selective 4/5/10 cleanup in central 8px; Galmuri9 Korean paint",
        "rect": list(RECT_HOLD),
        "background_donor_column": 72,
        "font": "Galmuri9.bdf",
        "selectively_cleared_pixels": hold_cleared,
        **hold_paint,
        "changed_pixels": changed_pixels(hold_before, hold_after),
    })

    # 5) 残り回数 -> 남은횟수.  Keep the 13px left join exactly.  Starting at
    # x=165, replace only the Japanese text/body with the clean continuation
    # sampled at x=220 on the same scanline.  This mirrors the established anim3
    # Korean panel style without touching the join/round.
    remain_before = cut(canvas, RECT_REMAIN)
    remain_jp = cut(jp_canvas, RECT_REMAIN)
    for y in range(56, 72):
        donor = canvas[y][220]
        gate(donor in {6, 9, 10, 11}, f"남은횟수 donor colour drift y={y}: {donor}")
        for x in range(165, 216):
            canvas[y][x] = donor
    remain_paint = paint_text(canvas, (165, 56, 216, 72), "남은횟수", font11)
    remain_after = cut(canvas, RECT_REMAIN)
    gate(
        all(remain_after[y][x] == remain_jp[y][x] for y in range(16) for x in range(13)),
        "남은횟수: original 13px left join/round not preserved",
    )
    reports.append({
        "label": "남은횟수",
        "source": "残り回数",
        "operation": "preserve JP left 13px join; clean text body from same-row x=220 donor; paint Korean",
        "rect": list(RECT_REMAIN),
        "background_donor_column": 220,
        "font": "Galmuri11.bdf",
        **remain_paint,
        "changed_pixels": changed_pixels(remain_before, remain_after),
    })

    # Canvas-scope gate: absolutely nothing outside the requested regions may
    # change.  The five rectangles include the left-round restoration-only case.
    allowed_rects = [RECT_MOTION, RECT_ARMOR, RECT_MOVE, RECT_HOLD, RECT_REMAIN]
    for y in range(len(canvas)):
        for x in range(len(canvas[0])):
            if canvas[y][x] == before_canvas[y][x]:
                continue
            gate(
                any(x0 <= x < x1 and y0 <= y < y1 for x0, y0, x1, y1 in allowed_rects),
                f"anim3 pixel change escaped requested rectangles at {x},{y}",
            )

    # Rebuild animation 3 by appending private tiles and rebinding only changed
    # lookup entries.  Existing graphics remain byte-exact so all other users of
    # shared tiles retain their current main-TIP artwork.
    header = ss12.spr.parse_resource_header(parent, KO_RES)
    original_resource = parent[header["offset"]:header["offset"] + header["resource_bytes"]]
    graphics = header["graphics"]
    palettes = header["palettes"]
    original_tiles = header["source_tiles"]
    _graphics_rel, records = ss12.animrec.animation_records(parent, KO_RES)
    parsed, ids, lookup_file = ss12.parse_animation_cross(records, 3)
    objects = parsed["objects"]
    min_x = min(int(obj["x"]) for obj in objects)
    min_y = min(int(obj["y"]) for obj in objects)

    existing = {graphics[t * 32:(t + 1) * 32]: t for t in range(original_tiles)}
    private: dict[bytes, int] = {}
    private_payloads: list[bytes] = []
    lookup_writes: dict[int, int] = {}
    cursor = 0
    changed_lookup = 0

    for obj in objects:
        wt = int(obj["size_px"][0]) // 8
        ht = int(obj["size_px"][1]) // 8
        count = wt * ht
        old_ids = ids[cursor:cursor + count]
        for ty in range(ht):
            for tx in range(wt):
                pos = ty * wt + tx
                old_id = int(old_ids[pos])
                ox = int(obj["x"]) - min_x + tx * 8
                oy = int(obj["y"]) - min_y + ty * 8
                payload = ss12.tileops.encode_tile([canvas[oy + yy][ox:ox + 8] for yy in range(8)])
                old_payload = graphics[old_id * 32:(old_id + 1) * 32]
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

    gate(changed_lookup > 0, "animation 3 produced no lookup changes")
    new_graphics = graphics + b"".join(private_payloads)
    new_palette_rel = header["graphics_rel"] + len(new_graphics)
    blob = bytearray(new_palette_rel + len(palettes))
    blob[:header["graphics_rel"]] = original_resource[:header["graphics_rel"]]
    struct.pack_into("<I", blob, 0x0C, new_palette_rel)
    for rel, tile_id in lookup_writes.items():
        struct.pack_into("<H", blob, rel, tile_id)
    blob[header["graphics_rel"]:new_palette_rel] = new_graphics
    blob[new_palette_rel:] = palettes
    gate(new_graphics[:len(graphics)] == graphics, "existing source graphics were rewritten")

    off = KO_RES - 0x08000000
    gate(off + len(blob) <= ALLOC_END, f"092D8000 resource overflow: {len(blob)}")
    if len(blob) > header["resource_bytes"]:
        gate(
            all(v == 0 for v in parent[off + header["resource_bytes"]:off + len(blob)]),
            "092D8000 extension area is not zero-filled",
        )

    output = bytearray(parent)
    output[off:off + len(blob)] = blob
    output = bytes(output)

    # ROM-scope gate: C43/E0518 and every other byte outside this private sprite
    # resource allocation remain parent-exact.
    escaped = [
        i for i, (a, b) in enumerate(zip(parent, output))
        if a != b and not (off <= i < off + len(blob))
    ]
    gate(not escaped, f"ROM changes escaped 092D8000 resource: {[hex(i) for i in escaped[:12]]}")
    gate(output[ALLOC_END:] == parent[ALLOC_END:], "bytes after 092D8000 allocation changed")

    after_canvas, after_pal, after_bank = ss12.resource_canvas(output, KO_RES, 3)
    gate(after_bank == before_bank, "anim3 palette bank changed")
    gate(after_canvas == canvas, "rebuilt anim3 canvas differs from edited canvas")

    # Final preservation gates requested by the user.
    move_after = cut(after_canvas, RECT_MOVE)
    hold_after = cut(after_canvas, RECT_HOLD)
    remain_after = cut(after_canvas, RECT_REMAIN)
    armor_after = cut(after_canvas, RECT_ARMOR)
    gate(all(move_after[y][x] == cut(jp_canvas, RECT_MOVE)[y][x] for y in range(16) for x in range(4)), "final 이동 left round drift")
    gate(all(hold_after[y][x] == cut(jp_canvas, RECT_HOLD)[y][x] for y in range(16) for x in range(4)), "final 지 left round drift")
    gate(all(remain_after[y][x] == cut(jp_canvas, RECT_REMAIN)[y][x] for y in range(16) for x in range(13)), "final 남은횟수 left join drift")
    gate(all(armor_after[y][x] == cut(jp_canvas, RECT_ARMOR)[y][x] for y in range(16) for x in range(4)), "final 장갑 left round drift")
    gate(MAIN_TIP_ROM.read_bytes() == parent, "canonical main TIP changed during candidate build")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    RESULT.write_bytes(output)
    shutil.copy2(MAIN_SAV, SAV)

    # Preview: before / original JP / after, focused on the lower remodel panel.
    crop = (48, 16, 224, 80)
    scale = 3

    def render_crop(src: list[list[int]], pal: bytes, bank: int) -> Image.Image:
        x0, y0, x1, y1 = crop
        piece = [row[x0:x1] for row in src[y0:y1]]
        return animutil.canvas_image(piece, pal, bank, scale)

    before_im = render_crop(before_canvas, before_pal, before_bank)
    jp_im = render_crop(jp_canvas, jp_pal, jp_bank)
    after_im = render_crop(after_canvas, after_pal, after_bank)
    gap = 10
    top = 22
    preview = Image.new("RGB", (before_im.width * 3 + gap * 2, before_im.height + top), (28, 28, 28))
    draw = ImageDraw.Draw(preview)
    draw.text((4, 4), "MAIN BEFORE / JP ORIGINAL / ANIM3 FOLLOW-UP", fill="white")
    preview.paste(before_im, (0, top))
    preview.paste(jp_im, (before_im.width + gap, top))
    preview.paste(after_im, (before_im.width * 2 + gap * 2, top))
    preview.save(PREVIEW)

    # Per-target strips make the preserved round/join pixels easy to inspect.
    for label, rect in (
        ("motion", RECT_MOTION),
        ("armor", RECT_ARMOR),
        ("move", RECT_MOVE),
        ("hold", RECT_HOLD),
        ("remaining", RECT_REMAIN),
    ):
        b = animutil.canvas_image(cut(before_canvas, rect), before_pal, before_bank, 6)
        j = animutil.canvas_image(cut(jp_canvas, rect), jp_pal, jp_bank, 6)
        a = animutil.canvas_image(cut(after_canvas, rect), after_pal, after_bank, 6)
        strip = Image.new("RGB", (b.width + j.width + a.width + 16, max(b.height, j.height, a.height)), (20, 20, 20))
        strip.paste(b, (0, 0))
        strip.paste(j, (b.width + 8, 0))
        strip.paste(a, (b.width + j.width + 16, 0))
        strip.save(OUT_DIR / f"anim3_{label}_before_jp_after_20260905.png")

    manifest = {
        "schema_version": 1,
        "kind": "ggen_advance_remodel_anim3_followup_candidate_20260905",
        "result": "PASS",
        "parent": {
            "path": advance_relative(MAIN_TIP_ROM),
            "sha256": sha256(parent),
            "promotion_reason": meta.get("promotion_reason"),
        },
        "output": {
            "path": advance_relative(RESULT),
            "sha256": sha256(output),
            "size": len(output),
            "sav": advance_relative(SAV),
            "preview": advance_relative(PREVIEW),
        },
        "resource": {
            "address": hex(KO_RES),
            "animation": 3,
            "before_resource_bytes": header["resource_bytes"],
            "after_resource_bytes": len(blob),
            "source_tiles_before": original_tiles,
            "private_tiles_appended": len(private_payloads),
            "changed_lookup_entries": changed_lookup,
            "allocation_end": hex(ALLOC_END),
        },
        "changes": reports,
        "verification": {
            "result": "PASS",
            "main_tip_unmodified": True,
            "only_092d8000_resource_changed": True,
            "existing_source_graphics_preserved": True,
            "animation3_canvas_roundtrip": True,
            "move_left_4px_jp_exact": True,
            "hold_left_4px_jp_exact": True,
            "armor_left_4px_jp_exact": True,
            "remaining_left_13px_jp_exact": True,
            "motion_font": "Galmuri11/cardinal outline matching historical main-TIP ss2 pass",
            "move_font": "Galmuri11/cardinal outline matching historical main-TIP ss2 pass",
            "hold_font": "Galmuri9/cardinal outline",
            "remaining_font": "Galmuri11/cardinal outline",
            "runtime_emulator": "not verified",
        },
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps({
        "output": str(RESULT),
        "sha256": sha256(output),
        "preview": str(PREVIEW),
        "private_tiles_appended": len(private_payloads),
        "changed_lookup_entries": changed_lookup,
        "changes": [{k: r[k] for k in ("label", "source", "font", "changed_pixels")} for r in reports],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
