#!/usr/bin/env python3
"""Compare Korean vs Japanese unit-remodel ss2 backgrounds.

Reads the current main-TIP and original-ROM slot-2 savestates, dumps GBA
display registers, VRAM ownership, and per-layer previews so the repeating
tan 'L' tiles can be attributed to a specific charblock/tilemap/font collision.
"""
from __future__ import annotations

import binascii
import hashlib
import json
import struct
from collections import Counter
from pathlib import Path
from typing import Any

from PIL import Image

import analyze_ggen_advance_intermission_cycle_states_20260830 as bg
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
from ggen_advance_project_paths import ADVANCE_ROOT, MAIN_TIP_ROM, ORIGINAL_ROM

KO_STATE = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).ss2"
JP_STATE = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Japan).ss2"
OUT_DIR = ADVANCE_ROOT / "outputs" / "20260905_ggen_advance_remodel_ss2_bg"
ANALYSIS = ADVANCE_ROOT / "analysis" / "ggen_advance_remodel_ss2_bg_corruption_20260905.json"
FONT12_BASE = 0x0008AC40
FONT12_STRIDE = 18
FONT8_TABLE = 0x0008A0A8


def u16(data: bytes, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def i16(data: bytes, off: int) -> int:
    return struct.unpack_from("<h", data, off)[0]


def i32(data: bytes, off: int) -> int:
    return struct.unpack_from("<i", data, off)[0]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def rgb555(value: int) -> tuple[int, int, int]:
    return tuple(((value >> shift) & 31) * 255 // 31 for shift in (0, 5, 10))


def io_regs(state: bytes) -> dict[str, Any]:
    io = state[statefmt.STATE_IO:statefmt.STATE_PALETTE]
    dispcnt = u16(io, 0)
    layers = []
    for index in range(4):
        info = bg.bg_info(state, index)
        layers.append({
            **info,
            "cnt_hex": f"0x{info['cnt']:04X}",
            "enabled": bool(dispcnt & (1 << (8 + index))),
        })
    affine = {}
    for name, base in (("bg2", 0x20), ("bg3", 0x30)):
        affine[name] = {
            "pa": i16(io, base),
            "pb": i16(io, base + 2),
            "pc": i16(io, base + 4),
            "pd": i16(io, base + 6),
            "x": i32(io, base + 8),
            "y": i32(io, base + 12),
            "pa_hex": f"0x{u16(io, base):04X}",
            "x_hex": f"0x{u32(io, base + 8):08X}",
            "y_hex": f"0x{u32(io, base + 12):08X}",
        }
    return {
        "dispcnt": f"0x{dispcnt:04X}",
        "mode": dispcnt & 7,
        "obj_1d": bool(dispcnt & 0x40),
        "forced_blank": bool(dispcnt & 0x80),
        "bg_enable": [(dispcnt >> 8) & 1, (dispcnt >> 9) & 1, (dispcnt >> 10) & 1, (dispcnt >> 11) & 1],
        "obj_enable": bool(dispcnt & 0x1000),
        "layers": layers,
        "affine": affine,
        "win0h": f"0x{u16(io, 0x40):04X}",
        "win1h": f"0x{u16(io, 0x42):04X}",
        "win0v": f"0x{u16(io, 0x44):04X}",
        "win1v": f"0x{u16(io, 0x46):04X}",
        "winin": f"0x{u16(io, 0x48):04X}",
        "winout": f"0x{u16(io, 0x4A):04X}",
        "bldcnt": f"0x{u16(io, 0x50):04X}",
        "bldalpha": f"0x{u16(io, 0x52):04X}",
        "rom_crc32": f"0x{u32(state, 8):08X}",
    }


def vram_block_hashes(state: bytes) -> dict[str, Any]:
    vram = state[statefmt.STATE_VRAM:statefmt.STATE_IWRAM]
    rows = []
    for block in range(6):
        chunk = vram[block * 0x4000:(block + 1) * 0x4000]
        rows.append({
            "block": block,
            "gba": f"0x{0x06000000 + block * 0x4000:08X}",
            "sha256": sha256(chunk),
            "nonzero": sum(1 for b in chunk if b),
        })
    screens = []
    for screen in range(32):
        chunk = vram[screen * 0x800:(screen + 1) * 0x800]
        screens.append({
            "screenblock": screen,
            "gba": f"0x{0x06000000 + screen * 0x800:08X}",
            "sha256": sha256(chunk),
            "nonzero": sum(1 for b in chunk if b),
        })
    return {"charblocks": rows, "screenblocks": screens, "obj": sha256(vram[0x10000:])}


def map_histogram(state: bytes, layer: int, affine: bool) -> dict[str, Any]:
    info = bg.bg_info(state, layer)
    vram = state[statefmt.STATE_VRAM:statefmt.STATE_IWRAM]
    counts: Counter[int] = Counter()
    samples = []
    if affine:
        size = 128 << info["size"]
        data = vram[info["screen_base"]:info["screen_base"] + size * size]
        for y in range(min(size, 32)):
            for x in range(min(size, 32)):
                tid = data[y * size + x]
                counts[tid] += 1
        for tid, n in counts.most_common(12):
            samples.append({"tile": tid, "count": n})
        return {
            "layer": layer,
            "affine": True,
            "map_size_tiles": size,
            "unique_tiles": len(counts),
            "top": samples,
            "tile0": counts.get(0, 0),
        }
    width, height = bg.bg_dimensions(info["size"])
    for y in range(min(height // 8, 32)):
        for x in range(min(width // 8, 32)):
            cell = bg.map_entry(vram, info["screen_base"], info["size"], x, y)
            counts[cell & 0x3FF] += 1
    for tid, n in counts.most_common(12):
        samples.append({"tile": tid, "count": n})
    return {
        "layer": layer,
        "affine": False,
        "unique_tiles": len(counts),
        "top": samples,
        "tile0": counts.get(0, 0),
    }


def tile_bytes(vram: bytes, char_base: int, tid: int, bpp8: bool) -> bytes:
    stride = 64 if bpp8 else 32
    off = char_base + tid * stride
    return bytes(vram[off:off + stride])


def unique_visible_tiles(state: bytes, layer: int, affine: bool) -> dict[int, bytes]:
    info = bg.bg_info(state, layer)
    vram = state[statefmt.STATE_VRAM:statefmt.STATE_IWRAM]
    result: dict[int, bytes] = {}
    if affine:
        size = 128 << info["size"]
        data = vram[info["screen_base"]:info["screen_base"] + size * size]
        for y in range(min(size, 64)):
            for x in range(min(size, 64)):
                tid = data[y * size + x]
                if tid not in result:
                    result[tid] = tile_bytes(vram, info["char_base"], tid, True)
        return result
    for y in range(20):
        for x in range(30):
            cell = bg.map_entry(vram, info["screen_base"], info["size"], x, y)
            tid = cell & 0x3FF
            if tid not in result:
                result[tid] = tile_bytes(vram, info["char_base"], tid, info["color_8bpp"])
    return result


def render_affine(state: bytes, layer: int, path: Path) -> dict[str, Any]:
    io = state[statefmt.STATE_IO:statefmt.STATE_PALETTE]
    vram = state[statefmt.STATE_VRAM:statefmt.STATE_IWRAM]
    pal = state[statefmt.STATE_PALETTE:statefmt.STATE_OAM]
    info = bg.bg_info(state, layer)
    size = 128 << info["size"]
    base = 0x20 if layer == 2 else 0x30
    pa, pb, pc, pd = (i16(io, base + i) for i in (0, 2, 4, 6))
    x0, y0 = i32(io, base + 8), i32(io, base + 12)
    image = Image.new("RGBA", (240, 160), (0, 0, 0, 0))
    pixels = image.load()
    used: Counter[int] = Counter()
    for sy in range(160):
        x = x0 + pb * sy
        y = y0 + pd * sy
        for sx in range(240):
            tx = (x >> 8) & (size * 8 - 1)
            ty = (y >> 8) & (size * 8 - 1)
            tid = vram[info["screen_base"] + (ty // 8) * size + (tx // 8)]
            used[tid] += 1
            px, py = tx & 7, ty & 7
            colour = vram[info["char_base"] + tid * 64 + py * 8 + px]
            if colour:
                pixels[sx, sy] = (*rgb555(u16(pal, colour * 2)), 255)
            x += pa
            y += pc
    path.parent.mkdir(parents=True, exist_ok=True)
    image.resize((960, 640), Image.NEAREST).save(path)
    return {"unique_sampled_tiles": len(used), "top": [{"tile": t, "pixels": n} for t, n in used.most_common(8)]}


def rom_hits(rom: bytes, payload: bytes, limit: int = 8) -> list[str]:
    hits = []
    pos = rom.find(payload)
    while pos >= 0 and len(hits) < limit:
        hits.append(f"0x{pos:08X}")
        pos = rom.find(payload, pos + 1)
    return hits


def font12_slots(rom: bytes, payload32: bytes) -> list[int]:
    """A 4bpp 8x8 tile may be the top-left of a 12x12 glyph unpacked into VRAM."""
    return []


def compare_tiles(ko: bytes, jp: bytes, layer: int, affine: bool, ko_rom: bytes, jp_rom: bytes) -> dict[str, Any]:
    ko_tiles = unique_visible_tiles(ko, layer, affine)
    jp_tiles = unique_visible_tiles(jp, layer, affine)
    identical = 0
    different = []
    only_ko = sorted(set(ko_tiles) - set(jp_tiles))
    only_jp = sorted(set(jp_tiles) - set(ko_tiles))
    common = sorted(set(ko_tiles) & set(jp_tiles))
    for tid in common:
        if ko_tiles[tid] == jp_tiles[tid]:
            identical += 1
        elif len(different) < 24:
            different.append({
                "tile": tid,
                "ko_sha": sha256(ko_tiles[tid]),
                "jp_sha": sha256(jp_tiles[tid]),
                "ko_rom": rom_hits(ko_rom, ko_tiles[tid][:32], 4),
                "jp_rom": rom_hits(jp_rom, jp_tiles[tid][:32], 4),
                "ko_in_jp_rom": rom_hits(jp_rom, ko_tiles[tid][:32], 4),
            })
    return {
        "layer": layer,
        "ko_unique": len(ko_tiles),
        "jp_unique": len(jp_tiles),
        "identical_payloads": identical,
        "common_ids": len(common),
        "only_ko_ids": only_ko[:40],
        "only_jp_ids": only_jp[:40],
        "different_sample": different,
    }


def dominant_tile_preview(state: bytes, layer: int, affine: bool, path: Path) -> dict[str, Any]:
    info = bg.bg_info(state, layer)
    vram = state[statefmt.STATE_VRAM:statefmt.STATE_IWRAM]
    pal = state[statefmt.STATE_PALETTE:statefmt.STATE_OAM]
    hist = map_histogram(state, layer, affine)
    if not hist["top"]:
        return hist
    tid = hist["top"][0]["tile"]
    raw = tile_bytes(vram, info["char_base"], tid, affine or info["color_8bpp"])
    image = Image.new("RGB", (64, 64))
    pixels = image.load()
    if affine or info["color_8bpp"]:
        for y in range(8):
            for x in range(8):
                colour = raw[y * 8 + x]
                rgb = rgb555(u16(pal, colour * 2))
                for dy in range(8):
                    for dx in range(8):
                        pixels[x * 8 + dx, y * 8 + dy] = rgb
    else:
        for y in range(8):
            for x in range(8):
                packed = raw[y * 4 + x // 2]
                colour = (packed >> (4 * (x & 1))) & 15
                rgb = rgb555(u16(pal, colour * 2))
                for dy in range(8):
                    for dx in range(8):
                        pixels[x * 8 + dx, y * 8 + dy] = rgb
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    return {"dominant_tile": tid, "payload_sha": sha256(raw), "bytes": raw[:32].hex()}


def palette_diff(ko: bytes, jp: bytes) -> dict[str, Any]:
    a = ko[statefmt.STATE_PALETTE:statefmt.STATE_OAM]
    b = jp[statefmt.STATE_PALETTE:statefmt.STATE_OAM]
    changed = [i for i in range(0, 512, 2) if a[i:i + 2] != b[i:i + 2]]
    return {
        "identical": a == b,
        "changed_entries": len(changed),
        "first_changed": changed[:16],
        "bg_sha": sha256(a[:512]),
        "obj_sha": sha256(a[512:]),
        "jp_bg_sha": sha256(b[:512]),
        "jp_obj_sha": sha256(b[512:]),
    }


def main() -> None:
    ko, _ = statefmt.parse_png_state(KO_STATE)
    jp, _ = statefmt.parse_png_state(JP_STATE)
    ko_rom = MAIN_TIP_ROM.read_bytes()
    jp_rom = ORIGINAL_ROM.read_bytes()
    ko_io = io_regs(ko)
    jp_io = io_regs(jp)
    mode = ko_io["mode"]
    affine_layers = {1: [2], 2: [2, 3]}.get(mode, [])
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    layer_reports = []
    for layer in range(4):
        affine = layer in affine_layers
        if affine:
            ko_aff = render_affine(ko, layer, OUT_DIR / f"ko_affine_bg{layer}.png")
            jp_aff = render_affine(jp, layer, OUT_DIR / f"jp_affine_bg{layer}.png")
        else:
            bg.render_bg(ko, bg.bg_info(ko, layer), OUT_DIR / f"ko_bg{layer}.png")
            bg.render_bg(jp, bg.bg_info(jp, layer), OUT_DIR / f"jp_bg{layer}.png")
            ko_aff = jp_aff = None
        layer_reports.append({
            "ko_hist": map_histogram(ko, layer, affine),
            "jp_hist": map_histogram(jp, layer, affine),
            "tile_compare": compare_tiles(ko, jp, layer, affine, ko_rom, jp_rom),
            "ko_affine_sample": ko_aff,
            "jp_affine_sample": jp_aff,
            "ko_dominant": dominant_tile_preview(ko, layer, affine, OUT_DIR / f"ko_bg{layer}_dominant.png"),
            "jp_dominant": dominant_tile_preview(jp, layer, affine, OUT_DIR / f"jp_bg{layer}_dominant.png"),
        })
    ko_hash = vram_block_hashes(ko)
    jp_hash = vram_block_hashes(jp)
    char_diff = []
    for a, b in zip(ko_hash["charblocks"], jp_hash["charblocks"]):
        char_diff.append({
            "block": a["block"],
            "identical": a["sha256"] == b["sha256"],
            "ko": a,
            "jp": b,
        })
    screen_diff = []
    for a, b in zip(ko_hash["screenblocks"], jp_hash["screenblocks"]):
        if a["sha256"] != b["sha256"]:
            screen_diff.append({
                "screenblock": a["screenblock"],
                "ko_nonzero": a["nonzero"],
                "jp_nonzero": b["nonzero"],
            })
    # Byte-level charblock diffs for the first differing 4bpp/8bpp tiles.
    ko_vram = ko[statefmt.STATE_VRAM:statefmt.STATE_IWRAM]
    jp_vram = jp[statefmt.STATE_VRAM:statefmt.STATE_IWRAM]
    tile_diffs = []
    for off in range(0, 0x10000, 32):
        if ko_vram[off:off + 32] != jp_vram[off:off + 32]:
            tile_diffs.append(off)
    first_diff_details = []
    for off in tile_diffs[:16]:
        payload = bytes(ko_vram[off:off + 32])
        first_diff_details.append({
            "vram": f"0x{0x06000000 + off:08X}",
            "ko_rom": rom_hits(ko_rom, payload, 6),
            "jp_rom": rom_hits(jp_rom, payload, 6),
            "jp_tile_in_ko_rom": rom_hits(ko_rom, bytes(jp_vram[off:off + 32]), 6),
        })
    report = {
        "kind": "ggen_advance_remodel_ss2_bg_corruption_20260905",
        "files": {
            "ko_state": str(KO_STATE),
            "jp_state": str(JP_STATE),
            "ko_rom_sha256": sha256(ko_rom),
            "jp_rom_sha256": sha256(jp_rom),
            "ko_state_crc": f"0x{u32(ko, 8):08X}",
            "jp_state_crc": f"0x{u32(jp, 8):08X}",
            "ko_rom_crc": f"0x{binascii.crc32(ko_rom) & 0xFFFFFFFF:08X}",
            "jp_rom_crc": f"0x{binascii.crc32(jp_rom) & 0xFFFFFFFF:08X}",
        },
        "ko_io": ko_io,
        "jp_io": jp_io,
        "io_identical": ko[statefmt.STATE_IO:statefmt.STATE_PALETTE] == jp[statefmt.STATE_IO:statefmt.STATE_PALETTE],
        "palette": palette_diff(ko, jp),
        "charblock_diff": char_diff,
        "screenblock_diff_count": len(screen_diff),
        "screenblock_diff": screen_diff[:40],
        "obj_vram_identical": ko_hash["obj"] == jp_hash["obj"],
        "bg_4bpp_tile_diff_count": len(tile_diffs),
        "first_bg_tile_diffs": first_diff_details,
        "layers": layer_reports,
    }
    ANALYSIS.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "analysis": str(ANALYSIS),
        "previews": str(OUT_DIR),
        "ko_mode": ko_io["mode"],
        "jp_mode": jp_io["mode"],
        "ko_dispcnt": ko_io["dispcnt"],
        "jp_dispcnt": jp_io["dispcnt"],
        "charblock_identical": [row["identical"] for row in char_diff],
        "bg_tile_diffs": len(tile_diffs),
        "ko_crc_match": u32(ko, 8) == (binascii.crc32(ko_rom) & 0xFFFFFFFF),
        "jp_crc_match": u32(jp, 8) == (binascii.crc32(jp_rom) & 0xFFFFFFFF),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
