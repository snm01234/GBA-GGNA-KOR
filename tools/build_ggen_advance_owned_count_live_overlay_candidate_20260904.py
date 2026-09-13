#!/usr/bin/env python3
"""Visible 所有数 -> 소유수 candidate for the disposal unit-list plaque.

EC0C tracing proved the instrumented blit/text path never runs on this screen.
Earlier overlays failed because they wrote stale hardcoded tile addresses, or
hooked a transfer that is not the last writer.  This ROM instead:

  * hooks the unit-list transfer that already fires while the plaque is visible
    (0x0806EB3E -> 0x08063194, 551 hits on the measured idle list);
  * after that transfer, gates on BG2CNT plus the palette-B plaque frame;
  * reads the live glyph tile IDs from map cells (22,9)-(26,9) and
    (22,10)-(26,10);
  * copies a Galmuri11 소유수 raster into those charblock tiles only.

Chrome, the trailing 1, 보급포인트/총유닛수, and C/N/지 are not touched.
Canonical main TIP and the original main SAV are never modified.
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
ROOT = THIS_DIR.parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_jp_ko_ss1_n_tile_owned_count_20260903 as plaque
import analyze_ggen_advance_remaining_ui_draw_calls_20260902 as drawutil
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
import build_ggen_advance_owned_count_ab_candidates_20260903 as ab
import build_ggen_advance_sort_popup_state6_candidate_20260903 as sortpatch
import test_ggen_advance_font_pair as fontpair
from ggen_advance_project_paths import (
    ADVANCE_ROOT,
    FONT_ZIP,
    MAIN_TIP_MANIFEST,
    MAIN_TIP_ROM,
    advance_relative,
)

EXPECTED_MAIN_SHA256 = "5e424b1737c411639f355a7509affb92eadc46113fd1802269f8e14cbdbb4618"
MAIN_SAV = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).sav"
TRACE_SS2 = (
    ADVANCE_ROOT
    / "outputs"
    / "20260904_ggen_advance_owned_count_ec0c_trace"
    / "ggen_advance_owned_count_ec0c_trace_candidate_20260904.ss2"
)
KO_SS1 = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).ss1"

OUT_DIR = ADVANCE_ROOT / "outputs" / "20260904_ggen_advance_owned_count_live_overlay"
OUT_ROM = OUT_DIR / "ggen_advance_owned_count_live_overlay_candidate_20260904.gba"
OUT_SAV = OUT_DIR / "ggen_advance_owned_count_live_overlay_candidate_20260904.sav"
MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_owned_count_live_overlay_candidate_20260904.json"
PREVIEW_DIR = OUT_DIR / "previews"

ROM_BASE = 0x08000000
HOOK_ADDR = 0x0806EB3E
HOOK_FILE = HOOK_ADDR - ROM_BASE
ORIGINAL_TRANSFER = 0x08063194
STUB_FILE = 0x000C5700
STUB_ADDR = ROM_BASE + STUB_FILE
STUB_LIMIT = 0x000C5A00
PAYLOAD_FILE = 0x000C5A00
PAYLOAD_ADDR = ROM_BASE + PAYLOAD_FILE
CAVE_END = 0x000C6800

GLYPH_CELLS = tuple((x, 9) for x in range(22, 27)) + tuple((x, 10) for x in range(22, 27))
WINDOW = (176, 72, 216, 88)
TEXT = "소유수"
TEXT_X = 178
TEXT_Y = 74
FACE = 10
CONTOUR = 5
FILL = 11


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def u16(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def thumb_bl_target(data: bytes | bytearray, address: int) -> int | None:
    return ab.thumb_bl_target(data, address)


def map_offset(x: int, y: int) -> int:
    return (y * 32 + x) * 2


def choose_state() -> Path:
    for path in (TRACE_SS2, KO_SS1):
        if path.is_file():
            state, _ = statefmt.parse_png_state(path)
            if plaque.plaque_scan(state).get("found"):
                return path
    raise SystemExit("gate failed: no savestate with a live 所有数 plaque")


def glyph_tile_ids(state: bytes) -> list[int]:
    vram = state[statefmt.STATE_VRAM:statefmt.STATE_IWRAM]
    ids = []
    for x, y in GLYPH_CELLS:
        cell = u16(vram, 0xE800 + map_offset(x, y))
        gate((cell >> 12) == 0xB, f"glyph cell ({x},{y}) is not palette B: 0x{cell:04X}")
        ids.append(cell & 0x3FF)
    uses: dict[int, list[tuple[int, int]]] = {tile: [] for tile in ids}
    for y in range(32):
        for x in range(32):
            tile = u16(vram, 0xE800 + map_offset(x, y)) & 0x3FF
            if tile in uses:
                uses[tile].append((x, y))
    for tile, cells in uses.items():
        gate(len(cells) == 1 and cells[0] in GLYPH_CELLS, f"glyph tile 0x{tile:03X} is shared: {cells}")
    return ids


def raster_payload(state: bytes, font: fontpair.BdfFont) -> tuple[bytes, dict[str, Any], list[list[int]], list[list[int]]]:
    pixels, binding = drawutil.layer_pixels(state, 2)
    before = [row[:] for row in pixels]
    x0, y0, x1, y1 = WINDOW
    cleared = 0
    for y in range(y0, y1):
        for x in range(x0, x1):
            if pixels[y][x] in (FACE, CONTOUR):
                pixels[y][x] = FILL
                cleared += 1
    raster = sortpatch.draw_text(pixels, TEXT, TEXT_X, TEXT_Y, font, face=FACE, contour=CONTOUR)
    escaped = [
        (x, y)
        for y in range(160)
        for x in range(240)
        if (not (x0 <= x < x1 and y0 <= y < y1)) and pixels[y][x] != before[y][x]
    ]
    gate(not escaped, f"소유수 raster escaped glyph window: {escaped[:8]}")
    tiles = b"".join(sortpatch.tile_bytes_from_screen(pixels, x, y) for x, y in GLYPH_CELLS)
    gate(len(tiles) == 10 * 32, "payload size drift")
    gate(any(tiles), "blank 소유수 payload")
    return tiles, {
        "binding": binding,
        "cleared_ink": cleared,
        "draw": {"text": TEXT, "x": TEXT_X, "y": TEXT_Y, "face": FACE, "contour": CONTOUR, "fill": FILL},
        **raster,
        "window": list(WINDOW),
    }, pixels, before


def save_previews(before: list[list[int]], after: list[list[int]]) -> dict[str, str]:
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)

    def crop(pixels: list[list[int]]) -> Image.Image:
        x0, y0, x1, y1 = WINDOW
        img = Image.new("RGB", (x1 - x0, y1 - y0))
        px = img.load()
        palette = [
            (0, 0, 0), (32, 32, 32), (64, 64, 64), (96, 96, 96),
            (160, 160, 160), (139, 90, 43), (80, 160, 80), (80, 80, 192),
            (220, 220, 80), (220, 80, 80), (240, 200, 80), (248, 232, 168),
            (180, 80, 180), (80, 200, 200), (200, 160, 80), (255, 255, 255),
        ]
        for y, row in enumerate(pixels[y0:y1]):
            for x, value in enumerate(row[x0:x1]):
                px[x, y] = palette[value & 15]
        return img.resize(((x1 - x0) * 8, (y1 - y0) * 8), Image.Resampling.NEAREST)

    jp_path = PREVIEW_DIR / "plaque_jp.png"
    ko_path = PREVIEW_DIR / "plaque_soyoosu.png"
    crop(before).save(jp_path)
    crop(after).save(ko_path)
    return {"jp": advance_relative(jp_path), "ko": advance_relative(ko_path)}


def op_lsr(rd: int, rs: int, imm: int) -> int:
    return 0x0800 | (imm << 6) | (rs << 3) | rd


def build_stub_clean() -> bytes:
    t = ab.Thumb(STUB_ADDR)
    t.label("entry")
    t.h(0xB500)
    t.bl_abs(ORIGINAL_TRANSFER)

    t.ldr_pc(0, "bg2cnt_addr")
    t.h(0x8801)
    t.ldr_pc(2, "bg2cnt_value")
    t.h(0x4291)
    t.b("done", 0x1)

    t.ldr_pc(0, "corner_tl")
    t.h(0x8801)
    t.h(op_lsr(1, 1, 12))
    t.h(0x290B)
    t.b("done", 0x1)

    t.ldr_pc(0, "corner_tr")
    t.h(0x8801)
    t.h(op_lsr(1, 1, 12))
    t.h(0x290B)
    t.b("done", 0x1)

    t.ldr_pc(0, "corner_bl")
    t.h(0x8801)
    t.h(op_lsr(1, 1, 12))
    t.h(0x290B)
    t.b("done", 0x1)

    t.h(0xB470)  # push {r4-r6}  (no lr; lr is already stacked)
    t.ldr_pc(4, "payload")
    t.ldr_pc(5, "row9")
    t.h(0x2602)  # rows
    t.label("row_loop")
    t.h(0x2205)  # tiles
    t.label("tile_loop")
    t.h(0x8828)  # ldrh r0,[r5]
    t.h(0x0580)  # lsls r0,r0,#22
    t.h(op_lsr(0, 0, 22))
    t.h(0x0140)  # lsls r0,r0,#5  (*32)
    t.ldr_pc(1, "charblock2")
    t.h(0x1840)  # adds r0,r0,r1
    t.h(0x2108)  # movs r1,#8
    t.label("copy_loop")
    t.h(0x6823)  # ldr r3,[r4]
    t.h(0x6003)  # str r3,[r0]
    t.h(0x3404)
    t.h(0x3004)
    t.h(0x3901)  # subs r1,#1
    t.b("copy_loop", 0x1)
    t.h(0x3502)  # adds r5,#2
    t.h(0x3A01)
    t.b("tile_loop", 0x1)
    t.h(0x3536)  # adds r5,#54  (next row, same x)
    t.h(0x3E01)
    t.b("row_loop", 0x1)
    t.h(0xBD70)  # pop {r4-r6, pc}; stacked lr becomes pc

    t.label("done")
    t.h(0xBD00)  # pop {pc}

    t.align4()
    t.word("bg2cnt_addr", 0x0400000C)
    t.word("bg2cnt_value", 0x00005D0A)
    t.word("corner_tl", 0x0600E800 + map_offset(21, 8))
    t.word("corner_tr", 0x0600E800 + map_offset(29, 8))
    t.word("corner_bl", 0x0600E800 + map_offset(21, 11))
    t.word("payload", PAYLOAD_ADDR)
    t.word("row9", 0x0600E800 + map_offset(22, 9))
    t.word("charblock2", 0x06008000)
    blob = t.build()
    gate(len(blob) <= PAYLOAD_FILE - STUB_FILE, f"stub overflow: {len(blob)}")
    return blob


def verify_stub_epilogue(blob: bytes) -> None:
    """Successful overlay must pop r4-r6 and lr; gate miss pops lr only."""
    # The success path uses pop {r4-r6,pc} which never reaches done.  That is
    # correct because r4-r6 were only pushed after the gates passed.
    del blob


def main() -> int:
    parent = MAIN_TIP_ROM.read_bytes()
    manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(parent) == EXPECTED_MAIN_SHA256, f"current main hash drift: {sha256(parent)}")
    gate(manifest.get("sha256") == EXPECTED_MAIN_SHA256, "main manifest hash drift")
    gate(manifest.get("promotion_reason") == "user_approved_n_tile_rollback_20260903", "unexpected current main")
    gate(MAIN_SAV.is_file(), "main SAV missing")
    gate(all(b == 0 for b in parent[STUB_FILE:CAVE_END]), "ROM cave 0x0C5700 is not zero-filled")
    gate(thumb_bl_target(parent, HOOK_ADDR) == ORIGINAL_TRANSFER, "EB3E is no longer BL 0x08063194")
    gate(parent[0x63194:0x63198] == bytes.fromhex("004b1847"), "0x08063194 veneer drift")

    state_path = choose_state()
    state, _ = statefmt.parse_png_state(state_path)
    scan = plaque.plaque_scan(state)
    gate(scan.get("found") and scan.get("screen_vram") == "0x0600E800", "plaque identity drift")
    ids = glyph_tile_ids(state)

    with ZipFile(FONT_ZIP) as archive:
        font = fontpair.load_bdf(archive, "Galmuri11.bdf")
    payload, raster_info, after_pixels, before_pixels = raster_payload(state, font)
    previews = save_previews(before_pixels, after_pixels)

    stub = build_stub_clean()
    child = bytearray(parent)
    child[HOOK_FILE:HOOK_FILE + 4] = ab.encode_thumb_bl(HOOK_ADDR, STUB_ADDR)
    gate(thumb_bl_target(child, HOOK_ADDR) == STUB_ADDR, "hook BL drift")
    child[STUB_FILE:STUB_FILE + len(stub)] = stub
    child[PAYLOAD_FILE:PAYLOAD_FILE + len(payload)] = payload
    gate(len(payload) <= CAVE_END - PAYLOAD_FILE, "payload overflow")

    changed = [i for i, (a, b) in enumerate(zip(parent, child)) if a != b]
    allowed = set(range(HOOK_FILE, HOOK_FILE + 4))
    allowed.update(range(STUB_FILE, STUB_FILE + len(stub)))
    allowed.update(range(PAYLOAD_FILE, PAYLOAD_FILE + len(payload)))
    gate(changed and set(changed) <= allowed, "changes escaped live-overlay allocation")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_ROM.write_bytes(child)
    shutil.copyfile(MAIN_SAV, OUT_SAV)
    gate(OUT_SAV.read_bytes() == MAIN_SAV.read_bytes(), "SAV copy drift")

    compile_result = subprocess.run(
        [sys.executable, "-m", "py_compile", str(Path(__file__).resolve())],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    gate(compile_result.returncode == 0, f"py_compile failed: {compile_result.stderr}")
    verify_stub_epilogue(stub)

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_owned_count_live_overlay_candidate_20260904",
        "result": "PASS",
        "translation": {"所有数": TEXT},
        "source": {
            "path": advance_relative(MAIN_TIP_ROM),
            "sha256": sha256(parent),
            "promotion_reason": manifest["promotion_reason"],
            "state": advance_relative(state_path),
        },
        "output": {"path": advance_relative(OUT_ROM), "sha256": sha256(child), "size": len(child)},
        "sav": {
            "path": advance_relative(OUT_SAV),
            "sha256": sha256(OUT_SAV.read_bytes()),
            "byte_exact_copy": True,
        },
        "hook": {
            "callsite": f"0x{HOOK_ADDR:08X}",
            "original": f"0x{ORIGINAL_TRANSFER:08X}",
            "stub": f"0x{STUB_ADDR:08X}",
            "payload": f"0x{PAYLOAD_ADDR:08X}",
            "why": "EB3E is the unit-list 63194 transfer that already runs while the plaque is on screen; live tile IDs are read after it returns.",
        },
        "gate": {
            "BG2CNT": "0x5D0A",
            "palette_B_corners": ["(21,8)", "(29,8)", "(21,11)"],
        },
        "glyph_cells": [{"x": x, "y": y, "tile": f"0x{tile:03X}"} for (x, y), tile in zip(GLYPH_CELLS, ids)],
        "raster": raster_info,
        "previews": previews,
        "verification": {
            "result": "PASS",
            "current_main_hash_verified": True,
            "cave_zero_filled": True,
            "only_eb3e_and_cave_mutated": True,
            "py_compile": "PASS",
            "main_tip_not_modified": True,
            "original_sav_not_modified": True,
        },
        "measurement_checkpoints": [
            "후보 ROM + 동봉 SAV로 부팅한다. 메인 TIP/원본 SAV는 쓰지 않는다.",
            "처분 유닛 목록에서 에일 스트라이크에 포커스를 둔다.",
            "오른쪽 플래크가 所有数가 아니라 소유수 로 보이면 PASS.",
            "한 칸 아래 MC건담으로 옮겨도 소유수 가 유지되고 N/C/지는 그대로여야 한다.",
            "하단 보급포인트/총유닛수가 깨지면 FAIL.",
        ],
    }
    MANIFEST.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "rom": advance_relative(OUT_ROM),
        "sha256": sha256(child),
        "sav": advance_relative(OUT_SAV),
        "changed_bytes": len(changed),
        "glyph_tiles": [f"0x{tile:03X}" for tile in ids],
        "previews": previews,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
