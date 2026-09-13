#!/usr/bin/env python3
"""Refine remodel anim3 left caps on top of the first follow-up candidate.

User-requested follow-up:
* 이동 / 장갑: replace the awkward location-specific JP 4px left join/cap with
  a common rounded profile derived from the clean 운동-style panel edge.
* 지: keep the existing Korean glyph/body, but simplify the left 4px cap to an
  HP-like orange-only chrome by converting yellow/dark glyph-like values to the
  orange rim index while preserving native orange/red rim pixels.

Only animation 3 of sprite resource 0x092D8000 is rebound. Existing source
pixels/tiles are not rewritten; edited cells are appended as private tiles.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import struct
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import build_ggen_advance_remodel_anim3_followup_20260905 as prev
from ggen_advance_project_paths import ADVANCE_ROOT, advance_relative

PARENT = prev.RESULT
PARENT_SAV = prev.SAV
KO_RES = prev.KO_RES
ALLOC_END = prev.ALLOC_END

RECT_MOTION = prev.RECT_MOTION
RECT_ARMOR = prev.RECT_ARMOR
RECT_MOVE = prev.RECT_MOVE
RECT_HOLD = prev.RECT_HOLD
RECT_REMAIN = prev.RECT_REMAIN

OUT_DIR = ADVANCE_ROOT / "outputs" / "20260905_ggen_advance_remodel_anim3_followup2"
RESULT = OUT_DIR / "ggen_advance_remodel_anim3_followup2_candidate_20260905.gba"
SAV = RESULT.with_suffix(".sav")
PREVIEW = OUT_DIR / "ggen_advance_remodel_anim3_followup2_preview_20260905.png"
MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_remodel_anim3_followup2_candidate_20260905.json"

# Clean four-pixel independent rounded cap derived from the 운동 panel's native
# vertical/rim progression, but without any glyph/outline pixels mixed into it.
# Palette indices: 6=outer red/orange rim, 7/8/9=orange/amber transition,
# A/B=bright inner panel.  The profile is vertically symmetric.
COMMON_ROUND4 = (
    (6, 6, 6, 6),
    (7, 8, 9, 9),
    (8, 9, 10, 10),
    *((9, 10, 11, 11),) * 10,
    (8, 9, 10, 10),
    (7, 8, 9, 9),
    (6, 6, 6, 6),
)

# HP-like simplified cap: index 7 is the orange rim tone.  Existing 6/7 pixels
# are already red/orange structure and stay intact; everything else in the left
# four pixels becomes 7 so no yellow/black-looking fragments remain.
HOLD_ORANGE = 7
HOLD_KEEP = {6, 7}


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


def main() -> int:
    gate(PARENT.is_file(), f"parent candidate missing: {PARENT}")
    gate(PARENT_SAV.is_file(), f"parent SAV missing: {PARENT_SAV}")
    parent = PARENT.read_bytes()
    gate(len(parent) == 32 * 1024 * 1024, "parent candidate size drift")

    before_canvas, before_pal, before_bank = prev.ss12.resource_canvas(parent, KO_RES, 3)
    canvas = [row[:] for row in before_canvas]
    reports: list[dict[str, Any]] = []

    # 1) 이동 / 장갑: normalize only the first four pixels to the clean
    # 운동-style rounded profile.  Text/body from x+4 onward remains exact.
    for label, rect in (("이동", RECT_MOVE), ("장갑", RECT_ARMOR)):
        x0, y0, _x1, y1 = rect
        gate(y1 - y0 == 16, f"{label}: unexpected plaque height")
        before = cut(canvas, rect)
        for ly, row_profile in enumerate(COMMON_ROUND4):
            canvas[y0 + ly][x0:x0 + 4] = list(row_profile)
        after = cut(canvas, rect)
        gate(
            all(after[y][x] == before[y][x] for y in range(16) for x in range(4, len(after[0]))),
            f"{label}: pixels outside left 4px changed",
        )
        gate(
            all(tuple(after[y][:4]) == COMMON_ROUND4[y] for y in range(16)),
            f"{label}: common round profile mismatch",
        )
        reports.append({
            "label": label,
            "operation": "replace left 4px with clean 운동-derived common rounded cap",
            "rect": list(rect),
            "left_cap_profile": [list(v) for v in COMMON_ROUND4],
            "changed_pixels": changed_pixels(before, after),
        })

    # 2) 지: preserve the Korean glyph/body and simplify the left four pixels.
    # All yellow/black-like values become orange index 7; native 6/7 rim pixels
    # stay intact.  This intentionally favors a simple HP-like orange cap over
    # the previous JP-derived yellow-heavy join.
    x0, y0, _x1, y1 = RECT_HOLD
    hold_before = cut(canvas, RECT_HOLD)
    converted = 0
    for y in range(y0, y1):
        for x in range(x0, x0 + 4):
            if canvas[y][x] not in HOLD_KEEP:
                if canvas[y][x] != HOLD_ORANGE:
                    converted += 1
                canvas[y][x] = HOLD_ORANGE
    hold_after = cut(canvas, RECT_HOLD)
    gate(
        all(hold_after[y][x] == hold_before[y][x] for y in range(16) for x in range(4, len(hold_after[0]))),
        "지: pixels outside left 4px changed",
    )
    gate(
        all(hold_after[y][x] in HOLD_KEEP for y in range(16) for x in range(4)),
        "지: left cap still contains non-orange/red values",
    )
    reports.append({
        "label": "지",
        "operation": "HP-like orange-only left 4px cap; preserve existing 6/7, convert all other values to 7",
        "rect": list(RECT_HOLD),
        "orange_index": HOLD_ORANGE,
        "preserved_indices": sorted(HOLD_KEEP),
        "converted_pixels": converted,
        "changed_pixels": changed_pixels(hold_before, hold_after),
    })

    # Scope gate: only the requested left 4px bands may differ from the parent.
    allowed = [
        (RECT_MOVE[0], RECT_MOVE[1], RECT_MOVE[0] + 4, RECT_MOVE[3]),
        (RECT_ARMOR[0], RECT_ARMOR[1], RECT_ARMOR[0] + 4, RECT_ARMOR[3]),
        (RECT_HOLD[0], RECT_HOLD[1], RECT_HOLD[0] + 4, RECT_HOLD[3]),
    ]
    for y in range(len(canvas)):
        for x in range(len(canvas[0])):
            if canvas[y][x] == before_canvas[y][x]:
                continue
            gate(
                any(ax0 <= x < ax1 and ay0 <= y < ay1 for ax0, ay0, ax1, ay1 in allowed),
                f"anim3 change escaped requested cap bands at {x},{y}",
            )

    # Rebuild animation 3 by appending private tiles and rebinding only changed
    # lookup entries, exactly like the parent follow-up builder.
    header = prev.ss12.spr.parse_resource_header(parent, KO_RES)
    original_resource = parent[header["offset"]:header["offset"] + header["resource_bytes"]]
    graphics = header["graphics"]
    palettes = header["palettes"]
    original_tiles = header["source_tiles"]
    _graphics_rel, records = prev.ss12.animrec.animation_records(parent, KO_RES)
    parsed, ids, lookup_file = prev.ss12.parse_animation_cross(records, 3)
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
                payload = prev.ss12.tileops.encode_tile([canvas[oy + yy][ox:ox + 8] for yy in range(8)])
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

    escaped = [
        i for i, (a, b) in enumerate(zip(parent, output))
        if a != b and not (off <= i < off + len(blob))
    ]
    gate(not escaped, f"ROM changes escaped 092D8000 resource: {[hex(i) for i in escaped[:12]]}")
    gate(output[ALLOC_END:] == parent[ALLOC_END:], "bytes after 092D8000 allocation changed")

    after_canvas, after_pal, after_bank = prev.ss12.resource_canvas(output, KO_RES, 3)
    gate(after_bank == before_bank, "anim3 palette bank changed")
    gate(after_canvas == canvas, "rebuilt anim3 canvas differs from edited canvas")

    # Preserve all previously approved follow-up labels outside the three cap bands.
    for label, rect in (("운동", RECT_MOTION), ("남은횟수", RECT_REMAIN)):
        gate(cut(after_canvas, rect) == cut(before_canvas, rect), f"{label}: previous follow-up content drift")
    for label, rect in (("이동", RECT_MOVE), ("장갑", RECT_ARMOR), ("지", RECT_HOLD)):
        before = cut(before_canvas, rect)
        after = cut(after_canvas, rect)
        gate(
            all(after[y][x] == before[y][x] for y in range(16) for x in range(4, len(after[0]))),
            f"{label}: body/text drift outside left cap",
        )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    RESULT.write_bytes(output)
    shutil.copy2(PARENT_SAV, SAV)

    # Focused before/after preview and per-target strips.
    crop = (48, 16, 224, 80)
    scale = 3

    def render_crop(src: list[list[int]], pal: bytes, bank: int) -> Image.Image:
        x0, y0, x1, y1 = crop
        piece = [row[x0:x1] for row in src[y0:y1]]
        return prev.animutil.canvas_image(piece, pal, bank, scale)

    before_im = render_crop(before_canvas, before_pal, before_bank)
    after_im = render_crop(after_canvas, after_pal, after_bank)
    gap = 10
    top = 22
    preview = Image.new("RGB", (before_im.width * 2 + gap, before_im.height + top), (28, 28, 28))
    draw = ImageDraw.Draw(preview)
    draw.text((4, 4), "FOLLOW-UP1 BEFORE / FOLLOW-UP2 AFTER", fill="white")
    preview.paste(before_im, (0, top))
    preview.paste(after_im, (before_im.width + gap, top))
    preview.save(PREVIEW)

    for label, rect in (("move", RECT_MOVE), ("armor", RECT_ARMOR), ("hold", RECT_HOLD)):
        b = prev.animutil.canvas_image(cut(before_canvas, rect), before_pal, before_bank, 8)
        a = prev.animutil.canvas_image(cut(after_canvas, rect), after_pal, after_bank, 8)
        strip = Image.new("RGB", (b.width + a.width + 8, max(b.height, a.height)), (20, 20, 20))
        strip.paste(b, (0, 0))
        strip.paste(a, (b.width + 8, 0))
        strip.save(OUT_DIR / f"anim3_{label}_before_after_followup2_20260905.png")

    manifest = {
        "schema_version": 1,
        "kind": "ggen_advance_remodel_anim3_followup2_candidate_20260905",
        "result": "PASS",
        "parent": {
            "path": advance_relative(PARENT),
            "sha256": sha256(parent),
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
            "parent_candidate_unmodified": PARENT.read_bytes() == parent,
            "only_092d8000_resource_changed": True,
            "existing_source_graphics_preserved": True,
            "animation3_canvas_roundtrip": True,
            "motion_unchanged": True,
            "remaining_unchanged": True,
            "move_body_text_unchanged": True,
            "armor_body_text_unchanged": True,
            "hold_body_text_unchanged": True,
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
        "changes": reports,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
