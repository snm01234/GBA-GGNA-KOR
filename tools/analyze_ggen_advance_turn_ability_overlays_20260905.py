#!/usr/bin/env python3
"""Dump ss2 turn-banner and ss3 ability-popup overlays and bind live tiles to ROM."""
from __future__ import annotations

import binascii
import hashlib
import json
import struct
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_remaining_ui_states_20260902 as remaining
import analyze_ggen_advance_settings_suspend_ui as sprite
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
from ggen_advance_project_paths import ADVANCE_ROOT, ORIGINAL_ROM, advance_relative

ROM_BASE = 0x08000000
PARENT = (
    ADVANCE_ROOT
    / "outputs"
    / "20260905_ggen_advance_stage_titles"
    / "ggen_advance_stage_entry_titles_ko_candidate_20260905.gba"
)
STATES = {
    "ss2": PARENT.with_suffix(".ss2"),
    "ss3": PARENT.with_suffix(".ss3"),
}
OUT_DIR = ADVANCE_ROOT / "analysis" / "ggen_advance_turn_ability_overlays_20260905"
OUT_JSON = ADVANCE_ROOT / "analysis" / "ggen_advance_turn_ability_overlays_20260905.json"
EXPECTED_JP_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def u16(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def decode_tile(raw: bytes) -> list[list[int]]:
    return [
        [((raw[y * 4 + x // 2] >> (4 * (x & 1))) & 0xF) for x in range(8)]
        for y in range(8)
    ]


def palette_rgb(palette: bytes, bank: int = 0) -> list[tuple[int, int, int]]:
    colors = []
    for index in range(16):
        value = u16(palette, (bank * 16 + index) * 2)
        colors.append(tuple(((value >> shift) & 31) * 255 // 31 for shift in (0, 5, 10)))
    return colors


def render_obj(state: bytes) -> tuple[Image.Image, list[dict[str, Any]]]:
    oam = state[statefmt.STATE_OAM:statefmt.STATE_VRAM]
    obj = state[statefmt.STATE_VRAM + statefmt.OBJ_VRAM:statefmt.STATE_IWRAM]
    pal = state[statefmt.STATE_PALETTE + 0x200:statefmt.STATE_OAM]
    canvas = Image.new("RGBA", (240, 160), (0, 0, 0, 0))
    rows: list[dict[str, Any]] = []
    for index in range(128):
        row = statefmt.parse_oam_entry(oam, index)
        x, y, w, h = int(row["x"]), int(row["y"]), int(row["width"]), int(row["height"])
        if not (x + w > 0 and y + h > 0 and x < 240 and y < 160):
            continue
        bank = int(row["palette_bank"])
        colors = palette_rgb(pal, bank)
        tile0 = int(row["tile"])
        ink = 0
        sprite_im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        for ty in range(h // 8):
            for tx in range(w // 8):
                tile_id = tile0 + ty * (w // 8) + tx
                raw = obj[tile_id * 32:(tile_id + 1) * 32]
                if len(raw) != 32:
                    continue
                pixels = decode_tile(raw)
                for py in range(8):
                    for px in range(8):
                        value = pixels[py][px]
                        if value:
                            ink += 1
                            sprite_im.putpixel((tx * 8 + px, ty * 8 + py), (*colors[value], 255))
        canvas.alpha_composite(sprite_im, (x, y))
        rows.append({**row, "ink": ink, "tiles": w * h // 64})
    return canvas, rows


def render_bg_layer(state: bytes, layer: int) -> tuple[Image.Image, dict[str, Any]]:
    io = state[statefmt.STATE_IO:statefmt.STATE_PALETTE]
    vram = state[statefmt.STATE_VRAM:statefmt.STATE_IWRAM]
    pal = state[statefmt.STATE_PALETTE:statefmt.STATE_OAM]
    dispcnt = u16(io, 0)
    cnt = u16(io, 8 + layer * 2)
    enabled = bool(dispcnt & (0x100 << layer))
    charblock = (cnt >> 2) & 3
    screenblock = (cnt >> 8) & 31
    image = Image.new("RGB", (240, 160), (0, 0, 0))
    if not enabled:
        return image, {"layer": layer, "enabled": False, "bgcnt": f"0x{cnt:04X}"}
    ink = 0
    for ty in range(20):
        for tx in range(30):
            cell = u16(vram, screenblock * 0x800 + (ty * 32 + tx) * 2)
            tile = cell & 0x03FF
            hflip = bool(cell & 0x400)
            vflip = bool(cell & 0x800)
            bank = (cell >> 12) & 0xF
            raw = vram[charblock * 0x4000 + tile * 32:charblock * 0x4000 + tile * 32 + 32]
            pixels = decode_tile(raw)
            colors = palette_rgb(pal, bank)
            for py in range(8):
                for px in range(8):
                    xx = 7 - px if hflip else px
                    yy = 7 - py if vflip else py
                    value = pixels[yy][xx]
                    if value:
                        ink += 1
                    image.putpixel((tx * 8 + px, ty * 8 + py), colors[value])
    return image, {
        "layer": layer,
        "enabled": True,
        "bgcnt": f"0x{cnt:04X}",
        "charblock": charblock,
        "screenblock": screenblock,
        "ink": ink,
        "dispcnt": f"0x{dispcnt:04X}",
    }


def parse_loose_header(rom: bytes, address: int) -> dict[str, Any] | None:
    off = address - ROM_BASE
    if off < 0 or off + 0x14 > len(rom):
        return None
    kind, pal_count, gfx_rel, pal_rel, anim_count = struct.unpack_from("<5I", rom, off)
    if kind != 0 or pal_count == 0 or pal_count > 16:
        return None
    if not (0x20 <= gfx_rel < pal_rel):
        return None
    gfx_bytes = pal_rel - gfx_rel
    if gfx_bytes % 32 or gfx_bytes > 0x20000:
        return None
    if not (1 <= anim_count <= 64):
        return None
    return {
        "address": f"0x{address:08X}",
        "kind": kind,
        "palette_count": pal_count,
        "graphics_rel": gfx_rel,
        "palette_rel": pal_rel,
        "animation_count": anim_count,
        "source_tiles": gfx_bytes // 32,
        "graphics_offset": off + gfx_rel,
    }


def unique_obj_tiles(state: bytes, rows: list[dict[str, Any]]) -> dict[bytes, list[int]]:
    obj = state[statefmt.STATE_VRAM + statefmt.OBJ_VRAM:statefmt.STATE_IWRAM]
    found: dict[bytes, list[int]] = {}
    for row in rows:
        if int(row["ink"]) == 0:
            continue
        w, h = int(row["width"]), int(row["height"])
        tile0 = int(row["tile"])
        for ty in range(h // 8):
            for tx in range(w // 8):
                tile_id = tile0 + ty * (w // 8) + tx
                raw = bytes(obj[tile_id * 32:(tile_id + 1) * 32])
                if len(raw) != 32 or len(set(raw)) <= 1:
                    continue
                found.setdefault(raw, []).append(tile_id)
    return found


def search_rom_tiles(rom: bytes, tiles: dict[bytes, list[int]], limit_hits: int = 8) -> list[dict[str, Any]]:
    reports = []
    for raw, live_ids in tiles.items():
        hits: list[int] = []
        start = 0
        while len(hits) < limit_hits:
            found = rom.find(raw, start)
            if found < 0:
                break
            hits.append(found)
            start = found + 1
        reports.append({
            "live_obj_tiles": sorted(set(f"0x{x:03X}" for x in live_ids)),
            "inkish": len(set(raw)) > 2,
            "rom_hits": [f"0x{x:08X}" for x in hits],
            "hit_count_capped": len(hits),
        })
    reports.sort(key=lambda r: (len(r["rom_hits"]) == 0, -len(r["live_obj_tiles"])))
    return reports


def cluster_hits(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    offsets: dict[int, int] = defaultdict(int)
    for row in hits:
        for item in row["rom_hits"]:
            off = int(item, 16) & ~0x1F
            offsets[off] += 1
    if not offsets:
        return []
    clustered: list[tuple[int, int, int]] = []
    current_start = None
    current_end = None
    current_count = 0
    for off in sorted(offsets):
        if current_start is None:
            current_start = current_end = off
            current_count = offsets[off]
            continue
        if off <= current_end + 0x800:
            current_end = off
            current_count += offsets[off]
        else:
            clustered.append((current_start, current_end, current_count))
            current_start = current_end = off
            current_count = offsets[off]
    clustered.append((current_start, current_end, current_count))
    clustered.sort(key=lambda item: item[2], reverse=True)
    return [
        {
            "start": f"0x{start:08X}",
            "end": f"0x{end:08X}",
            "matched_tile_occurrences": count,
            "span": end - start + 32,
        }
        for start, end, count in clustered[:12]
    ]


def slot_details(rom: bytes, state: bytes) -> list[dict[str, Any]]:
    slots = remaining.sprite_slots(state)
    obj = state[statefmt.STATE_VRAM + statefmt.OBJ_VRAM:statefmt.STATE_IWRAM]
    rows = []
    for slot in slots:
        address = int(slot["resource"], 16)
        header = parse_loose_header(rom, address)
        info: dict[str, Any] = {**slot}
        if header is None:
            info["header"] = None
            rows.append(info)
            continue
        info["header"] = {k: v for k, v in header.items()}
        graphics = rom[header["graphics_offset"]:header["graphics_offset"] + header["source_tiles"] * 32]
        lookup = {graphics[i * 32:(i + 1) * 32]: i for i in range(header["source_tiles"])}
        live_matches = []
        for tile_id in range(len(obj) // 32):
            raw = bytes(obj[tile_id * 32:(tile_id + 1) * 32])
            if raw in lookup and len(set(raw)) > 1:
                live_matches.append({"obj_tile": f"0x{tile_id:03X}", "source_tile": lookup[raw]})
        info["live_source_matches"] = len(live_matches)
        info["live_source_sample"] = live_matches[:24]
        try:
            _gr, records = sprite.animation_records(rom, address)
            anim = int(slot["animation"])
            if 0 <= anim < len(records):
                blob = b"".join(rec for _off, rec in records[anim:])
                parsed = sprite.parse_animation_oam(blob)
                info["animation_objects"] = [
                    {
                        "index": obj["index"],
                        "x": obj["x"],
                        "y": obj["y"],
                        "size_px": obj["size_px"],
                        "palette_bank": obj["palette_bank"],
                        "tile_start": obj["tile_start"],
                        "tile_count": obj["tile_count"],
                    }
                    for obj in parsed["objects"]
                ]
        except SystemExit:
            info["animation_objects"] = "parse_failed"
        rows.append(info)
    rows.sort(key=lambda r: (-int(r.get("live_source_matches") or 0), r["slot"]))
    return rows


def resource_from_graphics(rom: bytes, graphics_offset: int) -> dict[str, Any] | None:
    for off in range(max(0, graphics_offset - 0x8000), graphics_offset, 4):
        header = parse_loose_header(rom, ROM_BASE + off)
        if header and header["graphics_offset"] == graphics_offset:
            header["pointer_hits"] = pointer_hits(rom, ROM_BASE + off)[:12]
            return header
    return None


def pointer_hits(data: bytes, address: int) -> list[str]:
    needle = struct.pack("<I", address)
    hits = []
    start = 0
    while len(hits) < 16:
        found = data.find(needle, start)
        if found < 0:
            break
        hits.append(f"0x{found:08X}")
        start = found + 1
    return hits


def analyze_state(name: str, path: Path, rom: bytes, jp: bytes) -> dict[str, Any]:
    state, _ = statefmt.parse_png_state(path)
    crc = u32(state, 8)
    parent_crc = binascii.crc32(rom) & 0xFFFFFFFF
    gate(crc == parent_crc, f"{name} CRC 0x{crc:08X} != parent 0x{parent_crc:08X}")
    io = state[statefmt.STATE_IO:statefmt.STATE_PALETTE]
    obj_im, oam_rows = render_obj(state)
    obj_im.save(OUT_DIR / f"{name}_obj.png")
    obj_im.resize((720, 480), Image.Resampling.NEAREST).save(OUT_DIR / f"{name}_obj_x3.png")
    screenshot = Image.open(path).convert("RGB")
    screenshot.save(OUT_DIR / f"{name}_screenshot.png")
    screenshot.resize((720, 480), Image.Resampling.NEAREST).save(OUT_DIR / f"{name}_screenshot_x3.png")
    bg_info = []
    composite = Image.new("RGBA", (240, 160), (0, 0, 0, 255))
    for layer in range(4):
        image, info = render_bg_layer(state, layer)
        image.save(OUT_DIR / f"{name}_bg{layer}.png")
        bg_info.append(info)
        if info.get("enabled"):
            composite.alpha_composite(image.convert("RGBA"))
    composite.alpha_composite(obj_im)
    composite.save(OUT_DIR / f"{name}_composite.png")
    composite.resize((720, 480), Image.Resampling.NEAREST).save(OUT_DIR / f"{name}_composite_x3.png")
    tiles = unique_obj_tiles(state, oam_rows)
    hits = search_rom_tiles(rom, tiles)
    clusters = cluster_hits(hits)
    owners = []
    for cluster in clusters[:6]:
        start = int(cluster["start"], 16)
        aligned = start - (start % 32)
        owner = resource_from_graphics(rom, aligned)
        if owner is None:
            for guess in range(aligned, max(0, aligned - 0x4000), -32):
                owner = resource_from_graphics(rom, guess)
                if owner:
                    break
        owners.append({"cluster": cluster, "resource": owner})
    jp_hits = search_rom_tiles(jp, tiles)
    return {
        "path": advance_relative(path),
        "sha256": sha256(path.read_bytes()),
        "state_crc": f"0x{crc:08X}",
        "dispcnt": f"0x{u16(io, 0):04X}",
        "visible_oam": [
            {k: v for k, v in row.items() if k != "attr0"}
            for row in oam_rows
            if int(row["ink"]) > 8
        ],
        "visible_oam_count": len(oam_rows),
        "ink_oam_count": sum(1 for row in oam_rows if int(row["ink"]) > 8),
        "bg": bg_info,
        "unique_nonblank_obj_tiles": len(tiles),
        "rom_tile_clusters": clusters,
        "cluster_owners": owners,
        "jp_tile_clusters": cluster_hits(jp_hits),
        "sprite_slots": slot_details(rom, state),
        "unmatched_unique_tiles": sum(1 for row in hits if not row["rom_hits"]),
    }


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rom = PARENT.read_bytes()
    jp = ORIGINAL_ROM.read_bytes()
    gate(sha256(jp) == EXPECTED_JP_SHA256, "JP ROM hash drift")
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_turn_ability_overlays_20260905",
        "parent": {"path": advance_relative(PARENT), "sha256": sha256(rom), "size": len(rom)},
        "states": {},
    }
    for name, path in STATES.items():
        gate(path.exists(), f"missing {path}")
        report["states"][name] = analyze_state(name, path, rom, jp)
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {
        "out": advance_relative(OUT_JSON),
        "previews": advance_relative(OUT_DIR),
        "ss2_slots": [
            {k: v for k, v in row.items() if k in {"slot", "resource", "x", "y", "animation", "live_source_matches"}}
            for row in report["states"]["ss2"]["sprite_slots"][:12]
        ],
        "ss3_slots": [
            {k: v for k, v in row.items() if k in {"slot", "resource", "x", "y", "animation", "live_source_matches"}}
            for row in report["states"]["ss3"]["sprite_slots"][:12]
        ],
        "ss2_clusters": report["states"]["ss2"]["rom_tile_clusters"][:6],
        "ss3_clusters": report["states"]["ss3"]["rom_tile_clusters"][:6],
        "ss2_owners": report["states"]["ss2"]["cluster_owners"][:6],
        "ss3_owners": report["states"]["ss3"]["cluster_owners"][:6],
        "ss2_oam": [
            {k: row[k] for k in ("index", "x", "y", "width", "height", "tile", "palette_bank", "ink")}
            for row in report["states"]["ss2"]["visible_oam"]
        ],
        "ss3_oam": [
            {k: row[k] for k in ("index", "x", "y", "width", "height", "tile", "palette_bank", "ink")}
            for row in report["states"]["ss3"]["visible_oam"]
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
