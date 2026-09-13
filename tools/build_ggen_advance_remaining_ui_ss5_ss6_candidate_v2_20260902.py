#!/usr/bin/env python3
"""Build an ss5/ss6-only UI test ROM from the canonical main TIP.

Scope is intentionally isolated from the parallel ss1/ss2/ss3 graphics work.
Only these labels are changed:
  ss5: パイロット / ユニット / パーツ -> 파일럿 / 유닛 / 파츠
       normal anim 0/1/2 and focus anim 3/4/5 of 0x08C59744.
  ss6: 分解完了 -> 분해완료
       central 64x16 objects 6/7 of anim 6 in the existing 0x092C8000 clone.

The native ss5 package is private-cloned into zero-filled expansion space and
its sole ROM consumer is redirected.  ss6 keeps the already-promoted private
clone and appends/remaps only the selected anim6 object tiles.  The canonical
main TIP is never modified.
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

from PIL import Image

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_develop_menu_buttons_state_20260901 as spr
import analyze_ggen_advance_develop_menu_buttons_images_20260901 as animutil
import analyze_ggen_advance_settings_suspend_ui as animrec
import build_ggen_advance_develop_menu_buttons_ko_image_20260901 as styleops
import build_ggen_advance_settings_suspend_ui_ko_poc as paintops
import build_ggen_advance_map_menu_ui_ko_poc as tileops
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
SS5_SOURCE = 0x08C59744
SS5_CLONE_OFF = 0x012F0000
SS6_CLONE = 0x092C8000
BLOCK_SIZE = 0x8000

OUT_DIR = ADVANCE_ROOT / "outputs" / "20260902_ggen_advance_remaining_ui_ss5_ss6_v2"
OUT_ROM = OUT_DIR / "ggen_advance_remaining_ui_ss5_ss6_candidate_v2_20260902.gba"
OUT_SAV = OUT_DIR / "ggen_advance_remaining_ui_ss5_ss6_candidate_v2_20260902.sav"
OUT_PREVIEW = OUT_DIR / "ggen_advance_remaining_ui_ss5_ss6_candidate_v2_preview_20260902.png"
OUT_MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_remaining_ui_ss5_ss6_candidate_v2_20260902.json"
MAIN_SAV = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).sav"


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def pointer_hits(data: bytes | bytearray, address: int) -> list[int]:
    pattern = struct.pack("<I", address)
    region = bytes(data[:0x01000000])
    hits: list[int] = []
    start = 0
    while True:
        pos = region.find(pattern, start)
        if pos < 0:
            return hits
        hits.append(pos)
        start = pos + 1


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


def repaint_80_button(
    source: list[list[int]],
    text: str,
    font: fontpair.BdfFont,
    *,
    focus: bool,
) -> tuple[list[list[int]], dict[str, Any]]:
    """Erase native Japanese face/outline while preserving 80x16 button chrome."""
    height, width = len(source), len(source[0])
    gate((width, height) == (80, 16), f"{text}: expected 80x16, got {width}x{height}")

    if focus:
        # Native ss5 focus pictures use C face / 4 contour / A body.
        face, contour, body_expected = 0xC, 0x4, 0xA
        ink, korean_contour = 0xC, 0x4
    else:
        # Native ss5 normal pictures use A face / 5 contour / B body.
        face, contour, body_expected = 0xA, 0x5, 0xB
        ink, korean_contour = 0xA, 0x5

    marked = [[pixel in (face, contour) for pixel in row] for row in source]
    body = styleops.button_fill(source, marked, not focus)
    gate(body == body_expected, f"{text}: body index drift {body:X} != {body_expected:X}")

    clean = [row[:] for row in source]
    cleared = 0
    cap_restored = 0
    # Normal pictures use palette 5 for both the outer top/bottom frame and the
    # Japanese contour, so rows 0/15 must remain byte-exact.  Focus pictures use
    # contour 4 over a palette-5 frame; the few 4/C spill pixels in rows 0/15 can
    # therefore be restored deterministically to 5.
    for y in range(height):
        for x in range(width):
            if not marked[y][x]:
                continue
            if y in (0, 15):
                if focus:
                    clean[y][x] = 0x5
                    cleared += 1
                    cap_restored += 1
                continue
            clean[y][x] = styleops.restore_pixel(source, marked, x, y, body)
            cleared += 1
            if not styleops.in_button_body(x, y, width):
                cap_restored += 1
    gate(cleared > 0, f"{text}: no native glyph pixels found")

    if not focus:
        gate(clean[0] == source[0], f"{text}: normal top chrome row drift")
        gate(clean[15] == source[15], f"{text}: normal bottom chrome row drift")
    else:
        gate(all(v != 0x4 and v != 0xC for v in clean[0]), f"{text}: focus top-row Japanese spill remains")
        gate(all(v != 0x4 and v != 0xC for v in clean[15]), f"{text}: focus bottom-row Japanese spill remains")

    mask, text_width = paintops.make_text_mask(text, font, width, height, cell_width=12)
    pixels = [row[:] for row in clean]
    ink_pixels, contour_pixels = styleops.paint_mask_cardinal(
        pixels, mask, ink=ink, contour=korean_contour
    )
    gate(ink_pixels > 0 and contour_pixels > 0, f"{text}: Korean raster empty")
    gate(pixels[0] == clean[0] and pixels[15] == clean[15], f"{text}: Korean raster touched cap row")

    return pixels, {
        "translation": text,
        "style": "focus_blue" if focus else "normal_yellow",
        "size": [80, 16],
        "native_face": face,
        "native_contour": contour,
        "body": body,
        "korean_ink": ink,
        "korean_contour": korean_contour,
        "cleared_native_pixels": cleared,
        "cap_pixels_restored": cap_restored,
        "korean_ink_pixels": ink_pixels,
        "korean_contour_pixels": contour_pixels,
        "text_width_px": text_width,
    }


def remap_animation_canvas(
    header: dict[str, Any],
    parsed: dict[str, Any],
    ids: list[int],
    lookup_file: int,
    canvas: list[list[int]],
    object_indices: list[int],
    existing: dict[bytes, int],
    private: dict[bytes, int],
    private_payloads: list[bytes],
    lookup_writes: dict[int, int],
) -> dict[str, Any]:
    graphics = header["graphics"]
    objects = parsed["objects"]
    selected = [objects[i] for i in object_indices]
    gx0 = min(int(o["x"]) for o in selected)
    gy0 = min(int(o["y"]) for o in selected)

    by_object: list[list[int]] = []
    cursor = 0
    for obj in objects:
        count = int(obj["tile_count"])
        by_object.append(ids[cursor:cursor + count])
        cursor += count

    changed = 0
    before_ids: list[int] = []
    after_ids: list[int] = []
    object_base = 0
    bases: list[int] = []
    for obj in objects:
        bases.append(object_base)
        object_base += int(obj["tile_count"])

    original_tiles = len(graphics) // 32
    for obj_index in object_indices:
        obj = objects[obj_index]
        wt = int(obj["size_px"][0]) // 8
        ht = int(obj["size_px"][1]) // 8
        src_ids = by_object[obj_index]
        for ty in range(ht):
            for tx in range(wt):
                pos = ty * wt + tx
                old_id = int(src_ids[pos])
                ox = int(obj["x"]) - gx0 + tx * 8
                oy = int(obj["y"]) - gy0 + ty * 8
                payload = tileops.encode_tile([canvas[oy + yy][ox:ox + 8] for yy in range(8)])
                old_payload = graphics[old_id * 32:(old_id + 1) * 32]
                if payload == old_payload:
                    new_id = old_id
                elif payload in existing:
                    new_id = existing[payload]
                elif payload in private:
                    new_id = private[payload]
                else:
                    new_id = original_tiles + len(private_payloads)
                    gate(new_id <= 0xFFFF, "source tile id overflow")
                    private[payload] = new_id
                    private_payloads.append(payload)
                before_ids.append(old_id)
                after_ids.append(new_id)
                if new_id != old_id:
                    rel = (lookup_file - int(header["offset"])) + (bases[obj_index] + pos) * 2
                    previous = lookup_writes.get(rel)
                    gate(previous is None or previous == new_id, f"conflicting lookup write 0x{rel:X}")
                    lookup_writes[rel] = new_id
                    changed += 1
    return {
        "objects": object_indices,
        "changed_lookup_entries": changed,
        "source_ids_before": before_ids,
        "source_ids_after": after_ids,
    }


def finalize_clone(
    data: bytes | bytearray,
    address: int,
    private_payloads: list[bytes],
    lookup_writes: dict[int, int],
) -> tuple[bytes, dict[str, Any]]:
    source = bytes(data)
    header = spr.parse_resource_header(source, address)
    original = source[header["offset"]:header["offset"] + header["resource_bytes"]]
    graphics = header["graphics"]
    palettes = header["palettes"]
    new_graphics = graphics + b"".join(private_payloads)
    new_palette_rel = int(header["graphics_rel"]) + len(new_graphics)
    clone = bytearray(new_palette_rel + len(palettes))
    clone[:int(header["graphics_rel"])] = original[:int(header["graphics_rel"])]
    struct.pack_into("<I", clone, 0x0C, new_palette_rel)
    for rel, new_id in lookup_writes.items():
        struct.pack_into("<H", clone, rel, new_id)
    clone[int(header["graphics_rel"]):new_palette_rel] = new_graphics
    clone[new_palette_rel:] = palettes
    gate(new_graphics[:len(graphics)] == graphics, f"0x{address:08X}: original graphics changed")
    gate(clone[new_palette_rel:] == palettes, f"0x{address:08X}: palettes changed")
    return bytes(clone), {
        "source_address": f"0x{address:08X}",
        "source_resource_bytes": int(header["resource_bytes"]),
        "rebuilt_resource_bytes": len(clone),
        "original_source_tiles": len(graphics) // 32,
        "private_source_tiles_appended": len(private_payloads),
        "lookup_writes": len(lookup_writes),
    }


def build_ss5(parent: bytes, font: fontpair.BdfFont) -> tuple[bytes, dict[str, Any], list[tuple[list[list[int]], list[list[int]], bytes, int]]]:
    header = spr.parse_resource_header(parent, SS5_SOURCE)
    graphics = header["graphics"]
    palettes = header["palettes"]
    _rel, records = animrec.animation_records(parent, SS5_SOURCE)

    existing = {graphics[i * 32:(i + 1) * 32]: i for i in range(len(graphics) // 32)}
    private: dict[bytes, int] = {}
    private_payloads: list[bytes] = []
    lookup_writes: dict[int, int] = {}
    reports: list[dict[str, Any]] = []
    previews: list[tuple[list[list[int]], list[list[int]], bytes, int]] = []

    specs = [
        (0, "파일럿", False),
        (1, "유닛", False),
        (2, "파츠", False),
        (3, "파일럿", True),
        (4, "유닛", True),
        (5, "파츠", True),
    ]
    for anim, text, focus in specs:
        parsed, ids, lookup_file = animutil.parse_anim(records, anim)
        indices = list(range(len(parsed["objects"])))
        source_canvas = spr.stitch(graphics, parsed, ids, indices)
        gate((len(source_canvas[0]), len(source_canvas)) == (80, 16), f"ss5 anim{anim} geometry drift")
        rebuilt, paint_report = repaint_80_button(source_canvas, text, font, focus=focus)
        remap_report = remap_animation_canvas(
            header, parsed, ids, lookup_file, rebuilt, indices,
            existing, private, private_payloads, lookup_writes,
        )
        reports.append({"animation": anim, "text": text, "focus": focus, "paint": paint_report, "remap": remap_report})
        previews.append((source_canvas, rebuilt, palettes, 0))

    clone, clone_report = finalize_clone(parent, SS5_SOURCE, private_payloads, lookup_writes)
    clone_report["animations"] = reports
    return clone, clone_report, previews


def build_ss6(candidate: bytes | bytearray, font: fontpair.BdfFont) -> tuple[bytes, dict[str, Any], list[tuple[list[list[int]], list[list[int]], bytes, int]]]:
    source = bytes(candidate)
    header = spr.parse_resource_header(source, SS6_CLONE)
    graphics = header["graphics"]
    palettes = header["palettes"]
    _rel, records = animrec.animation_records(source, SS6_CLONE)
    parsed, ids, lookup_file = animutil.parse_anim(records, 6)
    objects = parsed["objects"]
    gate(len(objects) >= 8, "ss6 anim6 object count drift")
    gate(objects[6]["size_px"] == [32, 16] and objects[7]["size_px"] == [32, 16], "ss6 text objects geometry drift")
    gate((int(objects[6]["x"]), int(objects[6]["y"])) == (8, 8), "ss6 object6 origin drift")
    gate((int(objects[7]["x"]), int(objects[7]["y"])) == (40, 8), "ss6 object7 origin drift")

    indices = [6, 7]
    source_canvas = spr.stitch(graphics, parsed, ids, indices)
    gate((len(source_canvas[0]), len(source_canvas)) == (64, 16), "ss6 central strip is not 64x16")
    # This is a native yellow 64px label: A face / 5 contour / B body.
    rebuilt, paint_report = styleops.rebuild_button(source_canvas, "분해완료", font, 0xA, 0x5, palettes, 0)

    existing = {graphics[i * 32:(i + 1) * 32]: i for i in range(len(graphics) // 32)}
    private: dict[bytes, int] = {}
    private_payloads: list[bytes] = []
    lookup_writes: dict[int, int] = {}
    remap_report = remap_animation_canvas(
        header, parsed, ids, lookup_file, rebuilt, indices,
        existing, private, private_payloads, lookup_writes,
    )
    clone, clone_report = finalize_clone(source, SS6_CLONE, private_payloads, lookup_writes)
    clone_report.update({"animation": 6, "paint": paint_report, "remap": remap_report})
    return clone, clone_report, [(source_canvas, rebuilt, palettes, 0)]


def run_regression() -> dict[str, str]:
    tests = [
        ADVANCE_ROOT / "tools" / "test_ggen_advance_unified_pipeline.py",
        ADVANCE_ROOT / "tools" / "test_ggen_advance_intermission_development_fix.py",
    ]
    result: dict[str, str] = {}
    for path in tests:
        cp = subprocess.run([sys.executable, str(path)], cwd=str(ADVANCE_ROOT), capture_output=True, text=True)
        gate(cp.returncode == 0, f"{path.name} failed: {cp.stderr[-600:]}")
        result[path.name] = "PASS"
    return result


def main() -> int:
    parent = MAIN_TIP_ROM.read_bytes()
    jp = ORIGINAL_ROM.read_bytes()
    main_manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(parent) == main_manifest["sha256"], "main TIP / manifest hash mismatch")
    gate(MAIN_SAV.is_file(), "main SAV missing")

    # Guard against the previous mistaken ss3 interpretation: the current main
    # still has the clean/native ss5 source package at 0x08C59744.
    hp = spr.parse_resource_header(parent, SS5_SOURCE)
    hj = spr.parse_resource_header(jp, SS5_SOURCE)
    gate(parent[hp["offset"]:hp["offset"] + hp["resource_bytes"]] == jp[hj["offset"]:hj["offset"] + hj["resource_bytes"]], "ss5 source resource already modified in main TIP")
    hits = pointer_hits(parent, SS5_SOURCE)
    gate(hits == [0x0006F074], f"ss5 consumer drift: {[hex(x) for x in hits]}")

    candidate = bytearray(parent)
    allowed: set[int] = set()
    previews: list[tuple[list[list[int]], list[list[int]], bytes, int]] = []

    with ZipFile(FONT_ZIP) as archive:
        font = fontpair.load_bdf(archive, "Galmuri11.bdf")

    # ss5 private clone + sole consumer redirect.
    ss5_clone, ss5_report, ss5_previews = build_ss5(parent, font)
    gate(SS5_CLONE_OFF + len(ss5_clone) <= SS5_CLONE_OFF + BLOCK_SIZE, "ss5 clone exceeds 0x8000 block")
    gate(all(v == 0 for v in parent[SS5_CLONE_OFF:SS5_CLONE_OFF + len(ss5_clone)]), "ss5 clone allocation not zero-filled")
    candidate[SS5_CLONE_OFF:SS5_CLONE_OFF + len(ss5_clone)] = ss5_clone
    allowed.update(range(SS5_CLONE_OFF, SS5_CLONE_OFF + len(ss5_clone)))
    for hit in hits:
        struct.pack_into("<I", candidate, hit, ROM_BASE + SS5_CLONE_OFF)
        allowed.update(range(hit, hit + 4))
    ss5_report.update({
        "method": "private clone + sole consumer redirect",
        "clone_file_offset": f"0x{SS5_CLONE_OFF:08X}",
        "clone_address": f"0x{ROM_BASE + SS5_CLONE_OFF:08X}",
        "redirected_refs": [f"0x{x:08X}" for x in hits],
    })
    previews.extend(ss5_previews)

    # ss6 in-place rebuild of existing private clone; no original source or
    # consumer tables are touched.
    ss6_clone, ss6_report, ss6_previews = build_ss6(candidate, font)
    ss6_off = SS6_CLONE - ROM_BASE
    ss6_old = spr.parse_resource_header(parent, SS6_CLONE)
    ss6_limit = ((ss6_off // BLOCK_SIZE) + 1) * BLOCK_SIZE
    gate(ss6_off + len(ss6_clone) <= ss6_limit, "ss6 private clone growth exceeds allocation")
    gate(all(v == 0 for v in parent[ss6_off + ss6_old["resource_bytes"]:ss6_off + len(ss6_clone)]), "ss6 growth tail is not zero-filled")
    candidate[ss6_off:ss6_off + len(ss6_clone)] = ss6_clone
    allowed.update(range(ss6_off, ss6_off + len(ss6_clone)))
    ss6_report.update({
        "method": "append private tiles + remap only anim6 objects 6/7 in existing private clone",
        "allocation": [f"0x{ss6_off:08X}", f"0x{ss6_limit:08X}"],
    })
    previews.extend(ss6_previews)

    # Native sources for both tasks remain byte-exact in the candidate.
    for address in (SS5_SOURCE, 0x08C5FD14):
        h = spr.parse_resource_header(parent, address)
        gate(candidate[h["offset"]:h["offset"] + h["resource_bytes"]] == parent[h["offset"]:h["offset"] + h["resource_bytes"]], f"native source 0x{address:08X} modified")

    changed = [i for i, (a, b) in enumerate(zip(parent, candidate)) if a != b]
    escaped = [i for i in changed if i not in allowed]
    gate(not escaped, f"changes escaped allowed ranges: {escaped[:16]}")
    gate(set(range(0x0006F074, 0x0006F078)).issubset(set(changed)), "ss5 consumer redirect missing")

    cp = subprocess.run([sys.executable, "-m", "py_compile", str(Path(__file__))], cwd=str(ADVANCE_ROOT), capture_output=True, text=True)
    gate(cp.returncode == 0, f"py_compile failed: {cp.stderr}")
    regression = run_regression()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_ROM.write_bytes(candidate)
    shutil.copy2(MAIN_SAV, OUT_SAV)

    scale = 3
    thumb_w, thumb_h = 80 * scale, 16 * scale
    preview = Image.new("RGB", (2 * thumb_w + 12, len(previews) * thumb_h + 8), (16, 16, 16))
    for index, (before, after, palettes, bank) in enumerate(previews):
        # ss6 is 64px, so left-align it in the 80px preview slot.
        y = 4 + index * thumb_h
        bimg = animutil.canvas_image(before, palettes, bank, scale)
        aimg = animutil.canvas_image(after, palettes, bank, scale)
        preview.paste(bimg, (4, y))
        preview.paste(aimg, (thumb_w + 8, y))
    preview.save(OUT_PREVIEW)

    output = bytes(candidate)
    manifest = {
        "schema_version": 1,
        "kind": "ggen_advance_remaining_ui_ss5_ss6_candidate_v2_20260902",
        "result": "PASS",
        "scope": {
            "included_states": [5, 6],
            "excluded_parallel_work": [
                "ss1/ss2 status/develop graphics",
                "탑재/내리기/이동/변형",
                "이동/한계/범용/장갑",
                "이동타입/현재소속",
                "강화비용/보급P",
            ],
            "translations": {
                "ss5": {"パイロット": "파일럿", "ユニット": "유닛", "パーツ": "파츠"},
                "ss6": {"分解完了": "분해완료"},
            },
        },
        "source": {
            "parent": advance_relative(MAIN_TIP_ROM),
            "parent_sha256": sha256(parent),
            "main_tip_manifest": advance_relative(MAIN_TIP_MANIFEST),
        },
        "patch": {
            "font": "Galmuri11.bdf native 12x12",
            "ss5": ss5_report,
            "ss6": ss6_report,
        },
        "output": {
            "rom": advance_relative(OUT_ROM),
            "rom_sha256": sha256(output),
            "size": len(output),
            "sav": advance_relative(OUT_SAV),
            "sav_sha256": sha256(OUT_SAV.read_bytes()),
            "preview": advance_relative(OUT_PREVIEW),
            "changed_bytes": len(changed),
            "changed_ranges": changed_ranges(changed),
        },
        "verification": {
            "result": "PASS",
            "py_compile": "PASS",
            "regression": regression,
            "canonical_main_tip_unchanged": sha256(MAIN_TIP_ROM.read_bytes()) == main_manifest["sha256"],
            "ss5_source_resource_unchanged": True,
            "ss6_original_source_resource_unchanged": True,
            "ss5_consumer": "0x0806F074 -> 0x092F0000 in candidate only",
            "ss6_target": "0x092C8000 anim6 objects 6/7 only",
        },
    }
    OUT_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "rom": advance_relative(OUT_ROM),
        "rom_sha256": sha256(output),
        "sav": advance_relative(OUT_SAV),
        "preview": advance_relative(OUT_PREVIEW),
        "manifest": advance_relative(OUT_MANIFEST),
        "changed_bytes": len(changed),
        "main_tip_sha256": sha256(parent),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
