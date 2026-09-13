#!/usr/bin/env python3
"""Trace the live battle-forecast mini-labels from an mGBA main-TIP state.

This is the runtime counterpart to the older static forecast scan.  It proves
which BG layer owns the visible 実/攻/命 badges, resolves the BG2 tilemap back to
the source graphic resource, and verifies the ROM call/literal that draws that
resource.  The analyzer is read-only.
"""
from __future__ import annotations

import argparse
import binascii
import hashlib
import json
import struct
import zlib
from pathlib import Path
from typing import Any

from ggen_advance_project_paths import ADVANCE_ROOT, MAIN_TIP_ROM

ROM_BASE = 0x08000000
STATE_SIZE = 0x61000
STATE_IO = 0x00400
STATE_PALETTE = 0x00800
STATE_OAM = 0x00C00
STATE_VRAM = 0x01000
STATE_IWRAM = 0x19000
VRAM_SIZE = 0x18000

JP_ROM = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Japan).gba"
DEFAULT_STATE = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).ss1"
# The state was captured from the main TIP immediately before this follow-up
# was promoted.  Promotion backed that exact ROM up here, so the runtime trace
# remains reproducible even though the canonical root ROM now has a new CRC.
CAPTURED_MAIN_ROM = (
    ADVANCE_ROOT
    / "integrated"
    / "main_tip"
    / "backups"
    / "20260830T001604Z_battle_forecast_bg2_runtime_rows_galmuri7_20260830"
    / "SD Gundam GGeneration Advance (Korean).gba"
)
DEFAULT_OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_battle_forecast_main_state_20260830.json"
EXPECTED_CAPTURED_MAIN_SHA256 = "a3b1c5e4566762f5e486364ff4abace675548f29a34215bd81604925772d01e1"
EXPECTED_JP_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"

DRAW_FUNCTION = 0x08001C50
BASE_DRAW_CALL = 0x0803860E
BASE_DEST_LDR = 0x00038606
BASE_RESOURCE_LDR = 0x0003860C
BASE_DEST_LITERAL = 0x000386A4
BASE_RESOURCE_LITERAL = 0x000386A8
BASE_DEST = 0x0600E800
BASE_RESOURCE = 0x00A85FB4

# Conditional 24x2 row variants selected immediately afterwards.  Their
# 攻/命 cells are byte-identical to the base row and need the same patch.
VARIANT_POINTER_LITERALS = {
    "default": (0x00038740, 0x00A8642C),
    "branch_a": (0x000386B8, 0x00A8661C),
    "branch_b": (0x0003873C, 0x00A8680C),
}

# Live screen coordinates in the supplied main-TIP state.  BG2 rows 3/4 are
# the two 8-pixel halves of the 16-pixel badge row.
LIVE_LABELS = {
    "실": {"source": "実", "screen_x": 1, "resource_x": 1, "role": "physical_type"},
    "공": {"source": "攻", "screen_x": 14, "resource_x": 14, "role": "attack"},
    "명": {"source": "命", "screen_x": 21, "resource_x": 21, "role": "hit"},
}


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def decode_thumb_bl(data: bytes, address: int) -> int:
    offset = address - ROM_BASE
    hi = u16(data, offset)
    lo = u16(data, offset + 2)
    gate(hi & 0xF800 == 0xF000 and lo & 0xF800 == 0xF800, f"not a Thumb BL at 0x{address:08X}")
    displacement = ((hi & 0x07FF) << 12) | ((lo & 0x07FF) << 1)
    if displacement & 0x00400000:
        displacement -= 0x00800000
    return address + 4 + displacement


def literal_target(data: bytes, instruction_offset: int) -> tuple[int, int, int]:
    ins = u16(data, instruction_offset)
    gate(ins & 0xF800 == 0x4800, f"not an LDR literal at 0x{ROM_BASE + instruction_offset:08X}")
    register = (ins >> 8) & 7
    pc = (ROM_BASE + instruction_offset + 4) & ~3
    literal_address = pc + ((ins & 0xFF) << 2)
    literal_offset = literal_address - ROM_BASE
    return register, literal_offset, u32(data, literal_offset)


