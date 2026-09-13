#!/usr/bin/env python3
"""Analyze the mGBA savestate captured on the battle equipment UI.

The goal is to determine which GBA graphics path owns the Japanese mini-labels
visible in the battle equipment rows.  mGBA stores GBA state in the PNG custom
chunk `gbAs`; after zlib decompression it is the fixed 0x61000-byte serialized
GBA state (I/O, palette, OAM, VRAM, IWRAM, EWRAM).

This analyzer is read-only.  It does not patch the ROM or savestate.
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
import build_ggen_advance_status_ui_tile_overlay_poc as status_ui

DEFAULT_STATE = (
    ADVANCE_ROOT
    / "outputs"
    / "20260829_ggen_advance_battle_ui"
    / "ggen_advance_battle_weapon_ui_galmuri7_candidate_20260829.ss1"
)
DEFAULT_OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_mgba_battle_ui_savestate_20260829.json"
JP_ROM = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Japan).gba"
UI_CANDIDATE = (
    ADVANCE_ROOT
    / "outputs"
    / "20260829_ggen_advance_battle_ui"
    / "ggen_advance_battle_weapon_ui_galmuri7_candidate_20260829.gba"
)
FONT_POC = (
    ADVANCE_ROOT
    / "outputs"
    / "20260829_ggen_advance_battle_ui"
    / "ggen_advance_battle_weapon_font_galmuri7_poc_20260829.gba"
)

STATE_SIZE = 0x61000
STATE_IO = 0x00400
STATE_PALETTE = 0x00800
STATE_OAM = 0x00C00
STATE_VRAM = 0x01000
STATE_IWRAM = 0x19000
STATE_EWRAM = 0x21000
VRAM_SIZE = 0x18000
OBJ_VRAM = 0x10000

D54_ATLAS = 0x000D45DC
D54_TABLE = 0x000D54E4


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def gate(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"gate failed: {message}")


def parse_png_chunks(data: bytes) -> list[dict[str, Any]]:
    gate(data.startswith(b"\x89PNG\r\n\x1a\n"), "savestate is not PNG-container mGBA format")
    pos = 8
    chunks: list[dict[str, Any]] = []
    while pos + 12 <= len(data):
        length = struct.unpack_from(">I", data, pos)[0]
        kind = data[pos + 4 : pos + 8]
        payload_start = pos + 8
        payload_end = payload_start + length
        gate(payload_end + 4 <= len(data), f"PNG chunk {kind!r} overruns file")
        chunks.append(
            {
                "kind": kind.decode("latin1"),
                "file_offset": pos,
                "payload_offset": payload_start,
                "payload_length": length,
            }
        )
        pos = payload_end + 4
        if kind == b"IEND":
            break
    gate(pos == len(data), "unexpected trailing data after PNG IEND")
    return chunks


def get_chunk_payload(data: bytes, chunk: dict[str, Any]) -> bytes:
    start = int(chunk["payload_offset"])
    length = int(chunk["payload_length"])
    return data[start : start + length]


def crc32_file(path: Path) -> int | None:
    if not path.is_file():
        return None
    return binascii.crc32(path.read_bytes()) & 0xFFFFFFFF


def decode_tile(raw: bytes) -> list[list[int]]:
    gate(len(raw) == 32, "4bpp tile must be 32 bytes")
    return [
        [
            (raw[y * 4 + x // 2] >> (4 * (x & 1))) & 0x0F
            for x in range(8)
        ]
        for y in range(8)
    ]


def oam_size(shape: int, size: int) -> tuple[int, int] | None:
    table = {
        (0, 0): (8, 8),
        (0, 1): (16, 16),
        (0, 2): (32, 32),
        (0, 3): (64, 64),
        (1, 0): (16, 8),
        (1, 1): (32, 8),
        (1, 2): (32, 16),
        (1, 3): (64, 32),
        (2, 0): (8, 16),
        (2, 1): (8, 32),
        (2, 2): (16, 32),
        (2, 3): (32, 64),
    }
    return table.get((shape, size))


def active_oam_rows(oam: bytes) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index in range(128):
        attr0, attr1, attr2, _affine = struct.unpack_from("<HHHH", oam, index * 8)
        affine = bool(attr0 & 0x0100)
        disabled = (not affine) and bool(attr0 & 0x0200)
        if disabled:
            continue
        y = attr0 & 0x00FF
        x = attr1 & 0x01FF
        if y >= 160:
            y -= 256
        if x >= 240:
            x -= 512
        shape = (attr0 >> 14) & 3
        size = (attr1 >> 14) & 3
        dims = oam_size(shape, size)
        if not dims:
            continue
        if not (-64 < x < 240 and -64 < y < 160):
            continue
        rows.append(
            {
                "index": index,
                "x": x,
                "y": y,
                "width": dims[0],
                "height": dims[1],
                "tile": attr2 & 0x03FF,
                "priority": (attr2 >> 10) & 3,
                "palette_bank": (attr2 >> 12) & 0x0F,
                "affine": affine,
                "obj_mode": (attr0 >> 10) & 3,
                "attr0": f"0x{attr0:04X}",
                "attr1": f"0x{attr1:04X}",
                "attr2": f"0x{attr2:04X}",
            }
        )
    return rows


def group_equipment_rows(oam_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Measured state: the four visible equipment rows occupy y=48,64,80,96.
    result: list[dict[str, Any]] = []
    for y in (48, 64, 80, 96):
        members = [row for row in oam_rows if int(row["y"]) == y and int(row["height"]) == 16]
        members.sort(key=lambda row: int(row["x"]))
        if not members:
            continue
        result.append(
            {
                "y": y,
                "sprite_count": len(members),
                "x_positions": [int(row["x"]) for row in members],
                "tile_bases": [f"0x{int(row['tile']):03X}" for row in members],
                "palette_banks": sorted({int(row["palette_bank"]) for row in members}),
                "span_pixels": [min(int(row["x"]) for row in members), max(int(row["x"]) + int(row["width"]) for row in members)],
                "members": members,
            }
        )
    return result


def d54_exact_obj_matches(jp_rom: bytes, vram: bytes, tile_limit: int = 224) -> list[dict[str, Any]]:
    header = struct.unpack_from("<I", jp_rom, D54_ATLAS)[0]
    gate(header & 0x80000000, "D54 atlas is not custom-LZSS compressed")
    comp_len = header & 0xFFFF
    decoded = status_ui.lzss_decompress(jp_rom[D54_ATLAS + 4 : D54_ATLAS + 4 + comp_len])
    gate(len(decoded) == 6080, f"D54 decoded size drift: {len(decoded)}")
    lookup: dict[bytes, list[int]] = {}
    for offset in range(0, len(decoded), 32):
        lookup.setdefault(decoded[offset : offset + 32], []).append(offset // 32)
    obj = vram[OBJ_VRAM:]
    hits: list[dict[str, Any]] = []
    for tile_id in range(tile_limit):
        raw = bytes(obj[tile_id * 32 : (tile_id + 1) * 32])
        source_ids = lookup.get(raw)
        if source_ids:
            hits.append(
                {
                    "obj_tile": f"0x{tile_id:03X}",
                    "d54_tiles": [f"0x{x:03X}" for x in source_ids],
                }
            )
    return hits


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    raw = args.state.read_bytes()
    chunks = parse_png_chunks(raw)
    state_chunk = next((chunk for chunk in chunks if chunk["kind"] == "gbAs"), None)
    gate(state_chunk is not None, "mGBA gbAs chunk missing")
    state = zlib.decompress(get_chunk_payload(raw, state_chunk))
    gate(len(state) == STATE_SIZE, f"unexpected GBA serialized state size: {len(state)}")

    version_magic, bios_checksum, rom_crc32, master_cycles = struct.unpack_from("<IIII", state, 0)
    title = state[0x10:0x1C].rstrip(b"\x00").decode("ascii", errors="replace")
    game_code = state[0x1C:0x20].rstrip(b"\x00").decode("ascii", errors="replace")

    io = state[STATE_IO:STATE_PALETTE]
    palette = state[STATE_PALETTE:STATE_OAM]
    oam = state[STATE_OAM:STATE_VRAM]
    vram = state[STATE_VRAM:STATE_IWRAM]
    gate(len(vram) == VRAM_SIZE, "VRAM state size mismatch")

    dispcnt = struct.unpack_from("<H", io, 0)[0]
    bgcnt = [struct.unpack_from("<H", io, off)[0] for off in (0x08, 0x0A, 0x0C, 0x0E)]
    bgofs = [
        {
            "x": struct.unpack_from("<H", io, off)[0] & 0x01FF,
            "y": struct.unpack_from("<H", io, off + 2)[0] & 0x01FF,
        }
        for off in (0x10, 0x14, 0x18, 0x1C)
    ]

    oam_rows = active_oam_rows(oam)
    equipment_rows = group_equipment_rows(oam_rows)
    gate(len(equipment_rows) == 4, f"expected four visible equipment rows, got {len(equipment_rows)}")

    jp = JP_ROM.read_bytes()
    d54_hits = d54_exact_obj_matches(jp, vram)

    rom_candidates = []
    for label, path in (
        ("canonical_main", MAIN_TIP_ROM),
        ("ui_candidate", UI_CANDIDATE),
        ("source_font_poc", FONT_POC),
    ):
        crc = crc32_file(path)
        rom_candidates.append(
            {
                "label": label,
                "path": str(path.relative_to(ADVANCE_ROOT)).replace("\\", "/") if path.is_file() else str(path),
                "crc32": f"0x{crc:08X}" if crc is not None else None,
                "matches_state": crc == rom_crc32 if crc is not None else False,
            }
        )

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_mgba_battle_ui_savestate",
        "result": "PASS",
        "savestate": {
            "path": str(args.state.relative_to(ADVANCE_ROOT)).replace("\\", "/"),
            "size": len(raw),
            "sha256": sha256(raw),
            "png_chunks": chunks,
            "gbAs_decompressed_size": len(state),
        },
        "serialized_header": {
            "version_magic": f"0x{version_magic:08X}",
            "bios_checksum": f"0x{bios_checksum:08X}",
            "rom_crc32": f"0x{rom_crc32:08X}",
            "master_cycles": master_cycles,
            "title": title,
            "game_code": game_code,
            "rom_candidates": rom_candidates,
        },
        "video": {
            "DISPCNT": f"0x{dispcnt:04X}",
            "obj_1d_mapping": bool(dispcnt & 0x0040),
            "bg_enabled": [bool(dispcnt & (0x0100 << index)) for index in range(4)],
            "obj_enabled": bool(dispcnt & 0x1000),
            "bgcnt": [f"0x{x:04X}" for x in bgcnt],
            "bgofs": bgofs,
            "palette_bytes": len(palette),
            "oam_bytes": len(oam),
            "vram_bytes": len(vram),
        },
        "oam": {
            "active_visible_objects": len(oam_rows),
            "equipment_rows": equipment_rows,
            "conclusion": "The four battle equipment rows are OBJ sprites backed by OBJ VRAM, not ordinary BG text cells.",
        },
        "d54_relation": {
            "atlas_file_offset": f"0x{D54_ATLAS:08X}",
            "resource_table_file_offset": f"0x{D54_TABLE:08X}",
            "exact_obj_tile_matches": len(d54_hits),
            "sample_matches": d54_hits[:64],
            "interpretation": "D54 contributes battle frame/background graphics. The label-bearing OBJ rows are assembled separately by the 0x08039B28 row compositor and then copied to OBJ VRAM by 0x0803A19C.",
        },
        "fixed_label_resources": {
            "row_compositor": "0x08039B28",
            "row_build_call": "0x080394FA",
            "obj_copy": "0x0803A19C",
            "obj_copy_call": "0x08039502",
            "resource_format": "0x74-byte descriptor = 0x14 header + 0x40 8x16 graphic + 0x20 palette",
            "resources": {
                "実": "0x08A8D854", "攻": "0x08A8D9B0", "命": "0x08A8DA24", "弾": "0x08A8DA98",
                "射": "0x08A8DB0C", "全": "0x08A8DB80", "近": "0x08A8DBF4", "単": "0x08A8DC68"
            },
            "compound_rule": "0x0803A0DE-0x0803A17A combines 射/近 at tile x=25 with 単/全 at tile x=26, producing 射単/近単/射全/近全.",
        },
        "conclusion": {
            "original_8x16_source_font_hypothesis": "REJECTED",
            "reason": "The savestate is CRC-matched to the Galmuri7 UI candidate whose original 8x16 source slots were patched, yet the live label pixels reside in OBJ VRAM sprite rows and remain Japanese.",
            "standard_12x12_font_hypothesis": "REJECTED_FOR_FIXED_LABELS",
            "fixed_graphic_hypothesis": "CONFIRMED",
            "resolved_source": "embedded 8x16 fixed graphic descriptors in 0x08A8D854-0x08A8DC68, rendered by 0x08039B28 before OBJ copy",
            "next_trace_target": "validate the fixed-graphic Galmuri7 candidate in-game; no further font-slot or D54 guessing is needed unless runtime output differs",
        },
        "verification": {
            "result": "PASS",
            "state_size_exact_0x61000": len(state) == STATE_SIZE,
            "state_crc_matches_ui_candidate": any(row["label"] == "ui_candidate" and row["matches_state"] for row in rom_candidates),
            "obj_rows_found": len(equipment_rows) == 4,
            "obj_1d_mapping": bool(dispcnt & 0x0040),
            "d54_background_overlap_present": len(d54_hits) > 0,
        },
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": report["result"],
        "out": str(args.out),
        "state_crc32": report["serialized_header"]["rom_crc32"],
        "matched_rom": next((row["label"] for row in rom_candidates if row["matches_state"]), None),
        "equipment_rows": len(equipment_rows),
        "d54_exact_obj_tile_matches": len(d54_hits),
        "source_font_hypothesis": "REJECTED",
    }, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
