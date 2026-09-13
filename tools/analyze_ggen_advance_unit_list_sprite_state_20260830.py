#!/usr/bin/env python3
"""Analyze the fresh mGBA unit-list state after the status-badge follow-up.

The supplied state was captured from
`ggen_advance_status_badges_hold_fixed_list_detail_followup_candidate_20260830.gba`.
This analyzer proves the runtime owner of the still-Japanese right-side unit
panel (運動/装甲/限界/移動 and the small 持 badge).

Key result: the visible right panel is an OBJ sprite canvas backed by the
C5A5DC sprite package, not the E0518 BG atlas and not the C491 look-alike pair.
Many live OBJ tiles are byte-exact copies of the original Japanese E0518 label
tiles and, independently, byte-exact raw tiles inside the C5A5DC package's
C5CBxx-C5CFxx graphic sheet.  The small 持 itself is at screen x=136,y=128
(top) / y=136 (bottom), OBJ tiles 0x186/0x18E, sourced byte-exact from ROM
0x00C5CEB0 / 0x00C5CF10.
"""
from __future__ import annotations

import argparse
import binascii
import hashlib
import json
import struct
import sys
import zlib
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import build_ggen_advance_status_ui_tile_overlay_poc as status  # noqa: E402

STATE_SIZE = 0x61000
STATE_IO = 0x00400
STATE_PALETTE = 0x00800
STATE_OAM = 0x00C00
STATE_VRAM = 0x01000
STATE_IWRAM = 0x19000
VRAM_SIZE = 0x18000
OBJ_VRAM = 0x10000
IWRAM_SIZE = 0x8000
ROM_BASE = 0x08000000

DEFAULT_STATE = ROOT / "outputs" / "20260830_ggen_advance_status_badges" / "ggen_advance_status_badges_hold_fixed_list_detail_followup_candidate_20260830.ss1"
MAIN_ROM = ROOT / "SD Gundam GGeneration Advance (Korean).gba"
JP_ROM = ROOT / "SD Gundam GGeneration Advance (Japan).gba"
DEFAULT_OUT = ROOT / "analysis" / "ggen_advance_unit_list_sprite_state_20260830.json"

EXPECTED_MAIN_SHA256 = "1a416cd86af1492f8b5a6a21f6536392bd156189c0a667c9933e619375db41a0"
EXPECTED_JP_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"

STATUS_TABLE = 0x000E0518
SPRITE_OBJECT_TABLE = 0x03001F98
SPRITE_OBJECT_SIZE = 40
ACTIVE_PACKAGE = 0x08C5A5DC
REJECTED_ALT_PACKAGE = 0x08C64140

# C491 translated private clones from the follow-up that did not affect the
# visible badge.  Their absence from live VRAM is an explicit negative proof.
C491_CLONES = (0x01280000, 0x01280040)

# OAM object 28 is the 64x64 right-panel canvas in this state.  With 1D OBJ
# mapping its 4bpp tile base is 0x155, so local (1,6)/(1,7) are 0x186/0x18E.
RIGHT_PANEL_OAM_INDEX = 28
RIGHT_PANEL_X = 128
RIGHT_PANEL_Y = 80
RIGHT_PANEL_TILE_BASE = 0x155
HOLD_OBJ_TILES = (0x186, 0x18E)
HOLD_SCREEN_POSITIONS = ((136, 128), (136, 136))
HOLD_ROM_SOURCES = (0x00C5CEB0, 0x00C5CF10)

