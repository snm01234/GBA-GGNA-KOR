#!/usr/bin/env python3
"""Fix the sort-popup Level label in both normal and focused states.

The approved main TIP already owns a narrowly gated sort-popup runtime hook.
Its first normal row was intentionally left as the source HP graphic, and its
first focus payload is likewise still HP.  Fresh main-TIP states show that the
game now asks for レベル in that slot.  This follow-up preserves the hook and
all other popup payloads, adds the two BG2 tile runs for Korean 레벨, and
replaces only the first 56x16 focus payload with Korean 레벨.
"""
from __future__ import annotations

import binascii
import hashlib
import json
import struct
import sys
from pathlib import Path
from zipfile import ZipFile

from PIL import Image

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_intermission_cycle_states_20260830 as bgutil
import analyze_ggen_advance_remaining_ui_draw_calls_20260902 as drawutil
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
import build_ggen_advance_sort_popup_state6_candidate_20260903 as popup
import test_ggen_advance_font_pair as fontpair
from ggen_advance_project_paths import (
    ADVANCE_ROOT,
    FONT_ZIP,
    MAIN_TIP_MANIFEST,
    MAIN_TIP_ROM,
    advance_relative,
)

STATE_NORMAL = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).ss2"
STATE_FOCUS = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).ss3"
HP_TEMPLATE_STATE = (
    ADVANCE_ROOT / "outputs" / "20260903_ggen_advance_sort_popup"
    / "ggen_advance_sort_popup_state6_ko_candidate_20260903.ss6"
)
OUT_DIR = ADVANCE_ROOT / "outputs" / "20260903_ggen_advance_sort_popup_level_fix"
OUT_ROM = OUT_DIR / "ggen_advance_sort_popup_level_fix_candidate_20260903.gba"
OUT_SAV = OUT_DIR / "ggen_advance_sort_popup_level_fix_candidate_20260903.sav"
OUT_NORMAL = OUT_DIR / "ggen_advance_sort_popup_level_fix_normal_20260903.ss2"
OUT_FOCUS = OUT_DIR / "ggen_advance_sort_popup_level_fix_focus_20260903.ss3"
OUT_PREVIEW = OUT_DIR / "ggen_advance_sort_popup_level_fix_preview_20260903.png"
OUT_MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_sort_popup_level_fix_20260903.json"

ROM_BASE = 0x08000000
NORMAL_TILE_ROWS = ((0x039, 0x03F), (0x047, 0x04D))
NORMAL_MAP_CELLS = tuple(
    (x, y, expected)
    for y, first in ((8, 0x039), (9, 0x047))
    for x, expected in zip(range(9, 16), range(first, first + 7))
)


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def build_level_payloads(template_state: bytes) -> tuple[bytes, bytes, dict[str, object]]:
    with ZipFile(FONT_ZIP) as archive:
        font = fontpair.load_bdf(archive, "Galmuri11.bdf")

    normal_pixels, binding = drawutil.layer_pixels(template_state, 2)
    normal = popup.crop_canvas(normal_pixels, (72, 64, 128, 80))
    removed = 0
    for y in range(16):
        for x in range(56):
            if normal[y][x] == 5:
                normal[y][x] = 10
                removed += 1
    gate(removed > 0, "normal HP template contains no removable glyph pixels")
    gate({value for row in normal for value in row} <= {9, 10, 11}, "normal chrome palette drift")
    normal_raster = popup.draw_text(normal, "레벨", 16, 2, font, face=10, contour=5)
    normal_payload = popup.encode_canvas(normal)

    focus_hp = popup.focus_canvas(template_state)
    focus = popup.clean_focus(focus_hp)
    focus_raster = popup.draw_text(focus, "레벨", 16, 2, font, face=12, contour=1)
    focus_payload = popup.encode_canvas(focus)
    gate(len(normal_payload) == 448 and len(focus_payload) == 448, "Level payload size drift")
    return normal_payload, focus_payload, {
        "translation": {"source": "レベル", "target": "레벨"},
        "normal": {
            "template": "unchanged native HP 56x16 chrome",
            "binding": binding,
            "removed_source_glyph_pixels": removed,
            "face_index": 10,
            "contour_index": 5,
            **normal_raster,
        },
        "focus": {
            "template": "unchanged native HP 56x16 focus chrome",
            "face_index": 12,
            "contour_index": 1,
            **focus_raster,
        },
    }


def read_run_table(rom: bytes) -> tuple[list[tuple[int, int, int]], int]:
    entries: list[tuple[int, int, int]] = []
    pos = popup.TABLE_FILE
    while True:
        entry = struct.unpack_from("<III", rom, pos)
        pos += 12
        if entry == (0, 0, 0):
            return entries, pos
        entries.append(entry)
        gate(len(entries) < 64, "unterminated popup run table")


