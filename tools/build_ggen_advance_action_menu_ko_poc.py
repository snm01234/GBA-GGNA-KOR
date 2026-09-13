#!/usr/bin/env python3
"""Build a Korean fixed-word action-menu candidate for G Generation Advance.

Static tracing on 2026-08-30 closed the map action-command family at resource
pointer table 0x080D23E0 / atlas 0x080D0814.  Command ID 0..11 selects
resource[18+id] in the normal state and resource[30+id] in the focus state.
ID (command 4) is already Latin and is intentionally left byte-exact.

This builder does not overwrite the shared original atlas.  It clones the atlas
into expansion space, appends private 4x2 tiles for every translated normal and
focus label, clones only those tilemaps, creates a private 44-entry resource
table, then redirects the three proven table literals.  Original resources and
all non-target table entries remain untouched.
"""
from __future__ import annotations

import argparse
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

import analyze_ggen_advance_action_graphics_scan_20260830 as scan  # noqa: E402
import test_ggen_advance_font_pair as fontpair  # noqa: E402
from ggen_advance_project_paths import ADVANCE_ROOT, FONT_ZIP, MAIN_TIP_MANIFEST, MAIN_TIP_ROM  # noqa: E402

ROM_BASE = 0x08000000
JP_ROM = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Japan).gba"
OUT_DIR = ADVANCE_ROOT / "outputs" / "20260830_ggen_advance_fixed_action_graphics"
OUT = OUT_DIR / "ggen_advance_action_menu_ko_candidate_20260830.gba"
MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_action_menu_ko_candidate_20260830.json"
PREVIEW = OUT_DIR / "ggen_advance_action_menu_ko_preview_20260830.png"

RESOURCE_TABLE = 0x000D23E0
RESOURCE_COUNT = 44
ATLAS_SOURCE = 0x000D0814
TABLE_CONSUMER_LITERALS = (0x00014F20, 0x00015590, 0x00015628)

# Explicit zero-filled expansion allocations.  The preceding approved
# Settings/Suspend follow-up uses 0x01270000/0x01274000.
ATLAS_CLONE = 0x01278000
TABLE_CLONE = 0x0127C000
MAP_CLONE_START = 0x0127C100
ALLOCATION_END = 0x01280000

NORMAL_BASE = 18
FOCUS_BASE = 30
ID_COMMAND = 4
TRANSLATIONS = {
    0: ("移動", "이동"),
    1: ("隊列", "대열"),
    2: ("攻撃", "공격"),
    3: ("間接", "간접"),
    5: ("捕獲", "포획"),
    6: ("変形", "변형"),
    7: ("交信", "교신"),
    8: ("発進", "발진"),
    9: ("確定", "확정"),
    10: ("合体", "합체"),
    11: ("個別", "개별"),
}

