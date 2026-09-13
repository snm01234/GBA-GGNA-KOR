#!/usr/bin/env python3
"""Read-only analysis of the three intermission focus-cycle savestates."""
from __future__ import annotations

import binascii
import hashlib
import json
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image

THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_action_graphics_scan_20260830 as scan
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt

ROM = ROOT / "SD Gundam GGeneration Advance (Korean).gba"
STATES = [ROOT / f"SD Gundam GGeneration Advance (Korean).ss{i}" for i in (1, 2, 3)]
OUT = ROOT / "analysis" / "ggen_advance_intermission_cycle_states_20260830.json"
PREVIEW_DIR = ROOT / "outputs" / "20260830_ggen_advance_intermission_cycle_analysis"
FOCUS = {1: "작전", 2: "편성", 3: "개발"}
PACKAGE = 0x00C493B4
ATLAS_START = 0x00C4FC98
ATLAS_END = 0x00C51178


def u16(data: bytes, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def rgb555(value: int) -> tuple[int, int, int]:
    return tuple(((value >> shift) & 31) * 255 // 31 for shift in (0, 5, 10))


def bg_dimensions(size: int) -> tuple[int, int]:
    return ((256, 256), (512, 256), (256, 512), (512, 512))[size]


def map_entry(vram: bytes, screen_base: int, size: int, tx: int, ty: int) -> int:
    width, height = bg_dimensions(size)
    tx %= width // 8
    ty %= height // 8
    block_x, block_y = tx // 32, ty // 32
    if size == 0:
        block = 0
    elif size == 1:
        block = block_x
    elif size == 2:
        block = block_y
    else:
        block = block_y * 2 + block_x
    off = screen_base + block * 0x800 + ((ty & 31) * 32 + (tx & 31)) * 2
    return u16(vram, off)


def bg_info(state: bytes, index: int) -> dict:
    io = state[statefmt.STATE_IO:statefmt.STATE_PALETTE]
    cnt = u16(io, 8 + index * 2)
    return {
        "index": index, "cnt": cnt, "priority": cnt & 3,
        "char_base": ((cnt >> 2) & 3) * 0x4000,
        "color_8bpp": bool(cnt & 0x80),
        "screen_base": ((cnt >> 8) & 31) * 0x800,
        "size": (cnt >> 14) & 3,
        "scroll_x": u16(io, 0x10 + index * 4) & 0x1FF,
        "scroll_y": u16(io, 0x12 + index * 4) & 0x1FF,
    }


def render_bg(state: bytes, info: dict, path: Path) -> None:
    vram = state[statefmt.STATE_VRAM:statefmt.STATE_IWRAM]
    pal = state[statefmt.STATE_PALETTE:statefmt.STATE_OAM]
    image = Image.new("RGBA", (240, 160), (0, 0, 0, 0))
    pixels = image.load()
    for sy in range(160):
        wy = sy + info["scroll_y"]
        for sx in range(240):
            wx = sx + info["scroll_x"]
            entry = map_entry(vram, info["screen_base"], info["size"], wx // 8, wy // 8)
            tile = entry & 0x3FF
            px, py = wx & 7, wy & 7
            if entry & 0x400:
                px = 7 - px
            if entry & 0x800:
                py = 7 - py
            if info["color_8bpp"]:
                off = info["char_base"] + tile * 64 + py * 8 + px
                colour = vram[off]
                if colour == 0:
                    continue
                value = u16(pal, colour * 2)
            else:
                off = info["char_base"] + tile * 32 + py * 4 + px // 2
                packed = vram[off]
                colour = (packed >> (4 * (px & 1))) & 15
                if colour == 0:
                    continue
                bank = (entry >> 12) & 15
                value = u16(pal, (bank * 16 + colour) * 2)
            pixels[sx, sy] = (*rgb555(value), 255)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.resize((960, 640), Image.Resampling.NEAREST).save(path)


def target_tiles(state: bytes, info: dict) -> dict[int, bytes]:
    """Tiles visible in native x=0..103,y=0..95, covering all three circles."""
    vram = state[statefmt.STATE_VRAM:statefmt.STATE_IWRAM]
    result: dict[int, bytes] = {}
    for sy in range(0, 96, 8):
        for sx in range(0, 104, 8):
            wx, wy = sx + info["scroll_x"], sy + info["scroll_y"]
            entry = map_entry(vram, info["screen_base"], info["size"], wx // 8, wy // 8)
            tile = entry & 0x3FF
            tile_bytes = 64 if info["color_8bpp"] else 32
            off = info["char_base"] + tile * tile_bytes
            result[tile] = bytes(vram[off:off + tile_bytes])
    return result


def object_tile_ids(entry: dict, mapping_1d: bool = True) -> list[int]:
    tiles_per_row = entry["width"] // 8
    rows = entry["height"] // 8
    if mapping_1d:
        return [entry["tile"] + y * tiles_per_row + x for y in range(rows) for x in range(tiles_per_row)]
    return [entry["tile"] + y * 32 + x for y in range(rows) for x in range(tiles_per_row)]


def render_target_obj(state: bytes, path: Path) -> None:
    oam = state[statefmt.STATE_OAM:statefmt.STATE_VRAM]
    vram = state[statefmt.STATE_VRAM:statefmt.STATE_IWRAM]
    obj = vram[statefmt.OBJ_VRAM:]
    pal = state[statefmt.STATE_PALETTE:statefmt.STATE_OAM]
    image = Image.new("RGBA", (240, 160), (0, 0, 0, 0))
    pixels = image.load()
    # Higher OAM indices are behind lower indices at equal priority.
    for index in reversed(range(22)):
        entry = statefmt.parse_oam_entry(oam, index)
        attr0 = int(entry["attr0"], 16)
        attr1 = int(entry["attr1"], 16)
        if ((attr0 >> 8) & 3) == 2:
            continue
        affine = bool(attr0 & 0x100)
        colour8 = bool(attr0 & 0x2000)
        if affine or colour8:
            continue
        hflip, vflip = bool(attr1 & 0x1000), bool(attr1 & 0x2000)
        tiles_per_row = entry["width"] // 8
        for py in range(entry["height"]):
            for px in range(entry["width"]):
                source_x = entry["width"] - 1 - px if hflip else px
                source_y = entry["height"] - 1 - py if vflip else py
                tile = entry["tile"] + (source_y // 8) * tiles_per_row + source_x // 8
                off = tile * 32 + (source_y & 7) * 4 + (source_x & 7) // 2
                packed = obj[off]
                colour = (packed >> (4 * (source_x & 1))) & 15
                if colour == 0:
                    continue
                value = u16(pal, 0x200 + (entry["palette_bank"] * 16 + colour) * 2)
                sx, sy = entry["x"] + px, entry["y"] + py
                if 0 <= sx < 240 and 0 <= sy < 160:
                    pixels[sx, sy] = (*rgb555(value), 255)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.resize((960, 640), Image.Resampling.NEAREST).save(path)


def atlas_sources(raw: bytes, atlas: bytes) -> list[int]:
    return [i for i in range(len(atlas) // 32) if atlas[i * 32:(i + 1) * 32] == raw]


def object_group_report(state: bytes) -> dict:
    oam = state[statefmt.STATE_OAM:statefmt.STATE_VRAM]
    obj = state[statefmt.STATE_VRAM + statefmt.OBJ_VRAM:statefmt.STATE_IWRAM]
    rom = ROM.read_bytes()
    atlas = rom[ATLAS_START:ATLAS_END]
    groups = {"focused_circle": [13], "focused_overlay": [0, 1, 2, 3, 4],
              "nonfocus_left_or_top_A": [14, 15, 16, 17], "nonfocus_left_or_top_B": [18, 19, 20, 21]}
    result = {}
    for name, indices in groups.items():
        rows = []
        source_union = set()
        exact = 0
        for index in indices:
            entry = statefmt.parse_oam_entry(oam, index)
            tile_rows = []
            for tile in object_tile_ids(entry):
                raw = bytes(obj[tile * 32:(tile + 1) * 32])
                sources = atlas_sources(raw, atlas)
                if sources:
                    exact += 1
                    source_union.update(sources)
                tile_rows.append({"obj_tile": f"0x{tile:03X}", "atlas_tiles": [f"0x{x:03X}" for x in sources]})
            rows.append({"oam": index, "x": entry["x"], "y": entry["y"], "width": entry["width"],
                         "height": entry["height"], "palette_bank": entry["palette_bank"], "tiles": tile_rows})
        result[name] = {"objects": rows, "exact_tile_uses": exact,
                        "source_atlas_tiles": [f"0x{x:03X}" for x in sorted(source_union)]}
    return result


def accepted_streams(rom: bytes) -> list[dict]:
    result = []
    for off in range(0, len(rom) - 8, 4):
        header = struct.unpack_from("<I", rom, off)[0]
        if (header & 0xFFFF0000) != 0x80000000:
            continue
        body_len = header & 0xFFFF
        if body_len < 16 or off + 4 + body_len > len(rom):
            continue
        try:
            decoded = scan.lzss_decompress(rom[off + 4:off + 4 + body_len])
        except (ValueError, IndexError):
            continue
        if len(decoded) < 32 or len(decoded) % 32 or len(decoded) // 32 > 4096:
            continue
        result.append({"offset": off, "body_len": body_len, "decoded": decoded})
    return result


def match_streams(live: dict[int, bytes], streams: list[dict]) -> list[dict]:
    live4 = {tile: raw for tile, raw in live.items() if len(raw) == 32 and len(set(raw)) > 1}
    scored = []
    for stream in streams:
        source_lookup: dict[bytes, list[int]] = defaultdict(list)
        decoded = stream["decoded"]
        for source_id in range(len(decoded) // 32):
            source_lookup[decoded[source_id * 32:(source_id + 1) * 32]].append(source_id)
        pairs = []
        deltas = Counter()
        for live_id, raw in live4.items():
            for source_id in source_lookup.get(raw, []):
                pairs.append((live_id, source_id))
                deltas[live_id - source_id] += 1
        if not pairs:
            continue
        delta, coherent = deltas.most_common(1)[0]
        coherent_pairs = sorted((a, b) for a, b in pairs if a - b == delta)
        scored.append({
            "resource_file_offset": f"0x{stream['offset']:08X}",
            "compressed_body_length": stream["body_len"],
            "decoded_size": len(decoded), "decoded_tiles": len(decoded) // 32,
            "exact_tile_hits": len({a for a, _ in pairs}),
            "dominant_live_minus_source_delta": delta,
            "coherent_exact_hits": coherent,
            "coherent_pairs": [[f"0x{a:03X}", f"0x{b:03X}"] for a, b in coherent_pairs],
        })
    return sorted(scored, key=lambda row: (row["coherent_exact_hits"], row["exact_tile_hits"]), reverse=True)[:12]


def main() -> int:
    rom = ROM.read_bytes()
    states = [statefmt.parse_png_state(path)[0] for path in STATES]
    crc = binascii.crc32(rom) & 0xFFFFFFFF
    state_crcs = [struct.unpack_from("<I", state, 8)[0] for state in states]
    statefmt.gate(all(value == crc for value in state_crcs), f"savestate ROM CRC mismatch: {state_crcs} vs {crc}")
    streams = accepted_streams(rom)

    reports = []
    layer_live_union: dict[int, dict[int, bytes]] = {i: {} for i in range(4)}
    for number, state in enumerate(states, 1):
        io = state[statefmt.STATE_IO:statefmt.STATE_PALETTE]
        dispcnt = u16(io, 0)
        layers = []
        for index in range(4):
            info = bg_info(state, index)
            info["enabled"] = bool(dispcnt & (0x100 << index))
            if info["enabled"]:
                path = PREVIEW_DIR / f"state{number}_bg{index}.png"
                render_bg(state, info, path)
                live = target_tiles(state, info)
                layer_live_union[index].update(live)
                info["target_roi_unique_tiles"] = [f"0x{x:03X}" for x in sorted(live)]
                info["preview"] = str(path.relative_to(ROOT)).replace("\\", "/")
            layers.append(info)
        obj_path = PREVIEW_DIR / f"state{number}_target_obj.png"
        render_target_obj(state, obj_path)
        reports.append({"state": number, "focus": FOCUS[number], "dispcnt": f"0x{dispcnt:04X}", "layers": layers,
                        "target_obj_preview": str(obj_path.relative_to(ROOT)).replace("\\", "/"),
                        "target_obj_groups": object_group_report(state)})

    differences = []
    regions = {
        "palette": (statefmt.STATE_PALETTE, statefmt.STATE_OAM),
        "oam": (statefmt.STATE_OAM, statefmt.STATE_VRAM),
        "bg_vram": (statefmt.STATE_VRAM, statefmt.STATE_VRAM + statefmt.OBJ_VRAM),
        "obj_vram": (statefmt.STATE_VRAM + statefmt.OBJ_VRAM, statefmt.STATE_IWRAM),
    }
    for left, right in ((0, 1), (1, 2), (0, 2)):
        row = {"states": [left + 1, right + 1]}
        for name, (start, end) in regions.items():
            row[name + "_changed_bytes"] = sum(a != b for a, b in zip(states[left][start:end], states[right][start:end]))
        differences.append(row)

    source_matches = {}
    for index, live in layer_live_union.items():
        if live:
            source_matches[f"bg{index}"] = match_streams(live, streams)

    report = {
        "schema_version": 1, "kind": "ggen_advance_intermission_cycle_states_20260830", "result": "PASS",
        "rom": {"path": ROM.name, "size": len(rom), "sha256": hashlib.sha256(rom).hexdigest(), "crc32": f"0x{crc:08X}"},
        "states": reports, "state_differences": differences,
        "target_sprite_package": {"pointer": f"0x{0x08000000 + PACKAGE:08X}",
                                  "file_offset": f"0x{PACKAGE:08X}",
                                  "raw_atlas_range": [f"0x{ATLAS_START:08X}", f"0x{ATLAS_END:08X}"],
                                  "raw_atlas_size": ATLAS_END - ATLAS_START,
                                  "raw_atlas_tiles": (ATLAS_END - ATLAS_START) // 32},
        "accepted_custom_lzss_streams": len(streams), "target_layer_source_matches": source_matches,
        "scope": "read-only; no ROM bytes modified",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "out": str(OUT), "crc": f"0x{crc:08X}",
                      "differences": differences,
                      "enabled_layers": [[x["index"] for x in r["layers"] if x["enabled"]] for r in reports],
                      "top_matches": {key: value[:3] for key, value in source_matches.items()}}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
