#!/usr/bin/env python3
"""Build the ss5/ss6 background-preserving follow-up candidate.

This is a focused follow-up to the measured v2 candidate.  Runtime confirmed
that the Korean labels themselves are correct, but v2 erased every palette
pixel equal to the Japanese face/contour values.  Those indices are also used
by native chrome, which created yellow holes in ss5's red/orange gradient and
left an uneven ss6 background.

v3 does not heuristically inpaint those colors.  Instead it reconstructs the
exact text-free chrome geometry proven by the six ss5 source animations and by
the ss6 64x16 central label strip.  Static gates require that the clean template
only differs from the Japanese source at native face/contour pixels; therefore
all non-text gradient/frame pixels remain byte-exact.  Korean is then painted
on that clean template and only the selected source lookups are remapped.

Scope stays isolated from parallel work:
  ss5: パイロット / ユニット / パーツ -> 파일럿 / 유닛 / 파츠
  ss6: 分解完了 -> 분해완료
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
import build_ggen_advance_remaining_ui_ss5_ss6_candidate_v2_20260902 as v2
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
SS5_SOURCE = v2.SS5_SOURCE
SS5_CLONE_OFF = v2.SS5_CLONE_OFF
SS6_CLONE = v2.SS6_CLONE
BLOCK_SIZE = v2.BLOCK_SIZE
MAIN_SAV = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).sav"

OUT_DIR = ADVANCE_ROOT / "outputs" / "20260903_ggen_advance_remaining_ui_ss5_ss6_v3"
OUT_ROM = OUT_DIR / "ggen_advance_remaining_ui_ss5_ss6_candidate_v3_20260903.gba"
OUT_SAV = OUT_DIR / "ggen_advance_remaining_ui_ss5_ss6_candidate_v3_20260903.sav"
OUT_PREVIEW = OUT_DIR / "ggen_advance_remaining_ui_ss5_ss6_candidate_v3_preview_20260903.png"
OUT_MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_remaining_ui_ss5_ss6_candidate_v3_20260903.json"


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def ss5_clean_chrome(source: list[list[int]], *, focus: bool) -> tuple[list[list[int]], dict[str, Any]]:
    """Reconstruct exact native 80x16 chrome without any Japanese glyph pixels.

    Across anim0..2 and anim3..5 the left red/orange cap and the horizontal
    frame rows are byte-identical.  Only face/contour pixels differ from the
    following row geometry.  The gate below enforces that claim per animation.
    """
    height, width = len(source), len(source[0])
    gate((width, height) == (80, 16), f"ss5 chrome geometry drift: {width}x{height}")
    face, contour, body = (0xC, 0x4, 0xA) if focus else (0xA, 0x5, 0xB)

    clean = [row[:] for row in source]
    # (prefix pixels kept byte-exact from source, fill value for the rest)
    row_geometry = {
        0: (2, 0x5),
        1: (5, 0x8),
        2: (5, 0x9),
        3: (7, body),
        12: (7, body),
        13: (5, 0x9),
        14: (5, 0x8),
        15: (2, 0x5),
    }
    for y in range(16):
        prefix, fill = row_geometry.get(y, (6, body))
        clean[y][prefix:] = [fill] * (80 - prefix)

    diffs = [
        (x, y, source[y][x], clean[y][x])
        for y in range(16)
        for x in range(80)
        if source[y][x] != clean[y][x]
    ]
    non_text = [row for row in diffs if row[2] not in (face, contour)]
    gate(not non_text, f"ss5 clean template changed non-text chrome: {non_text[:8]}")
    gate(diffs, "ss5 clean template unexpectedly identical to Japanese source")

    return clean, {
        "template": "native 80x16 row-geometry reconstruction",
        "native_face": face,
        "native_contour": contour,
        "body": body,
        "japanese_pixels_removed": len(diffs),
        "non_text_chrome_differences": len(non_text),
        "gradient_prefix_preserved": True,
    }


def paint_ss5(clean: list[list[int]], text: str, font: fontpair.BdfFont, *, focus: bool) -> tuple[list[list[int]], dict[str, Any]]:
    body = 0xA if focus else 0xB
    ink = 0xC if focus else 0xA
    contour = 0x4 if focus else 0x5
    mask, text_width = v2.paintops.make_text_mask(text, font, 80, 16, cell_width=12)
    pixels = [row[:] for row in clean]
    ink_pixels, contour_pixels = v2.styleops.paint_mask_cardinal(pixels, mask, ink=ink, contour=contour)
    gate(ink_pixels > 0 and contour_pixels > 0, f"{text}: Korean raster empty")
    gate(pixels[0] == clean[0] and pixels[15] == clean[15], f"{text}: Korean raster touched outer frame")
    return pixels, {
        "translation": text,
        "style": "focus_blue" if focus else "normal_yellow",
        "body": body,
        "korean_ink": ink,
        "korean_contour": contour,
        "text_width_px": text_width,
        "korean_ink_pixels": ink_pixels,
        "korean_contour_pixels": contour_pixels,
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
        clean, clean_report = ss5_clean_chrome(source_canvas, focus=focus)
        rebuilt, paint_report = paint_ss5(clean, text, font, focus=focus)
        remap_report = v2.remap_animation_canvas(
            header, parsed, ids, lookup_file, rebuilt, indices,
            existing, private, private_payloads, lookup_writes,
        )
        reports.append({
            "animation": anim,
            "text": text,
            "focus": focus,
            "clean_chrome": clean_report,
            "paint": paint_report,
            "remap": remap_report,
        })
        previews.append((source_canvas, rebuilt, palettes, 0))

    clone, clone_report = v2.finalize_clone(parent, SS5_SOURCE, private_payloads, lookup_writes)
    clone_report["animations"] = reports
    clone_report["background_restore"] = "deterministic text-free row geometry; zero non-text chrome changes"
    return clone, clone_report, previews


def ss6_clean_chrome(source: list[list[int]]) -> tuple[list[list[int]], dict[str, Any]]:
    """Build exact text-free 64x16 normal-yellow chrome for the completion label."""
    gate((len(source[0]), len(source)) == (64, 16), "ss6 clean chrome geometry drift")
    clean = [[0xB] * 64 for _ in range(16)]
    for y in range(16):
        if y in (0, 15):
            continue
        if y in (1, 14):
            for x in range(3, 62):
                clean[y][x] = 0x9
        elif y in (2, 13):
            for x in (2, 3, 60, 61, 62):
                clean[y][x] = 0x9
        else:
            for x in (1, 2, 61, 62):
                clean[y][x] = 0x9

    diffs = [
        (x, y, source[y][x], clean[y][x])
        for y in range(16)
        for x in range(64)
        if source[y][x] != clean[y][x]
    ]
    non_text = [row for row in diffs if row[2] not in (0xA, 0x5)]
    gate(not non_text, f"ss6 clean template changed non-text chrome: {non_text[:8]}")
    gate(diffs, "ss6 clean template unexpectedly identical to Japanese source")
    return clean, {
        "template": "native 64x16 normal-yellow rounded chrome",
        "native_face": 0xA,
        "native_contour": 0x5,
        "body": 0xB,
        "border": 0x9,
        "japanese_pixels_removed": len(diffs),
        "non_text_chrome_differences": len(non_text),
    }


def paint_ss6(clean: list[list[int]], font: fontpair.BdfFont) -> tuple[list[list[int]], dict[str, Any]]:
    mask, text_width = v2.paintops.make_text_mask("분해완료", font, 64, 16, cell_width=12)
    pixels = [row[:] for row in clean]
    ink_pixels, contour_pixels = v2.styleops.paint_mask_cardinal(pixels, mask, ink=0xA, contour=0x5)
    gate(ink_pixels > 0 and contour_pixels > 0, "ss6 Korean raster empty")
    gate(pixels[0] == clean[0] and pixels[15] == clean[15], "ss6 Korean raster touched outer frame")
    return pixels, {
        "translation": "분해완료",
        "style": "normal_yellow",
        "body": 0xB,
        "korean_ink": 0xA,
        "korean_contour": 0x5,
        "text_width_px": text_width,
        "korean_ink_pixels": ink_pixels,
        "korean_contour_pixels": contour_pixels,
    }


def build_ss6(candidate: bytes | bytearray, font: fontpair.BdfFont) -> tuple[bytes, dict[str, Any], list[tuple[list[list[int]], list[list[int]], bytes, int]]]:
    source = bytes(candidate)
    header = spr.parse_resource_header(source, SS6_CLONE)
    graphics = header["graphics"]
    palettes = header["palettes"]
    _rel, records = animrec.animation_records(source, SS6_CLONE)
    parsed, ids, lookup_file = animutil.parse_anim(records, 6)
    objects = parsed["objects"]
    gate(len(objects) >= 10, "ss6 anim6 object count drift")
    gate(objects[6]["size_px"] == [32, 16] and objects[7]["size_px"] == [32, 16], "ss6 text objects geometry drift")
    gate((int(objects[6]["x"]), int(objects[6]["y"])) == (8, 8), "ss6 object6 origin drift")
    gate((int(objects[7]["x"]), int(objects[7]["y"])) == (40, 8), "ss6 object7 origin drift")
    gate(objects[8]["palette_bank"] == 1 and objects[9]["palette_bank"] == 1, "ss6 side-cap palette drift")

    indices = [6, 7]
    source_canvas = spr.stitch(graphics, parsed, ids, indices)
    clean, clean_report = ss6_clean_chrome(source_canvas)
    rebuilt, paint_report = paint_ss6(clean, font)

    existing = {graphics[i * 32:(i + 1) * 32]: i for i in range(len(graphics) // 32)}
    private: dict[bytes, int] = {}
    private_payloads: list[bytes] = []
    lookup_writes: dict[int, int] = {}
    remap_report = v2.remap_animation_canvas(
        header, parsed, ids, lookup_file, rebuilt, indices,
        existing, private, private_payloads, lookup_writes,
    )
    clone, clone_report = v2.finalize_clone(source, SS6_CLONE, private_payloads, lookup_writes)
    clone_report.update({
        "animation": 6,
        "clean_chrome": clean_report,
        "paint": paint_report,
        "remap": remap_report,
        "background_restore": "synthetic native chrome before Korean paint; no Japanese A/5 retained",
    })
    return clone, clone_report, [(source_canvas, rebuilt, palettes, 0)]


def main() -> int:
    parent = MAIN_TIP_ROM.read_bytes()
    jp = ORIGINAL_ROM.read_bytes()
    main_manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(parent) == main_manifest["sha256"], "main TIP / manifest hash mismatch")
    gate(MAIN_SAV.is_file(), "main SAV missing")

    hp = spr.parse_resource_header(parent, SS5_SOURCE)
    hj = spr.parse_resource_header(jp, SS5_SOURCE)
    gate(
        parent[hp["offset"]:hp["offset"] + hp["resource_bytes"]]
        == jp[hj["offset"]:hj["offset"] + hj["resource_bytes"]],
        "ss5 source resource already modified in main TIP",
    )
    hits = v2.pointer_hits(parent, SS5_SOURCE)
    gate(hits == [0x0006F074], f"ss5 consumer drift: {[hex(x) for x in hits]}")

    candidate = bytearray(parent)
    allowed: set[int] = set()
    previews: list[tuple[list[list[int]], list[list[int]], bytes, int]] = []

    with ZipFile(FONT_ZIP) as archive:
        font = fontpair.load_bdf(archive, "Galmuri11.bdf")

    ss5_clone, ss5_report, ss5_previews = build_ss5(parent, font)
    gate(SS5_CLONE_OFF + len(ss5_clone) <= SS5_CLONE_OFF + BLOCK_SIZE, "ss5 clone exceeds 0x8000 block")
    gate(all(v == 0 for v in parent[SS5_CLONE_OFF:SS5_CLONE_OFF + len(ss5_clone)]), "ss5 clone allocation not zero-filled")
    candidate[SS5_CLONE_OFF:SS5_CLONE_OFF + len(ss5_clone)] = ss5_clone
    allowed.update(range(SS5_CLONE_OFF, SS5_CLONE_OFF + len(ss5_clone)))
    for hit in hits:
        struct.pack_into("<I", candidate, hit, ROM_BASE + SS5_CLONE_OFF)
        allowed.update(range(hit, hit + 4))
    ss5_report.update({
        "method": "private clone + exact chrome reconstruction + sole consumer redirect",
        "clone_file_offset": f"0x{SS5_CLONE_OFF:08X}",
        "clone_address": f"0x{ROM_BASE + SS5_CLONE_OFF:08X}",
        "redirected_refs": [f"0x{x:08X}" for x in hits],
    })
    previews.extend(ss5_previews)

    ss6_clone, ss6_report, ss6_previews = build_ss6(candidate, font)
    ss6_off = SS6_CLONE - ROM_BASE
    ss6_old = spr.parse_resource_header(parent, SS6_CLONE)
    ss6_limit = ((ss6_off // BLOCK_SIZE) + 1) * BLOCK_SIZE
    gate(ss6_off + len(ss6_clone) <= ss6_limit, "ss6 private clone growth exceeds allocation")
    gate(
        all(v == 0 for v in parent[ss6_off + ss6_old["resource_bytes"]:ss6_off + len(ss6_clone)]),
        "ss6 growth tail is not zero-filled",
    )
    candidate[ss6_off:ss6_off + len(ss6_clone)] = ss6_clone
    allowed.update(range(ss6_off, ss6_off + len(ss6_clone)))
    ss6_report.update({
        "method": "exact chrome reconstruction + remap anim6 objects 6/7 only",
        "allocation": [f"0x{ss6_off:08X}", f"0x{ss6_limit:08X}"],
    })
    previews.extend(ss6_previews)

    # Parallel-session/native sources remain byte-exact.
    for address in (SS5_SOURCE, 0x08C5FD14):
        h = spr.parse_resource_header(parent, address)
        gate(
            candidate[h["offset"]:h["offset"] + h["resource_bytes"]]
            == parent[h["offset"]:h["offset"] + h["resource_bytes"]],
            f"native source 0x{address:08X} modified",
        )

    changed = [i for i, (a, b) in enumerate(zip(parent, candidate)) if a != b]
    escaped = [i for i in changed if i not in allowed]
    gate(not escaped, f"changes escaped allowed ranges: {escaped[:16]}")
    gate(set(range(0x0006F074, 0x0006F078)).issubset(set(changed)), "ss5 consumer redirect missing")

    cp = subprocess.run([sys.executable, "-m", "py_compile", str(Path(__file__))], cwd=str(ADVANCE_ROOT), capture_output=True, text=True)
    gate(cp.returncode == 0, f"py_compile failed: {cp.stderr}")
    regression = v2.run_regression()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_ROM.write_bytes(candidate)
    shutil.copy2(MAIN_SAV, OUT_SAV)

    scale = 3
    thumb_w, thumb_h = 80 * scale, 16 * scale
    preview = Image.new("RGB", (2 * thumb_w + 12, len(previews) * thumb_h + 8), (16, 16, 16))
    for index, (before, after, palettes, bank) in enumerate(previews):
        y = 4 + index * thumb_h
        preview.paste(animutil.canvas_image(before, palettes, bank, scale), (4, y))
        preview.paste(animutil.canvas_image(after, palettes, bank, scale), (thumb_w + 8, y))
    preview.save(OUT_PREVIEW)

    output = bytes(candidate)
    manifest = {
        "schema_version": 1,
        "kind": "ggen_advance_remaining_ui_ss5_ss6_candidate_v3_20260903",
        "result": "PASS",
        "runtime_followup": {
            "v2_ss5_issue": "global face/contour erase also changed native red/orange chrome",
            "v2_ss6_issue": "background retained/introduced uneven Japanese-looking dark residue",
            "v3_policy": "reconstruct exact text-free chrome first; paint Korean second",
        },
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
            "changed_ranges": v2.changed_ranges(changed),
        },
        "verification": {
            "result": "PASS",
            "py_compile": "PASS",
            "regression": regression,
            "canonical_main_tip_unchanged": sha256(MAIN_TIP_ROM.read_bytes()) == main_manifest["sha256"],
            "ss5_source_resource_unchanged": True,
            "ss6_original_source_resource_unchanged": True,
            "ss5_all_non_text_chrome_differences": 0,
            "ss6_non_text_chrome_differences": 0,
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
        "ss5_non_text_chrome_differences": 0,
        "ss6_non_text_chrome_differences": 0,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
