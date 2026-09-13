#!/usr/bin/env python3
"""Build a focused ss3-ss6 Korean UI candidate from the current main TIP.

Scope is intentionally limited to the four supplied runtime states:
  ss3: 搭載/降ろす/移動/変形 -> 탑재/내리기/이동/변형
  ss4: 移動タイプ/現在の所属 -> 이동타입/현재소속
  ss5: パイロット/ユニット/パーツ -> 파일럿/유닛/파츠
  ss6: 分解完了 -> 분해완료

ss1/ss2 are deliberately excluded.  Existing private develop-menu clones are
rebuilt in-place only inside the candidate ROM.  Native shared resources used
by ss3 are cloned into zero-filled expansion space and their direct consumers
are redirected.  The canonical main TIP is never modified.
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

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_develop_menu_buttons_state_20260901 as spr
import analyze_ggen_advance_develop_menu_buttons_images_20260901 as animutil
import analyze_ggen_advance_settings_suspend_ui as animrec
import build_ggen_advance_develop_menu_buttons_ko_image_20260901 as oldbuild
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
OUT_DIR = ADVANCE_ROOT / "outputs" / "20260902_ggen_advance_remaining_ui_ss3_ss6"
OUT_ROM = OUT_DIR / "ggen_advance_remaining_ui_ss3_ss6_candidate_20260902.gba"
OUT_SAV = OUT_DIR / "ggen_advance_remaining_ui_ss3_ss6_candidate_20260902.sav"
OUT_MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_remaining_ui_ss3_ss6_candidate_20260902.json"
MAIN_SAV = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).sav"

# Dedicated zero-filled graphics expansion blocks for the two still-native ss3 resources.
SS3_TEXT_CLONE = 0x012E0000
SS3_BUTTON_CLONE = 0x012E8000
BLOCK_SIZE = 0x8000


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def make_mask(text: str, font: fontpair.BdfFont, width: int, height: int) -> list[list[bool]]:
    mask, _ = paintops.make_text_mask(text, font, width, height, cell_width=12)
    return mask


def paint_cardinal(pixels: list[list[int]], mask: list[list[bool]], ink: int, contour: int) -> tuple[int, int]:
    return oldbuild.paint_mask_cardinal(pixels, mask, ink=ink, contour=contour)


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
) -> dict[str, Any]:
    x0, y0, x1, y1 = rect
    gate(0 <= x0 < x1 <= len(canvas[0]) and 0 <= y0 < y1 <= len(canvas), f"{text}: rect outside canvas {rect}")
    width, height = x1 - x0, y1 - y0
    gate(height == 16, f"{text}: expected 16px text strip, got {height}")
    before = [row[x0:x1] for row in canvas[y0:y1]]
    cleared = 0
    for yy in range(y0, y1):
        for xx in range(x0, x1):
            if canvas[yy][xx] in clear_values:
                canvas[yy][xx] = fill
                cleared += 1
    local = [row[x0:x1] for row in canvas[y0:y1]]
    mask = make_mask(text, font, width, height)
    ink_count, contour_count = paint_cardinal(local, mask, ink, contour)
    for yy in range(height):
        canvas[y0 + yy][x0:x1] = local[yy]
    gate(ink_count > 0 and contour_count > 0, f"{text}: Korean raster empty")
    return {
        "text": text,
        "rect": list(rect),
        "fill": fill,
        "ink": ink,
        "contour": contour,
        "clear_values": list(clear_values),
        "cleared_pixels": cleared,
        "ink_pixels": ink_count,
        "contour_pixels": contour_count,
        "before_sha256": sha256(bytes(v for row in before for v in row)),
        "after_sha256": sha256(bytes(v for row in canvas[y0:y1] for v in row[x0:x1])),
    }


def resource_allocation_limit(addr: int) -> int:
    off = addr - ROM_BASE
    if addr in (0x092C0000, 0x092C8000, 0x092D8000):
        return ((off // BLOCK_SIZE) + 1) * BLOCK_SIZE
    raise ValueError(f"no allocation limit for 0x{addr:08X}")


def rebuild_resource(
    rom: bytes | bytearray,
    addr: int,
    patches: list[dict[str, Any]],
    font: fontpair.BdfFont,
) -> tuple[bytes, dict[str, Any]]:
    data = bytes(rom)
    header = spr.parse_resource_header(data, addr)
    original = data[header["offset"]:header["offset"] + header["resource_bytes"]]
    graphics = header["graphics"]
    palettes = header["palettes"]
    original_tiles = len(graphics) // 32
    _gr_rel, records = animrec.animation_records(data, addr)

    existing: dict[bytes, int] = {}
    for tile_id in range(original_tiles):
        existing.setdefault(graphics[tile_id * 32:(tile_id + 1) * 32], tile_id)
    private: dict[bytes, int] = {}
    private_payloads: list[bytes] = []
    lookup_writes: dict[int, int] = {}
    reports: list[dict[str, Any]] = []

    for spec in patches:
        anim = int(spec["anim"])
        parsed, ids, lookup_file = animutil.parse_anim(records, anim)
        objects = parsed["objects"]
        indices = list(range(len(objects)))
        canvas = spr.stitch(graphics, parsed, ids, indices)
        min_x = min(int(o["x"]) for o in objects)
        min_y = min(int(o["y"]) for o in objects)
        strip_reports = []
        for rep in spec["repaints"]:
            strip_reports.append(repaint_rect(canvas, tuple(rep["rect"]), rep["text"], font,
                                                fill=rep["fill"], ink=rep["ink"], contour=rep["contour"],
                                                clear_values=tuple(rep["clear_values"])))

        cursor = 0
        changed_lookup = 0
        for obj in objects:
            wt = int(obj["size_px"][0]) // 8
            ht = int(obj["size_px"][1]) // 8
            count = wt * ht
            src_ids = ids[cursor:cursor + count]
            for ty in range(ht):
                for tx in range(wt):
                    pos = ty * wt + tx
                    old_id = int(src_ids[pos])
                    ox = int(obj["x"]) - min_x + tx * 8
                    oy = int(obj["y"]) - min_y + ty * 8
                    tile = [canvas[oy + yy][ox:ox + 8] for yy in range(8)]
                    payload = tileops.encode_tile(tile)
                    old_payload = graphics[old_id * 32:(old_id + 1) * 32]
                    if payload == old_payload:
                        new_id = old_id
                    elif payload in existing:
                        new_id = existing[payload]
                    elif payload in private:
                        new_id = private[payload]
                    else:
                        new_id = original_tiles + len(private_payloads)
                        gate(new_id <= 0xFFFF, f"0x{addr:08X}: source id overflow")
                        private[payload] = new_id
                        private_payloads.append(payload)
                    if new_id != old_id:
                        rel = (lookup_file - header["offset"]) + (cursor + pos) * 2
                        previous = lookup_writes.get(rel)
                        gate(previous is None or previous == new_id, f"0x{addr:08X}: conflicting lookup at 0x{rel:X}")
                        lookup_writes[rel] = new_id
                        changed_lookup += 1
            cursor += count
        reports.append({"animation": anim, "changed_lookup_entries": changed_lookup, "repaints": strip_reports})

    new_graphics = graphics + b"".join(private_payloads)
    new_palette_rel = header["graphics_rel"] + len(new_graphics)
    clone = bytearray(new_palette_rel + len(palettes))
    clone[:header["graphics_rel"]] = original[:header["graphics_rel"]]
    struct.pack_into("<I", clone, 0x0C, new_palette_rel)
    for rel, new_id in lookup_writes.items():
        struct.pack_into("<H", clone, rel, new_id)
    clone[header["graphics_rel"]:new_palette_rel] = new_graphics
    clone[new_palette_rel:] = palettes
    gate(new_graphics[:len(graphics)] == graphics, f"0x{addr:08X}: original source tiles changed")
    gate(clone[new_palette_rel:] == palettes, f"0x{addr:08X}: palette changed")
    return bytes(clone), {
        "resource": f"0x{addr:08X}",
        "original_resource_bytes": header["resource_bytes"],
        "rebuilt_resource_bytes": len(clone),
        "original_tiles": original_tiles,
        "private_tiles_appended": len(private_payloads),
        "animations": reports,
    }


def pointer_hits(data: bytes | bytearray, addr: int) -> list[int]:
    pat = struct.pack("<I", addr)
    out: list[int] = []
    start = 0
    while True:
        hit = bytes(data[:0x01000000]).find(pat, start)
        if hit < 0:
            return out
        out.append(hit)
        start = hit + 1


def changed_ranges(offsets: list[int]) -> list[list[str]]:
    if not offsets:
        return []
    result: list[list[str]] = []
    start = prev = offsets[0]
    for off in offsets[1:]:
        if off != prev + 1:
            result.append([f"0x{start:08X}", f"0x{prev + 1:08X}"])
            start = off
        prev = off
    result.append([f"0x{start:08X}", f"0x{prev + 1:08X}"])
    return result


def run_regression() -> dict[str, str]:
    tests = [
        ADVANCE_ROOT / "tools" / "test_ggen_advance_unified_pipeline.py",
        ADVANCE_ROOT / "tools" / "test_ggen_advance_intermission_development_fix.py",
    ]
    result: dict[str, str] = {}
    for test in tests:
        cp = subprocess.run([sys.executable, str(test)], cwd=str(ADVANCE_ROOT), capture_output=True, text=True)
        gate(cp.returncode == 0, f"{test.name} failed: {cp.stderr[-600:]}")
        result[test.name] = "PASS"
    return result


def main() -> int:
    parent = MAIN_TIP_ROM.read_bytes()
    main_manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(parent) == main_manifest["sha256"], "main TIP / manifest hash mismatch")
    gate(MAIN_SAV.is_file(), "main TIP SAV missing")
    candidate = bytearray(parent)
    allowed: set[int] = set()
    reports: list[dict[str, Any]] = []

    with ZipFile(FONT_ZIP) as archive:
        font = fontpair.load_bdf(archive, "Galmuri11.bdf")

    # ss3 base/static label resource.  Four native yellow 64x16 labels.
    ss3_text_patches = []
    for anim, ko in [(0, "탑재"), (1, "내리기"), (2, "이동"), (3, "변형")]:
        ss3_text_patches.append({
            "anim": anim,
            "repaints": [{"rect": [4, 0, 52, 16], "text": ko, "fill": 11, "ink": 10, "contour": 5, "clear_values": [10, 5]}],
        })
    clone, report = rebuild_resource(parent, 0x08C3F130, ss3_text_patches, font)
    gate(SS3_TEXT_CLONE + len(clone) <= SS3_TEXT_CLONE + BLOCK_SIZE, "ss3 text clone exceeds block")
    gate(all(v == 0 for v in parent[SS3_TEXT_CLONE:SS3_TEXT_CLONE + len(clone)]), "ss3 text clone area not zero-filled")
    candidate[SS3_TEXT_CLONE:SS3_TEXT_CLONE + len(clone)] = clone
    allowed.update(range(SS3_TEXT_CLONE, SS3_TEXT_CLONE + len(clone)))
    hits = pointer_hits(parent, 0x08C3F130)
    gate(hits, "no consumers for 0x08C3F130")
    for hit in hits:
        struct.pack_into("<I", candidate, hit, ROM_BASE + SS3_TEXT_CLONE)
        allowed.update(range(hit, hit + 4))
    report.update({"method": "private clone + direct consumer redirect", "clone": f"0x{ROM_BASE + SS3_TEXT_CLONE:08X}", "redirected_refs": [f"0x{x:08X}" for x in hits]})
    reports.append(report)

    # ss3 selectable/focus label resource. anim0/1/2 normal; anim3/4/5 focus.
    ss3_button_patches = []
    for anim, ko in [(0, "탑재"), (1, "내리기"), (2, "이동")]:
        ss3_button_patches.append({"anim": anim, "repaints": [{"rect": [18, 0, 70, 16], "text": ko, "fill": 11, "ink": 10, "contour": 5, "clear_values": [10, 5]}]})
    for anim, ko in [(3, "탑재"), (4, "내리기"), (5, "이동")]:
        ss3_button_patches.append({"anim": anim, "repaints": [{"rect": [18, 0, 70, 16], "text": ko, "fill": 10, "ink": 12, "contour": 4, "clear_values": [12, 4]}]})
    clone, report = rebuild_resource(parent, 0x08C59744, ss3_button_patches, font)
    gate(SS3_BUTTON_CLONE + len(clone) <= SS3_BUTTON_CLONE + BLOCK_SIZE, "ss3 button clone exceeds block")
    gate(all(v == 0 for v in parent[SS3_BUTTON_CLONE:SS3_BUTTON_CLONE + len(clone)]), "ss3 button clone area not zero-filled")
    candidate[SS3_BUTTON_CLONE:SS3_BUTTON_CLONE + len(clone)] = clone
    allowed.update(range(SS3_BUTTON_CLONE, SS3_BUTTON_CLONE + len(clone)))
    hits = pointer_hits(parent, 0x08C59744)
    gate(hits, "no consumers for 0x08C59744")
    for hit in hits:
        struct.pack_into("<I", candidate, hit, ROM_BASE + SS3_BUTTON_CLONE)
        allowed.update(range(hit, hit + 4))
    report.update({"method": "private clone + direct consumer redirect", "clone": f"0x{ROM_BASE + SS3_BUTTON_CLONE:08X}", "redirected_refs": [f"0x{x:08X}" for x in hits]})
    reports.append(report)

    # ss4: right-side panel, screen origin is canvas (0,80) for the live state.
    ss4_patches = [{
        "anim": 3,
        "repaints": [
            {"rect": [128, 24, 200, 40], "text": "이동타입", "fill": 11, "ink": 10, "contour": 5, "clear_values": [10, 5]},
            {"rect": [128, 40, 200, 56], "text": "현재소속", "fill": 11, "ink": 10, "contour": 5, "clear_values": [10, 5]},
        ],
    }]
    rebuilt, report = rebuild_resource(candidate, 0x092D8000, ss4_patches, font)
    off = 0x092D8000 - ROM_BASE
    limit = resource_allocation_limit(0x092D8000)
    gate(off + len(rebuilt) <= limit, "ss4 private clone growth exceeds allocation")
    candidate[off:off + len(rebuilt)] = rebuilt
    allowed.update(range(off, off + len(rebuilt)))
    report.update({"method": "rebuild existing private clone in candidate only", "allocation": [f"0x{off:08X}", f"0x{limit:08X}"]})
    reports.append(report)

    # ss5: top two labels live in anim6 panel; bottom focused パーツ is anim3.
    ss5_patches = [
        {
            "anim": 6,
            "repaints": [
                {"rect": [8, 80, 72, 96], "text": "파일럿", "fill": 11, "ink": 10, "contour": 2, "clear_values": [10, 2]},
                {"rect": [8, 96, 72, 112], "text": "유닛", "fill": 11, "ink": 10, "contour": 2, "clear_values": [10, 2]},
            ],
        },
        {
            "anim": 3,
            "repaints": [
                {"rect": [4, 0, 44, 16], "text": "파츠", "fill": 10, "ink": 12, "contour": 1, "clear_values": [12, 1]},
            ],
        },
    ]
    rebuilt, report = rebuild_resource(candidate, 0x092C0000, ss5_patches, font)
    off = 0x092C0000 - ROM_BASE
    limit = resource_allocation_limit(0x092C0000)
    gate(off + len(rebuilt) <= limit, "ss5 private clone growth exceeds allocation")
    candidate[off:off + len(rebuilt)] = rebuilt
    allowed.update(range(off, off + len(rebuilt)))
    report.update({"method": "rebuild existing private clone in candidate only", "allocation": [f"0x{off:08X}", f"0x{limit:08X}"]})
    reports.append(report)

    # ss6: remove native contour in the exact 64x16 central text strip, then draw Korean.
    ss6_patches = [{
        "anim": 6,
        "repaints": [
            {"rect": [4, 0, 60, 16], "text": "분해완료", "fill": 10, "ink": 10, "contour": 5, "clear_values": [5]},
        ],
    }]
    rebuilt, report = rebuild_resource(candidate, 0x092C8000, ss6_patches, font)
    off = 0x092C8000 - ROM_BASE
    limit = resource_allocation_limit(0x092C8000)
    gate(off + len(rebuilt) <= limit, "ss6 private clone growth exceeds allocation")
    candidate[off:off + len(rebuilt)] = rebuilt
    allowed.update(range(off, off + len(rebuilt)))
    report.update({"method": "rebuild existing private clone in candidate only", "allocation": [f"0x{off:08X}", f"0x{limit:08X}"]})
    reports.append(report)

    changed = [i for i, (a, b) in enumerate(zip(parent, candidate)) if a != b]
    escaped = [i for i in changed if i not in allowed]
    gate(not escaped, f"changes escaped allowed ranges: {escaped[:16]}")
    gate(bytes(candidate[:0x01000000]) != parent[:0x01000000], "expected ss3 consumer redirects missing")
    # Native source resources themselves remain byte-exact.
    for addr in (0x08C3F130, 0x08C59744):
        h = spr.parse_resource_header(parent, addr)
        gate(candidate[h["offset"]:h["offset"] + h["resource_bytes"]] == parent[h["offset"]:h["offset"] + h["resource_bytes"]], f"native resource 0x{addr:08X} modified")

    compile_cp = subprocess.run([sys.executable, "-m", "py_compile", str(Path(__file__))], cwd=str(ADVANCE_ROOT), capture_output=True, text=True)
    gate(compile_cp.returncode == 0, f"py_compile failed: {compile_cp.stderr}")
    regression = run_regression()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_ROM.write_bytes(candidate)
    shutil.copy2(MAIN_SAV, OUT_SAV)
    output = bytes(candidate)
    manifest = {
        "schema_version": 1,
        "kind": "ggen_advance_remaining_ui_ss3_ss6_candidate_20260902",
        "result": "PASS",
        "scope": {
            "included_states": [3, 4, 5, 6],
            "excluded_states": [1, 2],
            "translations": {
                "ss3": {"搭載": "탑재", "降ろす": "내리기", "移動": "이동", "変形": "변형"},
                "ss4": {"移動タイプ": "이동타입", "現在の所属": "현재소속"},
                "ss5": {"パイロット": "파일럿", "ユニット": "유닛", "パーツ": "파츠"},
                "ss6": {"分解完了": "분해완료"},
            },
        },
        "source": {
            "parent": advance_relative(MAIN_TIP_ROM),
            "parent_sha256": sha256(parent),
            "main_tip_manifest": advance_relative(MAIN_TIP_MANIFEST),
        },
        "patch": {"resources": reports, "font": "Galmuri11.bdf native 12x12"},
        "output": {
            "rom": advance_relative(OUT_ROM),
            "rom_sha256": sha256(output),
            "size": len(output),
            "sav": advance_relative(OUT_SAV),
            "sav_sha256": sha256(OUT_SAV.read_bytes()),
            "changed_bytes": len(changed),
            "changed_ranges": changed_ranges(changed),
        },
        "verification": {
            "result": "PASS",
            "canonical_main_tip_modified": False,
            "native_ss3_resources_byte_exact": True,
            "ss1_ss2_excluded": True,
            "changes_inside_declared_ranges_only": True,
            "py_compile": "PASS",
            "regression": regression,
        },
    }
    OUT_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "rom": str(OUT_ROM),
        "rom_sha256": sha256(output),
        "sav": str(OUT_SAV),
        "manifest": str(OUT_MANIFEST),
        "changed_bytes": len(changed),
        "resources": [{"resource": r["resource"], "private_tiles_appended": r["private_tiles_appended"]} for r in reports],
    }, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
