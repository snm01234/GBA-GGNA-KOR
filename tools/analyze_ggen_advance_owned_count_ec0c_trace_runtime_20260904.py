#!/usr/bin/env python3
"""Analyze the 20260904 EC0C trace savestates for the 所有数 plaque.

Expected captures:
  ss1  first disposal unit-list screen
  ss2  Aile Strike Gundam focused
  ss3  focus moved one row down to MC Gundam
  (the user labeled the third capture as ss2; the folder has ss3)
"""
from __future__ import annotations

import binascii
import hashlib
import json
import struct
import sys
from pathlib import Path
from typing import Any

from PIL import Image

THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_intermission_cycle_states_20260830 as bgutil
import analyze_ggen_advance_jp_ko_ss1_n_tile_owned_count_20260903 as plaque
import analyze_ggen_advance_owned_count_ec0c_trace_state_20260904 as reader
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
import build_ggen_advance_owned_count_ec0c_trace_candidate_20260904 as trace
from ggen_advance_project_paths import MAIN_TIP_ROM, ORIGINAL_ROM, advance_relative

DIR = ROOT / "outputs" / "20260904_ggen_advance_owned_count_ec0c_trace"
STATES = [DIR / f"ggen_advance_owned_count_ec0c_trace_candidate_20260904.ss{i}" for i in (1, 2, 3)]
LABELS = ["ss1_first_list", "ss2_aile_focus", "ss3_mc_focus"]
OUT = ROOT / "analysis" / "ggen_advance_owned_count_ec0c_trace_runtime_20260904.json"
PREVIEW = DIR / "previews"
KO_BASELINE = ROOT / "SD Gundam GGeneration Advance (Korean).ss1"
EWRAM_BASE = 0x02000000
ROM_BASE = 0x08000000
TRACE_OFF = trace.TRACE_BASE - EWRAM_BASE
GLYPH_TILES = (0x0DD, 0x0DE, 0x0DF, 0x0E0, 0x0E1, 0x0E4, 0x0E5, 0x0E6, 0x0E7, 0x0E8)


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def u16(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def aligned_hits(blob: bytes, value: int) -> list[str]:
    hits = []
    needle = struct.pack("<I", value)
    start = 0
    while True:
        pos = blob.find(needle, start)
        if pos < 0:
            break
        if pos % 4 == 0:
            hits.append(f"0x{pos:08X}")
        start = pos + 1
        if len(hits) >= 24:
            hits.append("truncated")
            break
    return hits


def render_obj(state: bytes) -> Image.Image:
    io = state[statefmt.STATE_IO:statefmt.STATE_PALETTE]
    oam = state[statefmt.STATE_OAM:statefmt.STATE_VRAM]
    vram = state[statefmt.STATE_VRAM:statefmt.STATE_IWRAM]
    pal = state[statefmt.STATE_PALETTE:statefmt.STATE_OAM]
    obj = vram[statefmt.OBJ_VRAM:]
    image = Image.new("RGBA", (240, 160), (0, 0, 0, 0))
    pixels = image.load()
    oned = bool(u16(io, 0) & 0x0040)
    if not oned:
        return image
    for index in range(128):
        attr0, attr1, attr2, _ = struct.unpack_from("<HHHH", oam, index * 8)
        if (attr0 >> 8) & 3 == 2:
            continue
        dims = statefmt.oam_size((attr0 >> 14) & 3, (attr1 >> 14) & 3)
        if dims is None or attr0 & 0x2000:
            continue
        x0 = attr1 & 0x1FF
        y0 = attr0 & 0xFF
        if x0 >= 240:
            x0 -= 512
        if y0 >= 160:
            y0 -= 256
        tile0 = attr2 & 0x03FF
        bank = (attr2 >> 12) & 0x0F
        width, height = dims
        for ty in range(height // 8):
            for tx in range(width // 8):
                tile = tile0 + ty * (width // 8) + tx
                raw = obj[tile * 32:tile * 32 + 32]
                if len(raw) < 32:
                    continue
                pix = plaque.decode_tile4(raw)
                for py in range(8):
                    for px in range(8):
                        colour = pix[py][px]
                        if colour == 0:
                            continue
                        sx = x0 + tx * 8 + px
                        sy = y0 + ty * 8 + py
                        if not (0 <= sx < 240 and 0 <= sy < 160):
                            continue
                        value = u16(pal, 0x200 + (bank * 16 + colour) * 2)
                        pixels[sx, sy] = (*bgutil.rgb555(value), 255)
    return image


def composite(state: bytes) -> Image.Image:
    bg = plaque.composite_state(state)
    obj = render_obj(state)
    return Image.alpha_composite(bg, obj)


def io_summary(state: bytes) -> dict[str, Any]:
    io = state[statefmt.STATE_IO:statefmt.STATE_PALETTE]
    return {
        "DISPCNT": f"0x{u16(io, 0):04X}",
        "BG0CNT": f"0x{u16(io, 8):04X}",
        "BG1CNT": f"0x{u16(io, 10):04X}",
        "BG2CNT": f"0x{u16(io, 12):04X}",
        "BG3CNT": f"0x{u16(io, 14):04X}",
        "header": {
            "magic": f"0x{u32(state, 0):08X}",
            "version": f"0x{u32(state, 4):08X}",
            "rom_crc32": f"0x{u32(state, 8):08X}",
            "rom_size": u32(state, 12),
            "title": state[0x10:0x1C].split(b"\x00", 1)[0].decode("ascii", "replace"),
        },
    }


def plaque_compact(scan: dict[str, Any]) -> dict[str, Any]:
    if not scan.get("found"):
        return {"found": False}
    cells = []
    hashes = []
    for line in scan["map"]:
        cells.append([cell["cell"] for cell in line])
        hashes.append([cell["sha256"][:16] for cell in line])
    return {
        "found": True,
        "bg2cnt": scan["bg2cnt"],
        "screen_vram": scan["screen_vram"],
        "charblock": scan["charblock"],
        "screenblock": scan["screenblock"],
        "rect": [scan["x0"], scan["y0"], scan["width"], scan["height"]],
        "unique_tiles": scan["unique_tiles"],
        "map_cells": cells,
        "tile_sha16": hashes,
    }


def glyph_report(state: bytes, tiles: list[int]) -> dict[str, Any]:
    rows = {}
    for tile in tiles:
        raw = plaque.bg_tile_bytes(state, 2, tile)
        rows[f"0x{tile:03X}"] = {
            "sha256": sha256(raw),
            "ascii": plaque.ascii_glyph(plaque.decode_tile4(raw)),
        }
    return rows


def badge_focus(state: bytes) -> list[dict[str, Any]]:
    rows = []
    for item in plaque.badge_column(state):
        pals = sorted({cell["palette"] for cell in item["cells"]})
        tiles = [cell["tile"] for cell in item["cells"]]
        rows.append({
            "y": item["y"],
            "palettes": pals,
            "tiles": tiles,
            "left_sha16": item["left_sha256"][:16],
            "right_sha16": item["right_sha256"][:16],
        })
    return rows


def vram_diff(a: bytes, b: bytes) -> dict[str, int]:
    va = a[statefmt.STATE_VRAM:statefmt.STATE_IWRAM]
    vb = b[statefmt.STATE_VRAM:statefmt.STATE_IWRAM]
    changed = sum(1 for x, y in zip(va, vb) if x != y)
    bg2_map_a = va[0xE800:0xF000]
    bg2_map_b = vb[0xE800:0xF000]
    bg1_map_a = va[0xE000:0xE800]
    bg1_map_b = vb[0xE000:0xE800]
    obj_a = va[0x10000:]
    obj_b = vb[0x10000:]
    return {
        "vram_bytes_changed": changed,
        "bg1_screenblock28_changed": sum(1 for x, y in zip(bg1_map_a, bg1_map_b) if x != y),
        "bg2_screenblock29_changed": sum(1 for x, y in zip(bg2_map_a, bg2_map_b) if x != y),
        "obj_vram_changed": sum(1 for x, y in zip(obj_a, obj_b) if x != y),
    }


def trace_dump(ewram: bytes) -> dict[str, Any]:
    region = ewram[TRACE_OFF:TRACE_OFF + trace.TRACE_SIZE]
    nonzero = sum(1 for b in region if b)
    records = []
    for index in range(trace.TRACE_SIZE // trace.RECORD_SIZE):
        off = TRACE_OFF + index * trace.RECORD_SIZE
        values = struct.unpack_from("<8I", ewram, off)
        if any(values):
            records.append({"index": index, "values": [f"0x{v:08X}" for v in values]})
    # Look for leftover count-like tables elsewhere.
    candidates = []
    for off in range(0, len(ewram) - 32, 32):
        count = u32(ewram, off)
        r0 = u32(ewram, off + 4)
        if 1 <= count <= 4096 and (0x06000000 <= r0 < 0x06018000 or 0x08000000 <= r0 < 0x0A000000):
            candidates.append({"ewram": f"0x{EWRAM_BASE + off:08X}", "count": count, "r0": f"0x{r0:08X}"})
            if len(candidates) >= 16:
                break
    return {
        "trace_base": f"0x{trace.TRACE_BASE:08X}",
        "nonzero_bytes": nonzero,
        "nonzero_records": records,
        "countlike_elsewhere": candidates,
    }


def save_preview(state: bytes, name: str, scan: dict[str, Any]) -> dict[str, str]:
    PREVIEW.mkdir(parents=True, exist_ok=True)
    full = composite(state)
    full4 = plaque.scale(full, 4)
    full_path = PREVIEW / f"{name}_full.png"
    full4.save(full_path)
    crop_path = PREVIEW / f"{name}_plaque.png"
    if scan.get("found"):
        x0 = scan["x0"] * 8
        y0 = scan["y0"] * 8
        crop = plaque.scale(full.crop((x0, y0, x0 + scan["width"] * 8, y0 + scan["height"] * 8)), 8)
        crop.save(crop_path)
    return {"full": advance_relative(full_path), "plaque": advance_relative(crop_path)}


def main() -> int:
    rom = trace.OUT_ROM.read_bytes()
    main_rom = MAIN_TIP_ROM.read_bytes()
    jp_rom = ORIGINAL_ROM.read_bytes()
    manifest = json.loads(trace.MANIFEST.read_text(encoding="utf-8"))
    calls = manifest["calls"]
    candidate_crc = binascii.crc32(rom) & 0xFFFFFFFF
    main_crc = binascii.crc32(main_rom) & 0xFFFFFFFF
    jp_crc = binascii.crc32(jp_rom) & 0xFFFFFFFF

    baseline_plaque = None
    if KO_BASELINE.is_file():
        base_state, _ = statefmt.parse_png_state(KO_BASELINE)
        baseline_plaque = plaque_compact(plaque.plaque_scan(base_state))

    reports = []
    parsed = []
    prev_rows = None
    prev_state = None
    for path, label in zip(STATES, LABELS):
        state, _chunks = statefmt.parse_png_state(path)
        parsed.append(state)
        ewram = state[0x21000:0x61000]
        iwram = state[statefmt.STATE_IWRAM:statefmt.STATE_IWRAM + statefmt.IWRAM_SIZE]
        rows = reader.parse_rows(ewram, rom, calls)
        executed = [row for row in rows if row["count"]]
        plaque_rows = [row for row in rows if row.get("plaque_flags")]
        delta = []
        if prev_rows is not None:
            for old, new in zip(prev_rows, rows):
                if new["count"] != old["count"]:
                    delta.append({
                        "name": new["name"],
                        "from": old["count"],
                        "to": new["count"],
                        "plaque_flags": new.get("plaque_flags", []),
                    })
        scan = plaque.plaque_scan(state)
        compact = plaque_compact(scan)
        previews = save_preview(state, label, scan)
        crc = u32(state, 8)
        if crc == candidate_crc:
            rom_match = "candidate_ec0c_trace"
        elif crc == main_crc:
            rom_match = "canonical_main"
        elif crc == jp_crc:
            rom_match = "japanese"
        else:
            rom_match = "unknown"
        glyph_ids = compact.get("unique_tiles") or list(GLYPH_TILES)
        report = {
            "label": label,
            "path": advance_relative(path),
            "size": path.stat().st_size,
            "io": io_summary(state),
            "rom_match": rom_match,
            "executed_count": sum(1 for row in rows if row["count"]),
            "executed": executed,
            "plaque_relevant": plaque_rows,
            "delta_from_previous": delta,
            "plaque": compact,
            "plaque_matches_ko_baseline": compact == baseline_plaque if baseline_plaque else None,
            "badges": badge_focus(state),
            "glyph_tiles": glyph_report(state, sorted(set(glyph_ids))[:24]),
            "trace_memory": trace_dump(ewram),
            "pointer_hits": {
                "ewram_0600E800": aligned_hits(ewram, 0x0600E800),
                "ewram_0801EC0C": aligned_hits(ewram, 0x0801EC0C),
                "ewram_080C5700": aligned_hits(ewram, 0x080C5700),
                "iwram_0801EC0C": aligned_hits(iwram, 0x0801EC0C),
                "iwram_0801F554": aligned_hits(iwram, 0x0801F554),
                "iwram_080C5700": aligned_hits(iwram, 0x080C5700),
            },
            "previews": previews,
        }
        if prev_state is not None:
            report["diff_from_previous"] = vram_diff(prev_state, state)
        reports.append(report)
        prev_rows = rows
        prev_state = state

    # Cross-state plaque / badge identity.
    plaque_equal = all(item["plaque"] == reports[0]["plaque"] for item in reports[1:])
    badge_delta = []
    if len(reports) >= 3:
        for left, right, pair in ((0, 1, "ss1_to_ss2"), (1, 2, "ss2_to_ss3")):
            a = reports[left]["badges"]
            b = reports[right]["badges"]
            changed = []
            for old, new in zip(a, b):
                if old != new:
                    changed.append({"y": new["y"], "from": old, "to": new})
            badge_delta.append({"pair": pair, "changed_rows": changed})

    wrapper0 = bytes(rom[trace.CAVE_FILE:trace.CAVE_FILE + 16])
    conclusion = []
    if reports[0]["rom_match"] != "candidate_ec0c_trace":
        conclusion.append("savestates_not_from_candidate_rom")
    if all(item["executed_count"] == 0 for item in reports):
        conclusion.append("ec0c_wrappers_never_recorded_a_call")
    if plaque_equal and reports[0]["plaque"].get("found"):
        conclusion.append("plaque_stable_across_focus_moves")
    if reports[0]["plaque"].get("found") and reports[0]["plaque"].get("screen_vram") == "0x0600E800":
        conclusion.append("live_plaque_still_screenblock29")

    out = {
        "schema_version": 1,
        "kind": "ggen_advance_owned_count_ec0c_trace_runtime_20260904",
        "result": "PASS",
        "roms": {
            "candidate_sha256": sha256(rom),
            "candidate_crc32": f"0x{candidate_crc:08X}",
            "main_crc32": f"0x{main_crc:08X}",
            "jp_crc32": f"0x{jp_crc:08X}",
            "wrapper0_head": wrapper0.hex(" ").upper(),
            "first_callsite_bl": rom[0x1EC42:0x1EC46].hex(" ").upper(),
        },
        "baseline_ko_plaque": baseline_plaque,
        "plaque_identical_across_states": plaque_equal,
        "badge_deltas": badge_delta,
        "conclusion_flags": conclusion,
        "states": reports,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "out": advance_relative(OUT),
        "rom_match": [item["rom_match"] for item in reports],
        "executed_count": [item["executed_count"] for item in reports],
        "plaque_found": [item["plaque"].get("found") for item in reports],
        "plaque_identical": plaque_equal,
        "conclusion_flags": conclusion,
        "previews": [item["previews"]["full"] for item in reports],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