def parse_png_state(path: Path) -> tuple[bytes, list[dict[str, Any]]]:
    data = path.read_bytes()
    gate(data.startswith(b"\x89PNG\r\n\x1a\n"), "savestate is not mGBA PNG-container format")
    pos = 8
    chunks: list[dict[str, Any]] = []
    state = None
    while pos + 12 <= len(data):
        length = struct.unpack_from(">I", data, pos)[0]
        kind = data[pos + 4 : pos + 8]
        payload = data[pos + 8 : pos + 8 + length]
        chunks.append({"kind": kind.decode("latin1"), "file_offset": pos, "payload_length": length})
        if kind == b"gbAs":
            state = zlib.decompress(payload)
        pos += 12 + length
        if kind == b"IEND":
            break
    gate(pos == len(data), "unexpected bytes after IEND")
    gate(state is not None, "mGBA gbAs chunk missing")
    gate(len(state) == STATE_SIZE, f"unexpected serialized state size: {len(state)}")
    return state, chunks


def parse_tile_resource(data: bytes, offset: int) -> dict[str, Any]:
    kind, dimensions, header_bytes, map_bytes, graphics_rel, graphics_bytes, palette_rel, palette_bytes = struct.unpack_from(
        "<8H", data, offset
    )
    width = dimensions & 0xFF
    height = dimensions >> 8
    gate(kind == 2, f"unexpected resource kind at 0x{offset:08X}: {kind}")
    gate(header_bytes == 0x10, f"unexpected resource header size at 0x{offset:08X}")
    gate(map_bytes == width * height * 2, f"tilemap byte count mismatch at 0x{offset:08X}")
    gate(graphics_bytes % 32 == 0, f"graphics are not tile aligned at 0x{offset:08X}")
    tilemap = list(struct.unpack_from("<" + "H" * (width * height), data, offset + header_bytes))
    return {
        "offset": offset,
        "width": width,
        "height": height,
        "header_bytes": header_bytes,
        "map_bytes": map_bytes,
        "graphics_rel": graphics_rel,
        "graphics_offset": offset + graphics_rel,
        "graphics_bytes": graphics_bytes,
        "palette_rel": palette_rel,
        "palette_offset": offset + palette_rel,
        "palette_bytes": palette_bytes,
        "tilemap": tilemap,
    }


def resource_cell_offsets(resource: dict[str, Any], x: int, top_y: int = 1) -> tuple[int, int, int, int]:
    width = int(resource["width"])
    tilemap = resource["tilemap"]
    top_entry = int(tilemap[top_y * width + x])
    bottom_entry = int(tilemap[(top_y + 1) * width + x])
    top_tile = top_entry & 0x03FF
    bottom_tile = bottom_entry & 0x03FF
    graphics = int(resource["graphics_offset"])
    return top_tile, bottom_tile, graphics + top_tile * 32, graphics + bottom_tile * 32


