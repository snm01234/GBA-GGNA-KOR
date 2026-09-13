#!/usr/bin/env python3
"""Prove the unit-list N-tile owner and re-derive the 所有数 plaque source.

JP/KO ss1 contrast showed the visible MC Gundam N is the 8x8 suffix/detail
cell, not the 8x16 C439 持 glyph.  This analyzer checks whether current main
still redirects that 1x1 owner to the Korean 지 clones, and whether the
所有数 chrome belongs to a nearby sprite/BG package.
"""
from __future__ import annotations

import binascii
import hashlib
import json
import struct
import sys
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_action_graphics_scan_20260830 as lz
import analyze_ggen_advance_develop_menu_buttons_state_20260901 as pkg
import analyze_ggen_advance_intermission_cycle_states_20260830 as bgutil
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
from ggen_advance_project_paths import (
    ADVANCE_ROOT,
    MAIN_TIP_MANIFEST,
    MAIN_TIP_ROM,
    ORIGINAL_ROM,
    advance_relative,
)

JP_STATE = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Japan).ss1"
KO_STATE = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).ss1"
OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_n_tile_rollback_and_owned_source_20260903.json"

ROM_BASE = 0x08000000
EXPECTED_JP_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"

N_REDIRECTS = {
    "normal_B": {
        "original": 0x08C491C0,
        "clone": 0x09280000,
        "literals": (0x080752F0, 0x08075458),
    },
    "focus_A": {
        "original": 0x08C491F4,
        "clone": 0x09280040,
        "literals": (0x080758F4, 0x08075A5C),
    },
}
HOLD_REDIRECTS = {
    "normal_B": {
        "original": 0x08C490B8,
        "korean": 0x08C43954,
        "literals": (0x080752E8, 0x08075450),
    },
    "focus_A": {
        "original": 0x08C4910C,
        "korean": 0x08C439A8,
        "literals": (0x080758EC, 0x08075A54),
    },
}
SUPPLY_RESOURCE = 0x08C4654C
CHROME_TILE = 0x00C47D50


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def u16(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def decode_desc(rom: bytes, address: int) -> dict[str, Any]:
    off = address - ROM_BASE
    flags = rom[off]
    width, height = rom[off + 2], rom[off + 3]
    gfx_rel = u16(rom, off + 8)
    gfx_len = u16(rom, off + 10)
    body = rom[off + gfx_rel : off + gfx_rel + gfx_len]
    decoded = lz.lzss_decompress(body) if flags & 0x10 else bytes(body)
    return {
        "address": f"0x{address:08X}",
        "flags": flags,
        "size": [width, height],
        "decoded_len": len(decoded),
        "decoded_sha256": sha256(decoded),
        "decoded": decoded,
    }


def pointer_map(rom: bytes, spec: dict[str, Any]) -> dict[str, Any]:
    values = {f"0x{addr:08X}": f"0x{u32(rom, addr - ROM_BASE):08X}" for addr in spec["literals"]}
    current = {u32(rom, addr - ROM_BASE) for addr in spec["literals"]}
    return {
        "literals": values,
        "unanimous": len(current) == 1,
        "value": f"0x{next(iter(current)):08X}" if len(current) == 1 else sorted(f"0x{x:08X}" for x in current),
        "points_to_original": current == {spec.get("original")},
        "points_to_clone": current == {spec["clone"]} if "clone" in spec else False,
        "points_to_korean": current == {spec["korean"]} if "korean" in spec else False,
    }


def bg_tile(state: bytes, layer: int, tile: int) -> bytes:
    info = bgutil.bg_info(state, layer)
    vram = state[statefmt.STATE_VRAM : statefmt.STATE_IWRAM]
    off = info["char_base"] + tile * 32
    return bytes(vram[off : off + 32])


def map_tile(state: bytes, layer: int, x: int, y: int) -> int:
    info = bgutil.bg_info(state, layer)
    vram = state[statefmt.STATE_VRAM : statefmt.STATE_IWRAM]
    return bgutil.map_entry(vram, info["screen_base"], info["size"], x, y) & 0x3FF


def ascii_tile(raw: bytes) -> list[str]:
    rows = []
    for y in range(8):
        line = []
        for x in range(8):
            packed = raw[y * 4 + (x >> 1)]
            value = (packed >> (4 * (x & 1))) & 0xF
            line.append("." if value == 0 else format(value, "X"))
        rows.append("".join(line))
    return rows


def find_package_covering(rom: bytes, file_off: int) -> dict[str, Any] | None:
    """Scan kind0/6-palette sprite headers whose graphics span file_off."""
    for off in range(0, min(len(rom), 0x01000000) - 0x20, 4):
        if u32(rom, off) != 0 or u32(rom, off + 4) != 6:
            continue
        graphics_rel = u32(rom, off + 8)
        palette_rel = u32(rom, off + 0x0C)
        anim_count = u32(rom, off + 0x10)
        if not (1 <= anim_count <= 24):
            continue
        if palette_rel <= graphics_rel or (palette_rel - graphics_rel) % 32:
            continue
        gfx_start = off + graphics_rel
        gfx_end = off + palette_rel
        if gfx_start <= file_off < gfx_end:
            return {
                "header": f"0x{ROM_BASE + off:08X}",
                "graphics_rel": graphics_rel,
                "palette_rel": palette_rel,
                "animation_count": anim_count,
                "source_tiles": (palette_rel - graphics_rel) // 32,
                "tile_index": (file_off - gfx_start) // 32,
            }
    return None


def bl_targets(rom: bytes, start: int, end: int) -> list[dict[str, str]]:
    rows = []
    addr = start
    while addr + 4 <= end:
        h1, h2 = struct.unpack_from("<HH", rom, addr - ROM_BASE)
        if (h1 & 0xF800) == 0xF000 and (h2 & 0xF800) == 0xF800:
            disp = ((h1 & 0x07FF) << 12) | ((h2 & 0x07FF) << 1)
            if disp & (1 << 22):
                disp -= 1 << 23
            target = (addr + 4 + disp) & 0xFFFFFFFF
            rows.append({"from": f"0x{addr:08X}", "to": f"0x{target:08X}"})
            addr += 4
            continue
        addr += 2
    return rows


def main() -> int:
    jp = ORIGINAL_ROM.read_bytes()
    ko = MAIN_TIP_ROM.read_bytes()
    manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(jp) == EXPECTED_JP_SHA256, "JP ROM hash drift")
    gate(sha256(ko) == manifest["sha256"], "main TIP hash drift")
    jp_state, _ = statefmt.parse_png_state(JP_STATE)
    ko_state, _ = statefmt.parse_png_state(KO_STATE)
    gate(u32(jp_state, 8) == (binascii.crc32(jp) & 0xFFFFFFFF), "JP state CRC mismatch")
    gate(u32(ko_state, 8) == (binascii.crc32(ko) & 0xFFFFFFFF), "KO state CRC mismatch")

    n_jp = {name: pointer_map(jp, spec) for name, spec in N_REDIRECTS.items()}
    n_ko = {name: pointer_map(ko, spec) for name, spec in N_REDIRECTS.items()}
    hold_ko = {name: pointer_map(ko, spec) for name, spec in HOLD_REDIRECTS.items()}
    gate(all(row["points_to_original"] for row in n_jp.values()), "JP N literals drifted")
    gate(all(row["points_to_korean"] for row in hold_ko.values()), "current main lost 8x16 持→지 redirects")

    originals = {name: decode_desc(jp, spec["original"]) for name, spec in N_REDIRECTS.items()}
    clones = {name: decode_desc(ko, spec["clone"]) for name, spec in N_REDIRECTS.items()}
    for name in N_REDIRECTS:
        originals[name].pop("decoded")
        clones[name].pop("decoded")
    originals_full = {name: decode_desc(jp, spec["original"]) for name, spec in N_REDIRECTS.items()}
    clones_full = {name: decode_desc(ko, spec["clone"]) for name, spec in N_REDIRECTS.items()}

    # MC is row y=3 in both states. JP focuses MC so N uses focus tiles;
    # KO has MC unfocused. Compare the bottom-right 8x8 of that window.
    jp_n = bg_tile(jp_state, 1, map_tile(jp_state, 1, 15, 4))
    ko_n = bg_tile(ko_state, 1, map_tile(ko_state, 1, 15, 4))
    jp_aile_c = bg_tile(jp_state, 1, map_tile(jp_state, 1, 15, 2))
    ko_aile_c = bg_tile(ko_state, 1, map_tile(ko_state, 1, 15, 2))

    n_live = {
        "jp_mc_bottom_right_sha256": sha256(jp_n),
        "ko_mc_bottom_right_sha256": sha256(ko_n),
        "jp_matches_original_focus_N": jp_n == originals_full["focus_A"]["decoded"],
        "jp_matches_original_normal_N": jp_n == originals_full["normal_B"]["decoded"],
        "ko_matches_clone_normal_ji": ko_n == clones_full["normal_B"]["decoded"],
        "ko_matches_clone_focus_ji": ko_n == clones_full["focus_A"]["decoded"],
        "ko_matches_original_N": ko_n in (originals_full["normal_B"]["decoded"], originals_full["focus_A"]["decoded"]),
        "aile_C_jp_equals_ko": jp_aile_c == ko_aile_c,
        "jp_n_ascii": ascii_tile(jp_n),
        "ko_n_ascii": ascii_tile(ko_n),
        "clone_ji_ascii": ascii_tile(clones_full["normal_B"]["decoded"]),
        "original_n_ascii": ascii_tile(originals_full["normal_B"]["decoded"]),
    }

    supply = pkg.parse_resource_header(jp, SUPPLY_RESOURCE)
    gfx_start = (SUPPLY_RESOURCE - ROM_BASE) + supply["graphics_rel"]
    gfx_end = (SUPPLY_RESOURCE - ROM_BASE) + supply["palette_rel"]
    chrome_in_supply = gfx_start <= CHROME_TILE < gfx_end
    covering = find_package_covering(jp, CHROME_TILE)

    # 所有数 interior tiles: prove JP==KO and still have no raw owner.
    interior = [0x0DD, 0x0DE, 0x0DF, 0x0E0, 0x0E1, 0x0E4, 0x0E5, 0x0E6, 0x0E7, 0x0E8]
    interior_rows = []
    for tile in interior:
        jp_raw = bg_tile(jp_state, 2, tile)
        ko_raw = bg_tile(ko_state, 2, tile)
        interior_rows.append({
            "tile": f"0x{tile:03X}",
            "jp_equals_ko": jp_raw == ko_raw,
            "raw_in_jp_rom": jp.find(jp_raw) >= 0,
            "raw_in_main": ko.find(ko_raw) >= 0,
            "sha256": sha256(jp_raw),
        })

    ec0c_bls = bl_targets(jp, 0x0801EC0C, 0x0801F200)

    result = {
        "schema_version": 1,
        "kind": "ggen_advance_n_tile_rollback_and_owned_source_20260903",
        "result": "PASS",
        "n_tile": {
            "identification": "The visible MC Gundam N is the compressed 1x1 C491C0/C491F4 family, misidentified earlier as detail-pane 持 and redirected to Galmuri7 지 clones at 0x09280000/0x09280040.",
            "jp_literals": n_jp,
            "current_main_literals": n_ko,
            "current_main_still_points_to_ji_clones": all(row["points_to_clone"] for row in n_ko.values()),
            "eight_by_sixteen_hold_still_korean": all(row["points_to_korean"] for row in hold_ko.values()),
            "original_descriptors": originals,
            "clone_descriptors": clones,
            "live": n_live,
            "rollback": {
                "method": "restore only the four C491 1x1 literals to 0x08C491C0 / 0x08C491F4",
                "do_not_touch": [
                    "C439 8x16 持→지 payloads",
                    "C490B8/C4910C 8x16 list redirects",
                    "orphan 지 clones at 0x09280000/0x09280040",
                ],
            },
        },
        "owned_count": {
            "jp_ko_interior_identical": all(row["jp_equals_ko"] for row in interior_rows),
            "interior_raw_rom_hits": sum(row["raw_in_jp_rom"] or row["raw_in_main"] for row in interior_rows),
            "interior": interior_rows,
            "chrome_tile": f"0x{CHROME_TILE:08X}",
            "chrome_in_supply_package": chrome_in_supply,
            "supply_graphics_span": [f"0x{gfx_start:08X}", f"0x{gfx_end:08X}"],
            "supply_header": {
                "address": f"0x{SUPPLY_RESOURCE:08X}",
                "animation_count": supply["animation_count"],
                "source_tiles": supply["source_tiles"],
            },
            "package_covering_chrome": covering,
            "ec0c_bl_targets": ec0c_bls,
            "rejected_previous_approaches": [
                "A/B/C global 12x12 font slot replacement",
                "D overlay after 0x0801E8D4 (wrong screenblock 31)",
                "E/finalizer/post-transfer overlays using stale tile IDs 0x0DD..0x10D",
            ],
            "next_owner_search": [
                "Keep the plaque identity as BG2 screenblock 29 chrome pattern, not tile numbers.",
                "If chrome is inside a sprite/BG package, stitch that package and look for a baked 所有数 animation/object distinct from supply animation 8.",
                "If interior glyphs remain absent from every decoded package tile, the compositor that allocates 0x0DD..0x0E8 lives under 0x0801EC0C; patch that producer or its source buffer, not a later VRAM hook.",
            ],
        },
    }
    # Drop decoded blobs already popped; ensure JSON is small.
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {
        "result": "PASS",
        "n_still_redirected_to_ji": result["n_tile"]["current_main_still_points_to_ji_clones"],
        "live_jp_is_original_N": n_live["jp_matches_original_focus_N"] or n_live["jp_matches_original_normal_N"],
        "live_ko_is_ji_clone": n_live["ko_matches_clone_normal_ji"] or n_live["ko_matches_clone_focus_ji"],
        "aile_C_untouched": n_live["aile_C_jp_equals_ko"],
        "owned_jp_ko_identical": result["owned_count"]["jp_ko_interior_identical"],
        "owned_interior_raw_hits": result["owned_count"]["interior_raw_rom_hits"],
        "chrome_in_supply": chrome_in_supply,
        "covering": covering,
        "ec0c_bl_count": len(ec0c_bls),
        "report": advance_relative(OUT),
    }
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
