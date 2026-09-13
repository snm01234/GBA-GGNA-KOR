#!/usr/bin/env python3
"""Bind the current main-TIP ss1/ss2 Japanese graphics to ROM owners.

This pass intentionally excludes ss3..ss6.  ss1 is an OBJ button package;
ss2 is a BG tilemap consumer of the already-relocated E0518 status atlas.
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
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_develop_menu_buttons_state_20260901 as spriteutil
import analyze_ggen_advance_settings_suspend_ui as spritefmt
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
from ggen_advance_text_codec import (
    DICT_12X12_BASE,
    DICT_12X12_END,
    encode_tokens,
    expand_to_slots,
    load_dictionary,
)
from ggen_advance_project_paths import (
    ADVANCE_ROOT,
    MAIN_TIP_MANIFEST,
    MAIN_TIP_ROM,
    ORIGINAL_ROM,
    advance_relative,
)

OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_ss1_ss2_graphics_20260902.json"
STATE1 = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).ss1"
STATE2 = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).ss2"
ROM_BASE = 0x08000000
OBJ_RESOURCE = 0x08C3F130
SS2_RESOURCE = 0x092D8000
SPRITE_OBJECT_TABLE = 0x03001F98
SPRITE_OBJECT_SIZE = 40

SS1_LABELS = {
    0: {"jp": "搭載", "ko": "탑재", "style": "normal"},
    1: {"jp": "降ろす", "ko": "내리기", "style": "normal"},
    2: {"jp": "移動", "ko": "이동", "style": "normal"},
    3: {"jp": "変形", "ko": "변형", "style": "normal"},
    4: {"jp": "搭載", "ko": "탑재", "style": "focus"},
    5: {"jp": "降ろす", "ko": "내리기", "style": "focus"},
    6: {"jp": "移動", "ko": "이동", "style": "focus"},
    7: {"jp": "変形", "ko": "변형", "style": "focus"},
    8: {"jp": "搭載", "ko": "탑재", "style": "disabled_palette_on_normal_graphics"},
    9: {"jp": "降ろす", "ko": "내리기", "style": "disabled_palette_on_normal_graphics"},
    10: {"jp": "移動", "ko": "이동", "style": "disabled_palette_on_normal_graphics"},
    11: {"jp": "変形", "ko": "변형", "style": "disabled_palette_on_normal_graphics"},
}

SS2_RECTS = {
    "移動": {"ko": "이동", "canvas_rect": [128, 24, 160, 40], "screen_rect": [128, 96, 160, 112]},
    "限界": {"ko": "한계", "canvas_rect": [176, 24, 208, 40], "screen_rect": [176, 96, 208, 112]},
    "汎用": {"ko": "범용", "canvas_rect": [112, 40, 144, 56], "screen_rect": [112, 112, 144, 128]},
    "装甲": {"ko": "장갑", "canvas_rect": [156, 40, 188, 56], "screen_rect": [156, 112, 188, 128]},
}


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def u16(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def parse_animation_cross(rom: bytes, resource: int, index: int) -> dict[str, Any]:
    """Parse animation OAM and the source lookup even when both cross records."""
    graphics_rel, records = spritefmt.animation_records(rom, resource)
    record_off, record = records[index]
    marker = record.find(b"\x40\x00\x40\x00")
    gate(marker >= 0, f"animation {index} marker missing")
    blob = b"".join(part for _off, part in records[index:])[marker:]
    parsed = spritefmt.parse_animation_oam(blob)
    total = sum(int(obj["tile_count"]) for obj in parsed["objects"])
    source_start = parsed["entries_end"]
    gate(source_start + total * 2 <= len(blob), f"animation {index} source lookup truncated")
    source_ids = list(struct.unpack_from(f"<{total}H", blob, source_start))
    source_tiles = spriteutil.parse_resource_header(rom, resource)["source_tiles"]
    gate(all(tile < source_tiles for tile in source_ids), f"animation {index} source id outside atlas")
    lookup_file = record_off + marker + source_start
    return {
        "animation": index,
        "marker_file_offset": f"0x{record_off + marker:08X}",
        "lookup_file_offset": f"0x{lookup_file:08X}",
        "objects": parsed["objects"],
        "source_ids": source_ids,
        "graphics_relative_offset": f"0x{graphics_rel:04X}",
    }


def sprite_slots(state: bytes, pointer: int) -> list[dict[str, Any]]:
    iwram = state[statefmt.STATE_IWRAM : statefmt.STATE_IWRAM + statefmt.IWRAM_SIZE]
    base = SPRITE_OBJECT_TABLE - 0x03000000
    rows = []
    for index in range(80):
        off = base + index * SPRITE_OBJECT_SIZE
        if u32(iwram, off) != pointer:
            continue
        x, y = u16(iwram, off + 0x0A), u16(iwram, off + 0x0C)
        if x >= 0xFF00:
            x -= 0x10000
        if y >= 0xFF00:
            y -= 0x10000
        rows.append({"slot": index, "x": x, "y": y, "animation": iwram[off + 0x11]})
    return rows


def ss2_panel_report(main: bytes, state: bytes) -> dict[str, Any]:
    header = spriteutil.parse_resource_header(main, SS2_RESOURCE)
    animation = parse_animation_cross(main, SS2_RESOURCE, 3)
    canvas = spriteutil.stitch(header["graphics"], {"objects": animation["objects"]}, animation["source_ids"], list(range(len(animation["objects"]))))
    gate((len(canvas[0]), len(canvas)) == (240, 80), "ss2 animation-3 canvas drift")
    labels = {}
    for source, spec in SS2_RECTS.items():
        x0, y0, x1, y1 = spec["canvas_rect"]
        values = [canvas[y][x] for y in range(y0, y1) for x in range(x0, x1)]
        counts = {str(value): values.count(value) for value in sorted(set(values))}
        gate(counts.get("10", 0) > 0 and counts.get("5", 0) > 0, f"{source}: native ink/contour missing")
        labels[source] = {**spec, "palette_index_counts": counts, "source_pixels_sha256": sha256(bytes(values))}
    io = state[statefmt.STATE_IO : statefmt.STATE_PALETTE]
    bg3cnt = u16(io, 8 + 3 * 2)
    return {
        "resource": f"0x{SS2_RESOURCE:08X}",
        "resource_file_offset": f"0x{header['offset']:08X}",
        "source_resource": "0x08C64140 (approved develop-menu private clone provenance)",
        "pointer_hits": [f"0x{x:08X}" for x in spriteutil.pointer_hits(main[:0x01000000], SS2_RESOURCE)],
        "animation": animation,
        "canvas_size": [len(canvas[0]), len(canvas)],
        "screen_origin": [0, 72],
        "live_bg3": {"bgcnt": f"0x{bg3cnt:04X}", "charblock": (bg3cnt >> 2) & 3, "screenblock": (bg3cnt >> 8) & 31},
        "labels": labels,
        "ownership": "animation 3 supplies the 240x80 lower panel; four native 32x16 raster cells are composited into live BG3",
    }


def encoded_label_hits(jp: bytes, labels: list[str]) -> dict[str, Any]:
    cmap_payload = json.loads(
        (ADVANCE_ROOT / "analysis" / "ggen_advance_12x12_identified_charmap_20260828.json").read_text(encoding="utf-8")
    )["verified_charmap"]
    char_to_slot: dict[str, int] = {}
    for slot, char in cmap_payload.items():
        if isinstance(char, str) and char:
            char_to_slot.setdefault(char, int(str(slot), 16))
    dictionary = load_dictionary(jp, DICT_12X12_BASE, DICT_12X12_END)
    expanded = [expand_to_slots(tokens, dictionary) for tokens in dictionary]
    result = {}
    for label in labels:
        slots = [char_to_slot[char] for char in label]
        memo: dict[int, list[list[int]]] = {len(slots): [[]]}
        for pos in range(len(slots) - 1, -1, -1):
            rows: list[list[int]] = []
            literal = slots[pos] if slots[pos] <= 0xDF else (slots[pos] - 0x20E0) & 0xFFFF
            rows.extend([[literal] + tail for tail in memo.get(pos + 1, [])])
            for index, sequence in enumerate(expanded):
                if sequence and slots[pos : pos + len(sequence)] == sequence:
                    rows.extend([[0xF000 + index] + tail for tail in memo.get(pos + len(sequence), [])])
            memo[pos] = rows[:4096]
        encodings = []
        for tokens in memo.get(0, []):
            raw = encode_tokens(tokens)
            hits = []
            cursor = 0
            while True:
                cursor = jp.find(raw, cursor)
                if cursor < 0:
                    break
                hits.append(cursor)
                cursor += 1
            if hits:
                encodings.append({
                    "tokens": [f"0x{x:04X}" for x in tokens],
                    "raw_hex": raw.hex(" ").upper(),
                    "file_offsets": [f"0x{x:08X}" for x in hits],
                })
        result[label] = {"slots": [f"0x{x:04X}" for x in slots], "encodings_found": encodings}
    return result


def main() -> int:
    main = MAIN_TIP_ROM.read_bytes()
    jp = ORIGINAL_ROM.read_bytes()
    manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(main) == manifest["sha256"], "main TIP/manifest hash drift")
    state1, _ = statefmt.parse_png_state(STATE1)
    state2, _ = statefmt.parse_png_state(STATE2)
    main_crc = binascii.crc32(main) & 0xFFFFFFFF
    gate(u32(state1, 8) == main_crc and u32(state2, 8) == main_crc, "savestate CRC != current main TIP")

    header = spriteutil.parse_resource_header(jp, OBJ_RESOURCE)
    gate(header["animation_count"] == 13 and header["source_tiles"] == 80, "ss1 package layout drift")
    animations = [parse_animation_cross(jp, OBJ_RESOURCE, index) for index in range(12)]
    for index in range(8, 12):
        gate(
            sorted(animations[index]["source_ids"]) == sorted(animations[index - 8]["source_ids"]),
            f"disabled animation {index} does not reuse normal graphics",
        )
    state1_slots = sprite_slots(state1, OBJ_RESOURCE)
    gate({row["animation"] for row in state1_slots} >= {0, 1, 2, 3, 4, 11}, "ss1 resident animation set drift")

    ss2_panel = ss2_panel_report(main, state2)
    gate(ss2_panel["pointer_hits"] == ["0x00072484", "0x00072778", "0x00072998", "0x00072E08"], "ss2 consumer set drift")

    result: dict[str, Any] = {
        "schema_version": 1,
        "kind": "ggen_advance_ss1_ss2_graphics_20260902",
        "result": "PASS",
        "scope": {"included": ["ss1", "ss2", "same resource consumers"], "excluded": ["ss3", "ss4", "ss5", "ss6"]},
        "correction": "prior 20260902 remaining-UI analyzers mapped ss1/ss2 labels from ss4/ss5; this report uses current PNG previews and live VRAM",
        "main_tip": {"path": advance_relative(MAIN_TIP_ROM), "sha256": sha256(main), "crc32": f"0x{main_crc:08X}"},
        "ss1": {
            "state": {"path": advance_relative(STATE1), "sha256": sha256(STATE1.read_bytes())},
            "resource": f"0x{OBJ_RESOURCE:08X}",
            "resource_file_offset": f"0x{OBJ_RESOURCE - ROM_BASE:08X}",
            "pointer_hits": [f"0x{x:08X}" for x in spriteutil.pointer_hits(main[:0x01000000], OBJ_RESOURCE)],
            "source_tiles": header["source_tiles"],
            "animation_count": header["animation_count"],
            "resident_slots": state1_slots,
            "labels": SS1_LABELS,
            "animations": animations,
            "ownership": "animations 8..11 reuse animations 0..3 graphic lookups with a disabled palette; patching normal+focus graphics covers all states",
        },
        "ss2": {
            "state": {"path": advance_relative(STATE2), "sha256": sha256(STATE2.read_bytes())},
            **ss2_panel,
            "encoded_text_hits": encoded_label_hits(jp, list(SS2_RECTS)),
        },
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "out": advance_relative(OUT),
        "ss1_slots": state1_slots,
        "ss2_resource": ss2_panel["resource"],
        "ss2_consumers": ss2_panel["pointer_hits"],
    }, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