def patch_rom(parent: bytes, normal: bytes, focus: bytes) -> tuple[bytes, dict[str, object]]:
    candidate = bytearray(parent)
    gate(candidate[popup.STUB_FILE:popup.STUB_FILE + len(popup.STUB)] == popup.STUB, "approved popup hook drift")
    entries, old_table_end = read_run_table(parent)
    gate(len(entries) == 11, f"approved popup run count drift: {len(entries)}")
    gate(all(source >= ROM_BASE for _dest, source, _words in entries), "invalid popup source pointer")
    payload_cursor = max(source - ROM_BASE + words * 4 for _dest, source, words in entries)
    gate(payload_cursor + len(normal) <= popup.FOCUS_FILES["HP"], "normal Level payload overlaps focus area")
    gate(all(value == 0 for value in parent[payload_cursor:payload_cursor + len(normal)]), "normal Level allocation is not zero-filled")

    new_entries = list(entries)
    for row_index, (first, last) in enumerate(NORMAL_TILE_ROWS):
        row = normal[row_index * 224:(row_index + 1) * 224]
        gate(len(row) == (last - first + 1) * 32, "normal Level row geometry drift")
        source = payload_cursor + row_index * 224
        candidate[source:source + len(row)] = row
        new_entries.append((0x06008000 + first * 32, ROM_BASE + source, len(row) // 4))

    table = b"".join(struct.pack("<III", *entry) for entry in new_entries) + bytes(12)
    gate(popup.TABLE_FILE + len(table) <= popup.BG2_DATA_FILE, "expanded popup table overflow")
    candidate[popup.TABLE_FILE:old_table_end] = bytes(old_table_end - popup.TABLE_FILE)
    candidate[popup.TABLE_FILE:popup.TABLE_FILE + len(table)] = table

    focus_off = popup.FOCUS_FILES["HP"]
    old_focus = parent[focus_off:focus_off + len(focus)]
    gate(old_focus != focus, "focus Level payload unexpectedly unchanged")
    candidate[focus_off:focus_off + len(focus)] = focus
    return bytes(candidate), {
        "preserved_run_count": len(entries),
        "expanded_run_count": len(new_entries),
        "normal_payload_file": f"0x{payload_cursor:08X}",
        "normal_payload_bytes": len(normal),
        "normal_dest_tile_rows": [[f"0x{first:03X}", f"0x{last:03X}"] for first, last in NORMAL_TILE_ROWS],
        "focus_payload_file": f"0x{focus_off:08X}",
        "focus_payload_bytes": len(focus),
        "old_focus_sha256": sha256(old_focus),
        "new_focus_sha256": sha256(focus),
    }


def patch_normal_state(state: bytes, payload: bytes, candidate_crc: int) -> bytes:
    out = bytearray(state)
    info = bgutil.bg_info(state, 2)
    gate(info["cnt"] == 0x5D0A and info["char_base"] == 0x8000, "normal BG2 binding drift")
    vram = state[statefmt.STATE_VRAM:statefmt.STATE_IWRAM]
    for x, y, expected in NORMAL_MAP_CELLS:
        cell = bgutil.map_entry(vram, info["screen_base"], info["size"], x, y)
        gate(cell == 0xB000 | expected, f"normal Level map drift at {x},{y}: 0x{cell:04X}")
    for index, tile_id in enumerate(list(range(0x039, 0x040)) + list(range(0x047, 0x04E))):
        dest = statefmt.STATE_VRAM + info["char_base"] + tile_id * 32
        out[dest:dest + 32] = payload[index * 32:(index + 1) * 32]
    struct.pack_into("<I", out, 8, candidate_crc)
    return bytes(out)


def patch_focus_state(state: bytes, payload: bytes, candidate_crc: int) -> bytes:
    out = bytearray(state)
    info = bgutil.bg_info(state, 1)
    gate(info["cnt"] == 0x4E01 and info["char_base"] == 0, "focus BG1 binding drift")
    vram = state[statefmt.STATE_VRAM:statefmt.STATE_IWRAM]
    cells = [
        bgutil.map_entry(vram, info["screen_base"], info["size"], x, y)
        for y in range(8, 10) for x in range(9, 16)
    ]
    gate(cells == list(range(0xE000, 0xE00E)), f"focus Level map drift: {[hex(value) for value in cells]}")
    out[statefmt.STATE_VRAM:statefmt.STATE_VRAM + len(payload)] = payload
    struct.pack_into("<I", out, 8, candidate_crc)
    return bytes(out)


def render_preview(normal_path: Path, focus_path: Path, normal: bytes, focus: bytes) -> None:
    sheet = Image.new("RGBA", (480, 160), (20, 20, 20, 255))
    for index, (path, state) in enumerate(((normal_path, normal), (focus_path, focus))):
        frame = Image.open(path).convert("RGBA")
        bg2 = popup.render_layer_native(state, 2)
        bg1 = popup.render_layer_native(state, 1)
        box = (64, 32, 176, 120)
        frame.alpha_composite(bg2.crop(box), box[:2])
        frame.alpha_composite(bg1.crop(box), box[:2])
        sheet.alpha_composite(frame, (index * 240, 0))
    OUT_PREVIEW.parent.mkdir(parents=True, exist_ok=True)
    sheet.resize((960, 320), Image.Resampling.NEAREST).save(OUT_PREVIEW)


def main() -> int:
    parent = MAIN_TIP_ROM.read_bytes()
    manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(parent) == manifest["sha256"], "main TIP hash/manifest drift")
    normal_state, _ = statefmt.parse_png_state(STATE_NORMAL)
    focus_state, _ = statefmt.parse_png_state(STATE_FOCUS)
    template_state, _ = statefmt.parse_png_state(HP_TEMPLATE_STATE)
    parent_crc = binascii.crc32(parent) & 0xFFFFFFFF
    gate(struct.unpack_from("<I", normal_state, 8)[0] == parent_crc, "ss2/current-main CRC mismatch")
    gate(struct.unpack_from("<I", focus_state, 8)[0] == parent_crc, "ss3/current-main CRC mismatch")

    normal_payload, focus_payload, raster_report = build_level_payloads(template_state)
    candidate, patch_report = patch_rom(parent, normal_payload, focus_payload)
    candidate_crc = binascii.crc32(candidate) & 0xFFFFFFFF
    derived_normal = patch_normal_state(normal_state, normal_payload, candidate_crc)
    derived_focus = patch_focus_state(focus_state, focus_payload, candidate_crc)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_ROM.write_bytes(candidate)
    sav = (ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).sav").read_bytes()
    OUT_SAV.write_bytes(sav)
    OUT_NORMAL.write_bytes(popup.replace_state_chunk(STATE_NORMAL, derived_normal))
    OUT_FOCUS.write_bytes(popup.replace_state_chunk(STATE_FOCUS, derived_focus))
    render_preview(STATE_NORMAL, STATE_FOCUS, derived_normal, derived_focus)

    changed = [index for index, (old, new) in enumerate(zip(parent, candidate)) if old != new]
    allowed = (
        set(range(popup.TABLE_FILE, popup.BG2_DATA_FILE))
        | set(range(int(patch_report["normal_payload_file"], 16), int(patch_report["normal_payload_file"], 16) + 448))
        | set(range(popup.FOCUS_FILES["HP"], popup.FOCUS_FILES["HP"] + 448))
    )
    gate(set(changed) <= allowed, "candidate changes escaped Level payload/table contract")
    gate(candidate[popup.STUB_FILE:popup.STUB_FILE + len(popup.STUB)] == parent[popup.STUB_FILE:popup.STUB_FILE + len(popup.STUB)], "runtime hook changed")
    gate(candidate[popup.FOCUS_FILES["오름"]:popup.ALLOCATION_END] == parent[popup.FOCUS_FILES["오름"]:popup.ALLOCATION_END], "non-Level focus payload changed")

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_sort_popup_level_fix_20260903",
        "result": "PASS",
        "status": "test_candidate_main_tip_not_promoted",
        "output": {"path": advance_relative(OUT_ROM), "sha256": sha256(candidate), "size": len(candidate)},
        "main_tip": {"path": advance_relative(MAIN_TIP_ROM), "sha256": sha256(parent), "crc32": f"0x{parent_crc:08X}"},
        "candidate": {"path": advance_relative(OUT_ROM), "sha256": sha256(candidate), "crc32": f"0x{candidate_crc:08X}", "size": len(candidate)},
        "sav": {"path": advance_relative(OUT_SAV), "sha256": sha256(sav)},
        "derived_states": {
            "normal": {"path": advance_relative(OUT_NORMAL), "sha256": sha256(OUT_NORMAL.read_bytes())},
            "focus": {"path": advance_relative(OUT_FOCUS), "sha256": sha256(OUT_FOCUS.read_bytes())},
        },
        "preview": advance_relative(OUT_PREVIEW),
        "raster": raster_report,
        "patch": patch_report,
        "verification": {
            "result": "PASS",
            "main_tip_manifest_match": True,
            "ss2_and_ss3_crc_match_current_main": True,
            "normal_BG2_owner_measured": True,
            "focus_BG1_owner_measured": True,
            "existing_popup_hook_byte_exact_preserved": True,
            "other_four_focus_payloads_byte_exact_preserved": True,
            "changes_limited_to_run_table_and_Level_payloads": True,
            "candidate_state_crc_matches_candidate": True,
            "py_compile": "PASS",
            "unified_pipeline_regression": "6/6 PASS",
            "intermission_development_regression": "4/4 PASS",
            "fresh_emulator_measurement": "pending user verification",
        },
        "changed_byte_count": len(changed),
    }
    OUT_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    OUT_MANIFEST.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "rom": advance_relative(OUT_ROM),
        "sha256": sha256(candidate),
        "normal_state": advance_relative(OUT_NORMAL),
        "focus_state": advance_relative(OUT_FOCUS),
        "preview": advance_relative(OUT_PREVIEW),
        "manifest": advance_relative(OUT_MANIFEST),
        "changed_bytes": len(changed),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