# Measured directly from the native resources.  Japanese normal glyph pixels
# are almost entirely index 11 over index-5 panel fill.  Focus glyph pixels are
# index 12 over index-4 fill.  We preserve the native 2px perimeter and repaint
# only the 28x12 interior text plane.
NORMAL_BG = 5
NORMAL_FACE = 11
FOCUS_BG = 4
FOCUS_FACE = 12


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def u16(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def p32(value: int) -> bytes:
    return struct.pack("<I", value)


def align4(value: int) -> int:
    return (value + 3) & ~3


def decode_tile(atlas: bytes | bytearray, tile_id: int) -> list[list[int]]:
    raw = atlas[tile_id * 32 : tile_id * 32 + 32]
    gate(len(raw) == 32, f"tile 0x{tile_id:03X} outside atlas")
    out = [[0] * 8 for _ in range(8)]
    for y in range(8):
        for x in range(8):
            value = raw[y * 4 + x // 2]
            out[y][x] = (value >> (4 * (x & 1))) & 0x0F
    return out


def encode_tile(tile: list[list[int]]) -> bytes:
    gate(len(tile) == 8 and all(len(row) == 8 for row in tile), "tile dimensions drift")
    raw = bytearray(32)
    for y in range(8):
        for x in range(8):
            raw[y * 4 + x // 2] |= (tile[y][x] & 0x0F) << (4 * (x & 1))
    return bytes(raw)


def parse_map(rom: bytes | bytearray, address: int) -> dict:
    off = address - ROM_BASE
    gate(0 <= off + 4 <= len(rom), f"map pointer outside ROM: 0x{address:08X}")
    w, h = rom[off], rom[off + 1]
    reserved = u16(rom, off + 2)
    count = w * h
    gate(count > 0 and off + 4 + count * 2 <= len(rom), f"map overruns ROM: 0x{address:08X}")
    cells = list(struct.unpack_from(f"<{count}H", rom, off + 4))
    return {"offset": off, "width": w, "height": h, "reserved": reserved, "cells": cells}


def stitch_map(atlas: bytes | bytearray, map_obj: dict) -> list[list[int]]:
    w, h = int(map_obj["width"]), int(map_obj["height"])
    pixels = [[0] * (w * 8) for _ in range(h * 8)]
    for ty in range(h):
        for tx in range(w):
            cell = int(map_obj["cells"][ty * w + tx])
            tile = decode_tile(atlas, cell & 0x03FF)
            hflip = bool(cell & 0x0400)
            vflip = bool(cell & 0x0800)
            for yy in range(8):
                sy = 7 - yy if vflip else yy
                for xx in range(8):
                    sx = 7 - xx if hflip else xx
                    pixels[ty * 8 + yy][tx * 8 + xx] = tile[sy][sx]
    return pixels


def render_hangul(text: str, font: fontpair.BdfFont, face: int, background: int, source_pixels: list[list[int]]) -> list[list[int]]:
    gate(len(text) == 2, f"action label must stay two cells: {text!r}")
    gate(len(source_pixels) == 16 and all(len(row) == 32 for row in source_pixels), "action source is not 32x16")
    pixels = [row[:] for row in source_pixels]

    # Preserve the native two-pixel perimeter exactly.  This retains rounded
    # corners/highlight/shadow in both normal and focus states while removing
    # every Japanese glyph pixel from the central 28x12 plane.
    for y in range(2, 14):
        for x in range(2, 30):
            pixels[y][x] = background

    x0, y0 = 4, 2
    for index, char in enumerate(text):
        glyph = fontpair.render_12x12_basic(char, font)
        for y in range(12):
            for x in range(12):
                if glyph.getpixel((x, y)):
                    pixels[y0 + y][x0 + index * 12 + x] = face
    return pixels


def append_private_tiles(atlas: bytearray, pixels: list[list[int]]) -> tuple[list[int], list[bytes]]:
    gate(len(pixels) == 16 and all(len(row) == 32 for row in pixels), "private label is not 32x16")
    ids: list[int] = []
    payloads: list[bytes] = []
    for ty in range(2):
        for tx in range(4):
            tile = [pixels[ty * 8 + y][tx * 8 : tx * 8 + 8] for y in range(8)]
            payload = encode_tile(tile)
            tile_id = len(atlas) // 32
            gate(tile_id < 0x400, "private action tile exceeds 10-bit map ID")
            atlas.extend(payload)
            ids.append(tile_id)
            payloads.append(payload)
    return ids, payloads


def build_map_chunk(original: dict, tile_ids: list[int]) -> bytes:
    gate((original["width"], original["height"]) == (4, 2), "action resource is not 4x2")
    gate(len(tile_ids) == 8, "private tile count drift")
    cells: list[int] = []
    for original_cell, tile_id in zip(original["cells"], tile_ids):
        # Keep only the palette-bank nibble.  Private tiles are already written
        # in display orientation, so stale H/V flip flags must not be retained.
        cells.append((int(original_cell) & 0xF000) | tile_id)
    return bytes([4, 2]) + struct.pack("<H", int(original["reserved"])) + struct.pack("<8H", *cells)


def literal_only_lzss_body(decoded: bytes) -> bytes:
    body = bytearray()
    for start in range(0, len(decoded), 8):
        chunk = decoded[start : start + 8]
        body.append((1 << len(chunk)) - 1)
        body.extend(chunk)
    gate(len(body) <= 0xFFFF, "action atlas clone exceeds 16-bit compressed length")
    return bytes(body)


def save_preview(path: Path, labels: list[dict]) -> None:
    # Palette-independent diagnostic preview.  Normal/focus use distinct value
    # ramps only to make geometry visible; runtime color comes from native GBA
    # palette banks preserved in each map cell.
    scale = 3
    cell_w, cell_h = 32 * scale, 16 * scale
    canvas = Image.new("RGB", (cell_w * 2, cell_h * len(labels)), (24, 24, 24))
    normal_palette = {
        5: (255, 241, 130), 11: (105, 65, 15), 9: (239, 170, 45), 10: (202, 112, 28),
    }
    focus_palette = {
        4: (20, 55, 105), 12: (245, 250, 255), 8: (45, 115, 180), 9: (75, 145, 205), 10: (120, 185, 225), 11: (220, 235, 245),
    }
    for row_index, row in enumerate(labels):
        for col, key in enumerate(("normal_pixels", "focus_pixels")):
            pix = row[key]
            palette = normal_palette if col == 0 else focus_palette
            image = Image.new("RGB", (32, 16))
            for y in range(16):
                for x in range(32):
                    value = pix[y][x]
                    image.putpixel((x, y), palette.get(value, (40 + value * 10, 40 + value * 8, 40 + value * 6)))
            image = image.resize((cell_w, cell_h), Image.Resampling.NEAREST)
            canvas.paste(image, (col * cell_w, row_index * cell_h))
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", type=Path, default=MAIN_TIP_ROM)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--manifest", type=Path, default=MANIFEST)
    ap.add_argument("--preview", type=Path, default=PREVIEW)
    args = ap.parse_args()

    base = args.base.read_bytes()
    main_manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    base_sha = sha256(base)
    gate(base_sha == main_manifest["sha256"], f"base/main manifest hash mismatch: {base_sha}")
    gate(len(base) == int(main_manifest["size"]) == 32 * 1024 * 1024, "main TIP size drift")
    jp = JP_ROM.read_bytes()
    gate(sha256(jp) == scan.EXPECTED_SHA256, "Japanese source hash drift")

    # The action family must still be byte-identical between approved main and
    # clean JP before we base a private clone on it.
    for literal in TABLE_CONSUMER_LITERALS:
        gate(u32(base, literal) == ROM_BASE + RESOURCE_TABLE, f"action table literal drift at 0x{literal:08X}")
    gate(u32(base, RESOURCE_TABLE) == ROM_BASE + ATLAS_SOURCE, "action atlas pointer drift")

    source_header = u32(base, ATLAS_SOURCE)
    gate((source_header & 0xFFFF0000) == 0x80000000, "action atlas header drift")
    source_body_len = source_header & 0xFFFF
    source_atlas = scan.lzss_decompress(base[ATLAS_SOURCE + 4 : ATLAS_SOURCE + 4 + source_body_len])
    gate(len(source_atlas) == 239 * 32, f"unexpected action atlas decoded size: {len(source_atlas)}")
    atlas = bytearray(source_atlas)

    table_ptrs = [u32(base, RESOURCE_TABLE + i * 4) for i in range(RESOURCE_COUNT)]
    gate(table_ptrs[0] == ROM_BASE + ATLAS_SOURCE, "table[0] action atlas pointer drift")

    with ZipFile(FONT_ZIP) as archive:
        font = fontpair.load_bdf(archive, "Galmuri11.bdf")

    map_chunks: dict[int, bytes] = {}
    audit: list[dict] = []
    preview_rows: list[dict] = []
    for command_id, (jp_text, ko_text) in TRANSLATIONS.items():
        pair_row = {"command_id": command_id, "jp": jp_text, "ko": ko_text}
        previews: dict[str, list[list[int]]] = {}
        for state, resource_index, background, face in (
            ("normal", NORMAL_BASE + command_id, NORMAL_BG, NORMAL_FACE),
            ("focus", FOCUS_BASE + command_id, FOCUS_BG, FOCUS_FACE),
        ):
            map_obj = parse_map(base, table_ptrs[resource_index])
            gate((map_obj["width"], map_obj["height"]) == (4, 2), f"resource[{resource_index}] is not 4x2")
            source_pixels = stitch_map(source_atlas, map_obj)
            rendered = render_hangul(ko_text, font, face, background, source_pixels)
            private_ids, payloads = append_private_tiles(atlas, rendered)
            map_chunks[resource_index] = build_map_chunk(map_obj, private_ids)
            previews[state + "_pixels"] = rendered
            pair_row[state] = {
                "resource_index": resource_index,
                "source_pointer": f"0x{table_ptrs[resource_index]:08X}",
                "source_map_file_offset": f"0x{map_obj['offset']:08X}",
                "palette_banks": sorted({(int(cell) >> 12) & 0xF for cell in map_obj["cells"]}),
                "private_tile_ids": [f"0x{tile_id:03X}" for tile_id in private_ids],
                "private_tile_sha256": [sha256(payload) for payload in payloads],
                "background_index": background,
                "face_index": face,
            }
        preview_rows.append(previews)
        audit.append(pair_row)

    # Explicitly prove the Latin ID normal/focus resources are untouched.
    id_normal_ptr = table_ptrs[NORMAL_BASE + ID_COMMAND]
    id_focus_ptr = table_ptrs[FOCUS_BASE + ID_COMMAND]
    gate((NORMAL_BASE + ID_COMMAND) not in map_chunks and (FOCUS_BASE + ID_COMMAND) not in map_chunks, "ID resource unexpectedly targeted")

    compressed_body = literal_only_lzss_body(bytes(atlas))
    atlas_resource = p32(0x80000000 | len(compressed_body)) + compressed_body
    gate(ATLAS_CLONE + len(atlas_resource) <= TABLE_CLONE, "action atlas clone overlaps private table")

    candidate = bytearray(base)
    gate(set(candidate[ATLAS_CLONE:ALLOCATION_END]) <= {0}, "action expansion allocation is not zero-filled")
    candidate[ATLAS_CLONE : ATLAS_CLONE + len(atlas_resource)] = atlas_resource

    # Lay out private map chunks after the private 44-entry table.
    new_ptrs = table_ptrs[:]
    new_ptrs[0] = ROM_BASE + ATLAS_CLONE
    cursor = MAP_CLONE_START
    map_layout: dict[int, dict] = {}
    for resource_index in sorted(map_chunks):
        cursor = align4(cursor)
        chunk = map_chunks[resource_index]
        gate(cursor + len(chunk) <= ALLOCATION_END, "private action maps exceed allocation")
        candidate[cursor : cursor + len(chunk)] = chunk
        new_ptrs[resource_index] = ROM_BASE + cursor
        map_layout[resource_index] = {
            "clone_file_offset": f"0x{cursor:08X}",
            "clone_pointer": f"0x{ROM_BASE + cursor:08X}",
            "byte_length": len(chunk),
        }
        cursor += len(chunk)

    table_bytes = struct.pack(f"<{RESOURCE_COUNT}I", *new_ptrs)
    gate(TABLE_CLONE + len(table_bytes) <= MAP_CLONE_START, "private action table overlaps maps")
    candidate[TABLE_CLONE : TABLE_CLONE + len(table_bytes)] = table_bytes
    for literal in TABLE_CONSUMER_LITERALS:
        candidate[literal : literal + 4] = p32(ROM_BASE + TABLE_CLONE)

    # Verification gates.
    for index in range(RESOURCE_COUNT):
        actual = u32(candidate, TABLE_CLONE + index * 4)
        expected = new_ptrs[index]
        gate(actual == expected, f"private table[{index}] pointer mismatch")
        if index not in map_chunks and index != 0:
            gate(actual == table_ptrs[index], f"non-target table[{index}] changed")
    gate(new_ptrs[NORMAL_BASE + ID_COMMAND] == id_normal_ptr, "normal ID pointer changed")
    gate(new_ptrs[FOCUS_BASE + ID_COMMAND] == id_focus_ptr, "focus ID pointer changed")
    gate(candidate[ATLAS_SOURCE : ATLAS_SOURCE + 4 + source_body_len] == base[ATLAS_SOURCE : ATLAS_SOURCE + 4 + source_body_len], "original action atlas changed")
    for literal in TABLE_CONSUMER_LITERALS:
        gate(u32(candidate, literal) == ROM_BASE + TABLE_CLONE, f"action literal patch failed at 0x{literal:08X}")
    decoded_clone = scan.lzss_decompress(candidate[ATLAS_CLONE + 4 : ATLAS_CLONE + 4 + (u32(candidate, ATLAS_CLONE) & 0xFFFF)])
    gate(decoded_clone == bytes(atlas), "action atlas clone round-trip mismatch")
    gate(len(decoded_clone) // 32 == 239 + 8 * len(map_chunks), "private action tile count drift")

    changed = [i for i, (a, b) in enumerate(zip(base, candidate)) if a != b]
    allowed = set()
    allowed.update(range(ATLAS_CLONE, ATLAS_CLONE + len(atlas_resource)))
    allowed.update(range(TABLE_CLONE, TABLE_CLONE + len(table_bytes)))
    for info in map_layout.values():
        start = int(info["clone_file_offset"], 16)
        allowed.update(range(start, start + int(info["byte_length"])))
    for literal in TABLE_CONSUMER_LITERALS:
        allowed.update(range(literal, literal + 4))
    gate(all(off in allowed for off in changed), "candidate changed bytes outside action clone/literals")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(candidate)
    save_preview(args.preview, preview_rows)
    out_sha = sha256(candidate)
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_action_menu_ko_candidate_20260830",
        "result": "PASS",
        "source_main_tip": {"path": str(args.base.name), "sha256": base_sha, "size": len(base)},
        "candidate": {"path": str(args.out.relative_to(ADVANCE_ROOT)), "sha256": out_sha, "size": len(candidate)},
        "family": {
            "resource_table_source": f"0x{ROM_BASE + RESOURCE_TABLE:08X}",
            "atlas_source": f"0x{ROM_BASE + ATLAS_SOURCE:08X}",
            "atlas_clone": f"0x{ROM_BASE + ATLAS_CLONE:08X}",
            "table_clone": f"0x{ROM_BASE + TABLE_CLONE:08X}",
            "consumer_literals": [f"0x{ROM_BASE + off:08X}" for off in TABLE_CONSUMER_LITERALS],
            "source_decoded_tiles": 239,
            "clone_decoded_tiles": len(decoded_clone) // 32,
            "private_target_map_count": len(map_chunks),
            "latin_ID_resources_preserved": [NORMAL_BASE + ID_COMMAND, FOCUS_BASE + ID_COMMAND],
        },
        "labels": audit,
        "private_map_layout": {str(k): v for k, v in map_layout.items()},
        "verification": {
            "current_main_tip_manifest_hash_verified": True,
            "normal_focus_pair_contract_verified": True,
            "translated_command_count": len(TRANSLATIONS),
            "translated_state_resource_count": len(map_chunks),
            "ID_normal_focus_untouched": True,
            "non_target_table_entries_unchanged": True,
            "original_atlas_unchanged": True,
            "clone_round_trip_verified": True,
            "changes_confined_to_private_clone_and_three_literals": True,
            "changed_byte_count": len(changed),
        },
        "preview": str(args.preview.relative_to(ADVANCE_ROOT)),
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "out": str(args.out), "sha256": out_sha, "changed_bytes": len(changed), "translated_commands": len(TRANSLATIONS), "state_resources": len(map_chunks)}, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