def bg_map_offset(screen_base: int, size: int, x: int, y: int) -> int:
    # Text BG sizes: 0=32x32, 1=64x32, 2=32x64, 3=64x64.  Screen blocks
    # are laid out in 32x32 chunks.
    block_x = x // 32
    block_y = y // 32
    if size == 0:
        gate(block_x == 0 and block_y == 0, "BG coordinate outside 32x32 map")
        block = 0
    elif size == 1:
        gate(block_y == 0 and block_x < 2, "BG coordinate outside 64x32 map")
        block = block_x
    elif size == 2:
        gate(block_x == 0 and block_y < 2, "BG coordinate outside 32x64 map")
        block = block_y
    else:
        gate(block_x < 2 and block_y < 2, "BG coordinate outside 64x64 map")
        block = block_y * 2 + block_x
    local = (y & 31) * 32 + (x & 31)
    return screen_base + block * 0x800 + local * 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--main", type=Path, default=CAPTURED_MAIN_ROM)
    parser.add_argument("--jp", type=Path, default=JP_ROM)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    state, chunks = parse_png_state(args.state)
    main_rom = args.main.read_bytes()
    jp = args.jp.read_bytes()
    gate(sha256(jp) == EXPECTED_JP_SHA256, f"unexpected Japanese ROM hash: {sha256(jp)}")
    gate(len(main_rom) == 32 * 1024 * 1024, f"unexpected captured main TIP size: {len(main_rom)}")
    gate(sha256(main_rom) == EXPECTED_CAPTURED_MAIN_SHA256, f"unexpected captured main TIP hash: {sha256(main_rom)}")

    state_crc = u32(state, 0x08)
    main_crc = binascii.crc32(main_rom) & 0xFFFFFFFF
    gate(state_crc == main_crc, f"state ROM CRC 0x{state_crc:08X} != main TIP CRC 0x{main_crc:08X}")

    io = state[STATE_IO:STATE_PALETTE]
    vram = state[STATE_VRAM:STATE_IWRAM]
    gate(len(vram) == VRAM_SIZE, "VRAM state size mismatch")
    dispcnt = u16(io, 0)
    gate((dispcnt & 7) == 0, f"forecast state is not GBA mode 0: DISPCNT=0x{dispcnt:04X}")
    gate(bool(dispcnt & 0x0400), "BG2 is not enabled")

    bg2cnt = u16(io, 0x0C)
    bg2_charbase = ((bg2cnt >> 2) & 3) * 0x4000
    bg2_screenbase = ((bg2cnt >> 8) & 31) * 0x800
    bg2_size = (bg2cnt >> 14) & 3
    gate(bg2_charbase == 0, f"unexpected BG2 charbase: 0x{bg2_charbase:04X}")
    gate(bg2_screenbase == 0xE800, f"unexpected BG2 screenbase: 0x{bg2_screenbase:04X}")
    gate(bg2_size == 1, f"unexpected BG2 map size code: {bg2_size}")

    resource = parse_tile_resource(jp, BASE_RESOURCE)
    gate((resource["width"], resource["height"]) == (25, 4), "base forecast row dimensions drift")

    dest_reg, dest_pool, dest_value = literal_target(jp, BASE_DEST_LDR)
    resource_reg, resource_pool, resource_value = literal_target(jp, BASE_RESOURCE_LDR)
    gate(dest_pool == BASE_DEST_LITERAL and dest_value == BASE_DEST, "BG2 destination literal drift")
    gate(resource_pool == BASE_RESOURCE_LITERAL and resource_value == ROM_BASE + BASE_RESOURCE, "forecast row resource literal drift")
    gate(decode_thumb_bl(jp, BASE_DRAW_CALL) == DRAW_FUNCTION, "forecast base draw call drift")

    variant_literals = []
    for name, (pool, expected_offset) in VARIANT_POINTER_LITERALS.items():
        value = u32(jp, pool)
        gate(value == ROM_BASE + expected_offset, f"forecast variant pointer drift: {name}")
        variant = parse_tile_resource(jp, expected_offset)
        gate((variant["width"], variant["height"]) == (24, 2), f"forecast variant dimensions drift: {name}")
        variant_literals.append({"name": name, "literal_file_offset": f"0x{pool:08X}", "resource": f"0x{value:08X}"})

    live = []
    for translation, spec in LIVE_LABELS.items():
        x = int(spec["screen_x"])
        top_map_off = bg_map_offset(bg2_screenbase, bg2_size, x, 3)
        bottom_map_off = bg_map_offset(bg2_screenbase, bg2_size, x, 4)
        top_entry = u16(vram, top_map_off)
        bottom_entry = u16(vram, bottom_map_off)
        top_live_tile = top_entry & 0x03FF
        bottom_live_tile = bottom_entry & 0x03FF
        top_live = bytes(vram[bg2_charbase + top_live_tile * 32 : bg2_charbase + (top_live_tile + 1) * 32])
        bottom_live = bytes(vram[bg2_charbase + bottom_live_tile * 32 : bg2_charbase + (bottom_live_tile + 1) * 32])

        src_top_tile, src_bottom_tile, src_top_off, src_bottom_off = resource_cell_offsets(resource, int(spec["resource_x"]))
        source_top = jp[src_top_off : src_top_off + 32]
        source_bottom = jp[src_bottom_off : src_bottom_off + 32]
        gate(top_live == source_top, f"live BG2 top tile does not match source resource: {spec['source']}")
        gate(bottom_live == source_bottom, f"live BG2 bottom tile does not match source resource: {spec['source']}")
        live.append(
            {
                "source": spec["source"],
                "translation": translation,
                "role": spec["role"],
                "screen": {"x_tile": x, "top_y_tile": 3, "bottom_y_tile": 4},
                "live_bg2_entries": [f"0x{top_entry:04X}", f"0x{bottom_entry:04X}"],
                "live_vram_tile_ids": [f"0x{top_live_tile:03X}", f"0x{bottom_live_tile:03X}"],
                "source_resource_tile_ids": [src_top_tile, src_bottom_tile],
                "source_file_offsets": [f"0x{src_top_off:08X}", f"0x{src_bottom_off:08X}"],
                "top_sha256": sha256(top_live),
                "bottom_sha256": sha256(bottom_live),
                "exact_live_match": True,
            }
        )

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_battle_forecast_main_state_runtime_trace",
        "result": "PASS",
        "savestate": {
            "path": str(args.state.relative_to(ADVANCE_ROOT)).replace("\\", "/") if args.state.is_relative_to(ADVANCE_ROOT) else str(args.state),
            "sha256": sha256(args.state.read_bytes()),
            "png_chunks": chunks,
            "serialized_size": len(state),
            "rom_crc32": f"0x{state_crc:08X}",
        },
        "captured_main_tip": {
            "path": str(args.main.relative_to(ADVANCE_ROOT)).replace("\\", "/") if args.main.is_relative_to(ADVANCE_ROOT) else str(args.main),
            "sha256": sha256(main_rom),
            "crc32": f"0x{main_crc:08X}",
            "state_crc_matches": True,
            "note": "This is the pre-follow-up main TIP backed up during promotion; the root canonical ROM now has the follow-up patch.",
        },
        "video": {
            "DISPCNT": f"0x{dispcnt:04X}",
            "BG2CNT": f"0x{bg2cnt:04X}",
            "owner": "BG2 text background",
            "charbase_vram_offset": f"0x{bg2_charbase:05X}",
            "screenbase_vram_offset": f"0x{bg2_screenbase:05X}",
            "map_size_code": bg2_size,
        },
        "runtime_call_path": {
            "draw_function": f"0x{DRAW_FUNCTION:08X}",
            "base_destination_load": f"0x{ROM_BASE + BASE_DEST_LDR:08X} -> pool 0x{BASE_DEST_LITERAL:08X} -> 0x{BASE_DEST:08X}",
            "base_resource_load": f"0x{ROM_BASE + BASE_RESOURCE_LDR:08X} -> pool 0x{BASE_RESOURCE_LITERAL:08X} -> 0x{ROM_BASE + BASE_RESOURCE:08X}",
            "base_draw_call": f"0x{BASE_DRAW_CALL:08X} -> 0x{DRAW_FUNCTION:08X}",
            "ldr_registers": {"destination": dest_reg, "resource": resource_reg},
            "conditional_row_variants": variant_literals,
        },
        "base_resource": {
            "address": f"0x{ROM_BASE + BASE_RESOURCE:08X}",
            "file_offset": f"0x{BASE_RESOURCE:08X}",
            "dimensions_tiles": [resource["width"], resource["height"]],
            "graphics_file_offset": f"0x{resource['graphics_offset']:08X}",
            "graphics_bytes": resource["graphics_bytes"],
            "palette_file_offset": f"0x{resource['palette_offset']:08X}",
        },
        "live_labels": live,
        "conclusion": {
            "previous_A8C004_only_hypothesis": "INSUFFICIENT_FOR_VISIBLE_TOP_BAR",
            "visible_top_bar_owner": "0x08A85FB4 drawn to BG2 by 0x08001C50",
            "visible_badges_proven": ["実", "攻", "命"],
            "patch_strategy": "patch the source cells in 0x08A85FB4 and matching conditional row variants; separately repair the interleaved A8C004 raw-cell matrix",
        },
        "verification": {
            "result": "PASS",
            "state_crc_matches_main_tip": True,
            "bg2_owner_verified": True,
            "base_resource_literal_verified": True,
            "base_draw_call_verified": True,
            "all_three_live_badges_byte_match_base_resource": len(live) == 3 and all(row["exact_live_match"] for row in live),
            "conditional_variant_literals_verified": len(variant_literals) == 3,
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "out": str(args.out),
        "state_crc32": f"0x{state_crc:08X}",
        "main_sha256": sha256(main_rom),
        "owner": "BG2 / 0x08A85FB4",
        "live_labels": [(row["source"], row["translation"], row["source_file_offsets"]) for row in live],
    }, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