# Runtime tile groups that connect the still-Japanese neighbors to the same
# C5A5DC package sheet.  These are useful anchors for the next patch.
RUNTIME_GROUPS = {
    "運動": {
        "obj_tiles": [0x156, 0x157, 0x158, 0x159, 0x15E, 0x15F, 0x160, 0x161],
        "rom_sources": [0x00C5CBB0, 0x00C5CBD0, 0x00C5CBF0, 0x00C5CC10,
                        0x00C5CC50, 0x00C5CC70, 0x00C5CC90, 0x00C5CCB0],
        "e0518_exact_anchors": {0x157: 0x147, 0x158: 0x148, 0x159: 0x149,
                                 0x15F: 0x14F, 0x160: 0x150, 0x161: 0x151},
    },
    "装甲": {
        "obj_tiles": [0x166, 0x167, 0x168, 0x169, 0x16E, 0x16F, 0x170, 0x171],
        "rom_sources": [0x00C5CCF0, 0x00C5CD10, 0x00C5CD30, 0x00C5CD50,
                        0x00C5CD70, 0x00C5CD90, 0x00C5CDB0, 0x00C5CDD0],
        "e0518_exact_anchors": {0x167: 0x14B, 0x168: 0x14C, 0x169: 0x14D,
                                 0x16F: 0x153, 0x170: 0x154, 0x171: 0x155},
    },
    "移動": {
        "obj_tiles": [0x176, 0x177, 0x178, 0x179, 0x17E, 0x17F, 0x180, 0x181],
        "rom_sources": [0x00C5CDF0, 0x00C5CE10, 0x00C5CE30, 0x00C5CC10,
                        0x00C5CE50, 0x00C5CE70, 0x00C5CC90, 0x00C5CCB0],
        "e0518_exact_anchors": {0x177: 0x15B, 0x178: 0x15C, 0x179: 0x149,
                                 0x17F: 0x162, 0x180: 0x150, 0x181: 0x151},
    },
    "限界": {
        # This label crosses the next sprite segment in the composed panel;
        # the exact anchors below are enough to prove the same source family.
        "obj_tiles": [0x195, 0x196, 0x197, 0x199, 0x19A, 0x19B],
        "rom_sources": [0x00C5CF50, 0x00C5CF70, 0x00C5CF90,
                        0x00C5CFB0, 0x00C5CFD0, 0x00C5CFF0],
        "e0518_exact_anchors": {0x196: 0x158, 0x197: 0x159,
                                 0x199: 0x15E, 0x19A: 0x15F, 0x19B: 0x160},
    },
}


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def u16(data: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def u32(data: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def parse_png_state(path: Path) -> tuple[bytes, list[dict[str, Any]]]:
    raw = path.read_bytes()
    gate(raw.startswith(b"\x89PNG\r\n\x1a\n"), "savestate is not mGBA PNG-container format")
    pos = 8
    state = None
    chunks: list[dict[str, Any]] = []
    while pos + 12 <= len(raw):
        length = struct.unpack_from(">I", raw, pos)[0]
        kind = raw[pos + 4:pos + 8]
        payload = raw[pos + 8:pos + 8 + length]
        chunks.append({"kind": kind.decode("latin1"), "file_offset": pos, "payload_length": length})
        if kind == b"gbAs":
            state = zlib.decompress(payload)
        pos += 12 + length
        if kind == b"IEND":
            break
    gate(state is not None, "mGBA gbAs chunk missing")
    gate(len(state) == STATE_SIZE, f"serialized state size drift: {len(state)}")
    return state, chunks


def oam_size(shape: int, size: int) -> tuple[int, int] | None:
    return {
        (0, 0): (8, 8), (0, 1): (16, 16), (0, 2): (32, 32), (0, 3): (64, 64),
        (1, 0): (16, 8), (1, 1): (32, 8), (1, 2): (32, 16), (1, 3): (64, 32),
        (2, 0): (8, 16), (2, 1): (8, 32), (2, 2): (16, 32), (2, 3): (32, 64),
    }.get((shape, size))


def parse_oam_entry(oam: bytes, index: int) -> dict[str, Any]:
    attr0, attr1, attr2, _ = struct.unpack_from("<HHHH", oam, index * 8)
    shape = (attr0 >> 14) & 3
    size = (attr1 >> 14) & 3
    dims = oam_size(shape, size)
    gate(dims is not None, f"invalid OAM shape/size at {index}")
    x = attr1 & 0x1FF
    y = attr0 & 0xFF
    if x >= 240:
        x -= 512
    if y >= 160:
        y -= 256
    return {
        "index": index,
        "x": x,
        "y": y,
        "width": dims[0],
        "height": dims[1],
        "tile": attr2 & 0x03FF,
        "priority": (attr2 >> 10) & 3,
        "palette_bank": (attr2 >> 12) & 0x0F,
        "attr0": f"0x{attr0:04X}",
        "attr1": f"0x{attr1:04X}",
        "attr2": f"0x{attr2:04X}",
    }


def decode_status_atlas(rom: bytes) -> tuple[int, bytes]:
    ptr = u32(rom, STATUS_TABLE)
    gate(ROM_BASE <= ptr < ROM_BASE + len(rom), f"invalid E0518 table[0] pointer: 0x{ptr:08X}")
    off = ptr - ROM_BASE
    header = u32(rom, off)
    gate(header & 0x80000000, "E0518 atlas is not custom-LZSS compressed")
    body_len = header & 0xFFFF
    decoded = status.lzss_decompress(rom[off + 4:off + 4 + body_len])
    gate(len(decoded) == status.ATLAS_EXPECTED_DECODED, f"E0518 decoded size drift: {len(decoded)}")
    return ptr, decoded


def obj_tile(obj: bytes, tile: int) -> bytes:
    start = tile * 32
    gate(start + 32 <= len(obj), f"OBJ tile 0x{tile:03X} outside OBJ VRAM")
    return bytes(obj[start:start + 32])


def atlas_tile(atlas: bytes, tile: int) -> bytes:
    start = tile * 32
    return atlas[start:start + 32]


def scan_iwram_resource_slots(iwram: bytes, pointer: int) -> list[dict[str, Any]]:
    rows = []
    base = SPRITE_OBJECT_TABLE - 0x03000000
    for index in range(100):
        off = base + index * SPRITE_OBJECT_SIZE
        if off + SPRITE_OBJECT_SIZE > len(iwram):
            break
        if u32(iwram, off) != pointer:
            continue
        rows.append({
            "object_slot": index,
            "iwram_address": f"0x{0x03000000 + off:08X}",
            "resource_pointer": f"0x{pointer:08X}",
            "field_06": f"0x{u16(iwram, off + 6):04X}",
            "field_08": f"0x{u16(iwram, off + 8):04X}",
            "field_0A": f"0x{u16(iwram, off + 0x0A):04X}",
            "field_0C": f"0x{u16(iwram, off + 0x0C):04X}",
            "field_0E": f"0x{u16(iwram, off + 0x0E):04X}",
        })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--state", type=Path, default=DEFAULT_STATE)
    ap.add_argument("--main", type=Path, default=MAIN_ROM)
    ap.add_argument("--jp", type=Path, default=JP_ROM)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    state, chunks = parse_png_state(args.state)
    main = args.main.read_bytes()
    jp = args.jp.read_bytes()
    gate(sha256(main) == EXPECTED_MAIN_SHA256, f"main TIP hash drift: {sha256(main)}")
    gate(sha256(jp) == EXPECTED_JP_SHA256, f"Japanese ROM hash drift: {sha256(jp)}")

    state_crc = u32(state, 0x08)
    main_crc = binascii.crc32(main) & 0xFFFFFFFF
    gate(state_crc == main_crc, f"state ROM CRC 0x{state_crc:08X} != main 0x{main_crc:08X}")

    io = state[STATE_IO:STATE_PALETTE]
    oam = state[STATE_OAM:STATE_VRAM]
    vram = state[STATE_VRAM:STATE_IWRAM]
    iwram = state[STATE_IWRAM:STATE_IWRAM + IWRAM_SIZE]
    gate(len(vram) == VRAM_SIZE, "VRAM size mismatch")
    gate(len(iwram) == IWRAM_SIZE, "IWRAM size mismatch")
    obj = vram[OBJ_VRAM:]

    dispcnt = u16(io, 0)
    gate(bool(dispcnt & 0x1000), f"OBJ layer disabled: DISPCNT=0x{dispcnt:04X}")
    gate(bool(dispcnt & 0x0040), "state is not using 1D OBJ tile mapping")

    panel = parse_oam_entry(oam, RIGHT_PANEL_OAM_INDEX)
    gate((panel["x"], panel["y"], panel["width"], panel["height"], panel["tile"]) ==
         (RIGHT_PANEL_X, RIGHT_PANEL_Y, 64, 64, RIGHT_PANEL_TILE_BASE), f"right panel OAM drift: {panel}")

    jp_ptr, jp_atlas = decode_status_atlas(jp)
    main_ptr, main_atlas = decode_status_atlas(main)
    gate(main_ptr == 0x09240000, f"main active E0518 pointer drift: 0x{main_ptr:08X}")
    gate(jp_atlas != main_atlas, "main E0518 atlas unexpectedly equals Japanese atlas")

    package_slots = scan_iwram_resource_slots(iwram, ACTIVE_PACKAGE)
    alt_slots = scan_iwram_resource_slots(iwram, REJECTED_ALT_PACKAGE)
    gate(package_slots, "active C5A5DC sprite package not resident in object manager")
    gate(not alt_slots, "alternate C64140 package unexpectedly resident in this state")

    group_reports = {}
    for label, spec in RUNTIME_GROUPS.items():
        matches = []
        for obj_id, rom_off in zip(spec["obj_tiles"], spec["rom_sources"]):
            live = obj_tile(obj, obj_id)
            gate(live == main[rom_off:rom_off + 32], f"{label} OBJ 0x{obj_id:03X} != ROM 0x{rom_off:08X}")
            matches.append({
                "obj_tile": f"0x{obj_id:03X}",
                "full_vram_tile": f"0x{0x800 + obj_id:03X}",
                "rom_source_offset": f"0x{rom_off:08X}",
                "sha256": sha256(live),
            })
        anchors = []
        for obj_id, source_id in spec["e0518_exact_anchors"].items():
            live = obj_tile(obj, obj_id)
            gate(live == atlas_tile(jp_atlas, source_id), f"{label} JP E0518 anchor mismatch: OBJ 0x{obj_id:03X}")
            gate(live != atlas_tile(main_atlas, source_id), f"{label} live OBJ unexpectedly equals Korean E0518 tile 0x{source_id:03X}")
            anchors.append({
                "obj_tile": f"0x{obj_id:03X}",
                "jp_e0518_tile": f"0x{source_id:03X}",
                "main_e0518_same": False,
            })
        group_reports[label] = {"raw_rom_matches": matches, "jp_e0518_exact_anchors": anchors}

    # Exact remaining 持 source: object 28, local column 1 rows 6/7.
    hold_rows = []
    for obj_id, pos, rom_off in zip(HOLD_OBJ_TILES, HOLD_SCREEN_POSITIONS, HOLD_ROM_SOURCES):
        live = obj_tile(obj, obj_id)
        gate(live == main[rom_off:rom_off + 32], f"right 持 tile 0x{obj_id:03X} source mismatch")
        hold_rows.append({
            "obj_tile": f"0x{obj_id:03X}",
            "full_vram_tile": f"0x{0x800 + obj_id:03X}",
            "screen_xy": list(pos),
            "rom_source_offset": f"0x{rom_off:08X}",
            "resource_relative_offset": f"0x{rom_off - (ACTIVE_PACKAGE - ROM_BASE):04X}",
            "sha256": sha256(live),
        })

    # The translated C491 look-alike clones are absent from live VRAM.
    c491_live_hits = []
    for clone_off in C491_CLONES:
        # Descriptor flags=0x1A; graphics at +0x14, compressed body length at +0x0A.
        graphic_len = u16(main, clone_off + 0x0A)
        decoded = status.lzss_decompress(main[clone_off + 0x14:clone_off + 0x14 + graphic_len])
        gate(len(decoded) == 32, f"C491 clone decode drift at 0x{clone_off:08X}")
        hits = [tile for tile in range(len(obj) // 32) if obj_tile(obj, tile) == decoded]
        c491_live_hits.append({"clone_offset": f"0x{clone_off:08X}", "obj_hits": [f"0x{x:03X}" for x in hits]})
        gate(not hits, f"C491 clone unexpectedly appears in live OBJ VRAM: 0x{clone_off:08X}")

    # Conversely, the already-successful C439 left-list translated tiles are
    # present in BG VRAM, explaining why that copy changed independently.
    left_list_tiles = []
    for graphic_off in (0x00C43968, 0x00C439BC):
        for half in range(2):
            raw = main[graphic_off + half * 32:graphic_off + (half + 1) * 32]
            hits = [tile for tile in range(OBJ_VRAM // 32) if vram[tile * 32:(tile + 1) * 32] == raw]
            left_list_tiles.append({
                "rom_offset": f"0x{graphic_off + half * 32:08X}",
                "bg_vram_tiles": [f"0x{x:03X}" for x in hits],
            })
    gate(any(row["bg_vram_tiles"] for row in left_list_tiles), "translated C439 left-list graphics absent from BG VRAM")

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_unit_list_sprite_state_20260830",
        "result": "PASS",
        "savestate": {
            "path": str(args.state.relative_to(ROOT)),
            "size": args.state.stat().st_size,
            "serialized_size": len(state),
            "chunks": chunks,
            "rom_crc32": f"0x{state_crc:08X}",
        },
        "main_tip": {
            "path": str(args.main.relative_to(ROOT)),
            "sha256": sha256(main),
            "crc32": f"0x{main_crc:08X}",
            "state_crc_matches": True,
        },
        "runtime": {
            "dispcnt": f"0x{dispcnt:04X}",
            "obj_enabled": True,
            "obj_mapping": "1D",
            "right_panel_oam": panel,
            "right_panel_interpretation": "the visible right-side unit information area is composed into OBJ VRAM sprites; it is not the E0518 BG tilemap seen directly",
        },
        "active_sprite_package": {
            "resource_pointer": f"0x{ACTIVE_PACKAGE:08X}",
            "file_offset": f"0x{ACTIVE_PACKAGE - ROM_BASE:08X}",
            "object_manager_slots": package_slots,
            "alternate_C64140_slots": alt_slots,
            "sheet_region_proven_by_live_raw_matches": "0x00C5CBB0..0x00C5CFF0 (target subset; package continues beyond this region)",
        },
        "e0518_control": {
            "jp_pointer": f"0x{jp_ptr:08X}",
            "main_pointer": f"0x{main_ptr:08X}",
            "main_decoded_sha256": sha256(main_atlas),
            "jp_decoded_sha256": sha256(jp_atlas),
            "interpretation": "main E0518 already contains the Korean status labels, but the live OBJ panel contains original-Japanese tile pixels copied from the separate C5A5DC sprite package",
        },
        "neighbor_label_proof": group_reports,
        "remaining_hold_badge": {
            "source": "C5A5DC sprite package sheet",
            "screen_badge_top_left": [136, 128],
            "tiles": hold_rows,
            "conclusion": "patching E0518 resource[12], D54, or C491 cannot change this visible copy; the live 持 is sourced from C5CEB0/C5CF10 before being placed in the OBJ panel",
        },
        "negative_proof": {
            "c491_translated_clones_live_obj_hits": c491_live_hits,
            "c491_conclusion": "no translated C491 clone tile is present in live OBJ VRAM, confirming the C491 visual match was not the final consumer",
        },
        "left_list_control": {
            "c439_translated_tiles": left_list_tiles,
            "interpretation": "the separately fixed left-list C439 graphic is resident in BG VRAM, consistent with the user's earlier observation that the left list changed while the right panel did not",
        },
        "conclusion": {
            "stale_savestate_hypothesis": "rejected for this fresh state: CRC matches the tested/promoted ROM and the right panel is a separately sourced OBJ composition",
            "actual_owner": "C5A5DC sprite package / C5CBxx-C5CFxx source sheet",
            "next_patch_target": "translate the C5A5DC package sheet for 運動/装甲/限界/移動 and the exact 持 pair 0x00C5CEB0/0x00C5CF10; audit any package-shared/alternate-state copies before writing",
            "do_not_patch_again": ["E0518 resource[12] for this copy", "D54 clone", "C491 look-alike pair"],
        },
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "out": str(args.out),
        "state_crc": f"0x{state_crc:08X}",
        "main_crc": f"0x{main_crc:08X}",
        "right_panel": panel,
        "active_package": f"0x{ACTIVE_PACKAGE:08X}",
        "hold_sources": [f"0x{x:08X}" for x in HOLD_ROM_SOURCES],
        "c491_live": False,
        "next_patch": "C5A5DC sprite package sheet",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
