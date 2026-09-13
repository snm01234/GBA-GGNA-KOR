#!/usr/bin/env python3
"""Bind remaining screenshot labels to live 12x12 BG pixels and draw callsites.

For ss1..ss5, reconstruct the requested BG layer as palette-index pixels, find
where the exact Japanese native 12x12 glyph mask is visible, and then scan Thumb
BL calls to the game's 12x12 text renderers for matching x/y immediates.  This
turns screenshot coordinates into concrete code/literal provenance suitable for
a minimal pointer redirect patch.
"""
from __future__ import annotations

import hashlib
import json
import struct
import sys
from pathlib import Path
from typing import Any

try:
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
except ModuleNotFoundError:  # The bundled runtime can run the structural scan without disassembly text.
    Cs = None  # type: ignore[assignment]
    CS_ARCH_ARM = CS_MODE_THUMB = 0

try:
    from analyze_direct_pc_literal import thumb_bl_target
except ModuleNotFoundError:
    def thumb_bl_target(data: bytes, file_offset: int) -> int | None:
        if file_offset + 4 > len(data):
            return None
        high, low = struct.unpack_from("<HH", data, file_offset)
        if high & 0xF800 != 0xF000 or low & 0xF800 != 0xF800:
            return None
        displacement = ((high & 0x07FF) << 12) | ((low & 0x07FF) << 1)
        if displacement & 0x00400000:
            displacement -= 0x00800000
        return (ROM_BASE + file_offset + 4 + displacement) & 0xFFFFFFFF

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
from ggen_advance_project_paths import ADVANCE_ROOT, ORIGINAL_ROM, advance_relative

OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_remaining_ui_draw_calls_20260902.json"
CHARMAP12 = ADVANCE_ROOT / "analysis" / "ggen_advance_12x12_identified_charmap_20260828.json"
FONT12_BASE = 0x0008AC40
FONT12_STRIDE = 18
EXPECTED_JP_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"
ROM_BASE = 0x08000000
RENDERERS = {0x08000CA0: "text12_CA0", 0x08000D10: "text12_D10"}

TARGETS: dict[int, list[dict[str, Any]]] = {
    1: [
        {"name": "運動", "layer": 3, "hint": [120, 96]},
        {"name": "限界", "layer": 3, "hint": [184, 96]},
        {"name": "移動", "layer": 3, "hint": [48, 112]},
        {"name": "装甲", "layer": 3, "hint": [112, 112]},
        {"name": "残り回数", "layer": 3, "hint": [152, 128]},
    ],
    2: [
        {"name": "強化費用", "layer": 2, "hint": [136, 72]},
        {"name": "補給P", "layer": 2, "hint": [136, 88]},
    ],
    3: [
        {"name": "変形", "layer": 3, "hint": [192, 136]},
    ],
    4: [
        {"name": "移動タイプ", "layer": 3, "hint": [128, 96]},
        {"name": "現在の所属", "layer": 3, "hint": [128, 112]},
    ],
    5: [
        {"name": "パイロット", "layer": 3, "hint": [152, 88]},
        {"name": "ユニット", "layer": 3, "hint": [152, 104]},
        {"name": "パーツ", "layer": 3, "hint": [152, 120]},
    ],
    6: [
        {"name": "ソート順の変更", "layer": 2, "hint": [75, 47]},
        {"name": "昇順", "layer": 2, "hint": [136, 66]},
        {"name": "名前", "layer": 2, "hint": [86, 82]},
        {"name": "降順", "layer": 2, "hint": [136, 82]},
        {"name": "配備中", "layer": 2, "hint": [83, 98]},
    ],
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


def decode_tile(vram: bytes, charblock: int, cell: int) -> list[list[int]]:
    tile_id = cell & 0x03FF
    off = charblock * 0x4000 + tile_id * 32
    raw = vram[off : off + 32]
    gate(len(raw) == 32, "VRAM tile overrun")
    tile = [[(raw[y * 4 + x // 2] >> (4 * (x & 1))) & 0x0F for x in range(8)] for y in range(8)]
    if cell & 0x0400:
        tile = [list(reversed(row)) for row in tile]
    if cell & 0x0800:
        tile = list(reversed(tile))
    return tile


def layer_pixels(state: bytes, layer: int) -> tuple[list[list[int]], dict[str, int]]:
    io = state[statefmt.STATE_IO : statefmt.STATE_PALETTE]
    vram = state[statefmt.STATE_VRAM : statefmt.STATE_IWRAM]
    cnt = u16(io, 8 + layer * 2)
    charblock = (cnt >> 2) & 3
    screenblock = (cnt >> 8) & 31
    screen = [[0] * 240 for _ in range(160)]
    for ty in range(20):
        for tx in range(30):
            cell = u16(vram, screenblock * 0x800 + (ty * 32 + tx) * 2)
            tile = decode_tile(vram, charblock, cell)
            for yy in range(8):
                for xx in range(8):
                    screen[ty * 8 + yy][tx * 8 + xx] = tile[yy][xx]
    return screen, {"bgcnt": cnt, "charblock": charblock, "screenblock": screenblock}


def glyph_points(data: bytes, slot: int) -> set[tuple[int, int]]:
    raw = data[FONT12_BASE + slot * FONT12_STRIDE : FONT12_BASE + (slot + 1) * FONT12_STRIDE]
    gate(len(raw) == FONT12_STRIDE, f"12x12 glyph overrun 0x{slot:04X}")
    return {
        (x, y)
        for y in range(12)
        for x in range(12)
        if raw[(y * 12 + x) // 8] & (1 << ((y * 12 + x) & 7))
    }


def phrase_mask(data: bytes, text: str, char_to_slot: dict[str, int]) -> tuple[set[tuple[int, int]], list[int]]:
    slots = []
    mask: set[tuple[int, int]] = set()
    for index, char in enumerate(text):
        gate(char in char_to_slot, f"12x12 charmap missing {char!r} for {text}")
        slot = char_to_slot[char]
        slots.append(slot)
        for x, y in glyph_points(data, slot):
            mask.add((index * 12 + x, y))
    return mask, slots


def dice(a: set[tuple[int, int]], b: set[tuple[int, int]]) -> float:
    if not a or not b:
        return 0.0
    return 2.0 * len(a & b) / (len(a) + len(b))


def locate_phrase(screen: list[list[int]], mask: set[tuple[int, int]], width: int, hint: list[int]) -> list[dict[str, Any]]:
    hx, hy = hint
    x_lo, x_hi = max(0, hx - 24), min(240 - width, hx + 24)
    y_lo, y_hi = max(0, hy - 20), min(160 - 12, hy + 20)
    best: list[tuple[float, int, int, int, int, int]] = []
    for y0 in range(y_lo, y_hi + 1):
        for x0 in range(x_lo, x_hi + 1):
            counts = [0] * 16
            for yy in range(12):
                row = screen[y0 + yy]
                for xx in range(width):
                    counts[row[x0 + xx]] += 1
            for value in range(16):
                if counts[value] == 0:
                    continue
                observed = {
                    (xx, yy)
                    for yy in range(12)
                    for xx in range(width)
                    if screen[y0 + yy][x0 + xx] == value
                }
                score = dice(observed, mask)
                if score >= 0.45:
                    best.append((score, x0, y0, value, len(observed), len(mask)))
    best.sort(reverse=True)
    out = []
    seen: set[tuple[int, int, int]] = set()
    for score, x, y, value, observed, expected in best:
        key = (x, y, value)
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "score": round(score, 6),
            "x": x,
            "y": y,
            "palette_index": value,
            "observed_pixels": observed,
            "expected_pixels": expected,
        })
        if len(out) >= 16:
            break
    return out


def literal_from_ldr_halfword(rom: bytes, file_off: int) -> tuple[int, int, int] | None:
    """Decode Thumb-1 LDR Rd,[pc,#imm8*4] at a known halfword boundary."""
    if not (0 <= file_off <= len(rom) - 2):
        return None
    half = u16(rom, file_off)
    if half & 0xF800 != 0x4800:
        return None
    reg = (half >> 8) & 7
    literal_off = ((file_off + 4) & ~3) + ((half & 0xFF) << 2)
    if literal_off + 4 > len(rom):
        return None
    return reg, literal_off, u32(rom, literal_off)


def draw_calls(rom: bytes) -> list[dict[str, Any]]:
    # Scan BL encodings directly instead of linearly disassembling from the ROM
    # header; Capstone correctly stops at the first non-code area otherwise.
    calls = [
        off
        for off in range(0, min(len(rom), 0x00800000) - 3, 2)
        if thumb_bl_target(rom, off) in RENDERERS
    ]
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB) if Cs is not None else None
    rows = []
    for call_off in calls:
        target = thumb_bl_target(rom, call_off)
        r_immediate: dict[int, int] = {}
        r_literal: dict[int, dict[str, int]] = {}
        # A 32-byte local window covers the ordinary `ldr r3; str; add; movs
        # r1; movs r2; bl` call pattern while keeping accidental stale register
        # assignments out of the provenance record.
        start = max(0, call_off - 32)
        for off in range(start, call_off, 2):
            half = u16(rom, off)
            if half & 0xF800 == 0x2000:  # MOVS Rd,#imm8
                reg = (half >> 8) & 7
                if reg in (1, 2, 3):
                    r_immediate[reg] = half & 0xFF
            literal = literal_from_ldr_halfword(rom, off)
            if literal is not None:
                reg, literal_off, value = literal
                if reg in (1, 2, 3):
                    r_literal[reg] = {"value": value, "insn": ROM_BASE + off, "literal_off": literal_off}
        trail = [] if md is None else [
            f"{insn.address:08X}: {insn.mnemonic} {insn.op_str}"
            for insn in md.disasm(rom[start : call_off + 4], ROM_BASE + start)
        ]
        rows.append({
            "call": ROM_BASE + call_off,
            "call_file_offset": call_off,
            "renderer": RENDERERS[int(target)],
            "x_r1": r_immediate.get(1),
            "y_r2": r_immediate.get(2),
            "r3_literal_value": r_literal.get(3, {}).get("value"),
            "r3_literal_load": r_literal.get(3, {}).get("insn"),
            "r3_literal_file_offset": r_literal.get(3, {}).get("literal_off"),
            "trail": trail,
        })
    return rows


def candidate_calls(calls: list[dict[str, Any]], locations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not locations:
        return []
    best = locations[0]
    x, y = int(best["x"]), int(best["y"])
    rows = []
    for call in calls:
        cx, cy = call.get("x_r1"), call.get("y_r2")
        if cx is None or cy is None:
            continue
        distance = abs(int(cx) - x) + abs(int(cy) - y)
        if distance <= 16:
            rows.append({**call, "xy_distance": distance})
    rows.sort(key=lambda row: (row["xy_distance"], row["call"]))
    return rows[:40]


def main() -> int:
    jp = ORIGINAL_ROM.read_bytes()
    gate(sha256(jp) == EXPECTED_JP_SHA256, f"Japanese ROM hash drift {sha256(jp)}")
    cmap = json.loads(CHARMAP12.read_text(encoding="utf-8"))["verified_charmap"]
    char_to_slot: dict[str, int] = {}
    for slot_text, char in cmap.items():
        if isinstance(char, str) and char:
            char_to_slot.setdefault(char, int(str(slot_text), 16))
    calls = draw_calls(jp)
    result: dict[str, Any] = {
        "schema_version": 1,
        "kind": "ggen_advance_remaining_ui_draw_calls_20260902",
        "result": "PASS",
        "source": {"rom": advance_relative(ORIGINAL_ROM), "sha256": sha256(jp)},
        "draw_calls_scanned": len(calls),
        "states": {},
    }
    compact = {}
    for state_no, targets in TARGETS.items():
        path = ADVANCE_ROOT / f"SD Gundam GGeneration Advance (Korean).ss{state_no}"
        state, _chunks = statefmt.parse_png_state(path)
        layer_cache: dict[int, tuple[list[list[int]], dict[str, int]]] = {}
        rows = []
        for spec in targets:
            layer = int(spec["layer"])
            if layer not in layer_cache:
                layer_cache[layer] = layer_pixels(state, layer)
            screen, binding = layer_cache[layer]
            mask, slots = phrase_mask(jp, str(spec["name"]), char_to_slot)
            locations = locate_phrase(screen, mask, len(str(spec["name"])) * 12, list(spec["hint"]))
            call_rows = candidate_calls(calls, locations)
            rows.append({
                **spec,
                "binding": {k: f"0x{v:04X}" if k == "bgcnt" else v for k, v in binding.items()},
                "slots_12x12": [f"0x{slot:04X}" for slot in slots],
                "locations": locations,
                "candidate_draw_calls": call_rows,
            })
            compact[f"ss{state_no}:{spec['name']}"] = {
                "location": locations[0] if locations else None,
                "calls": [
                    [f"0x{r['call']:08X}", r["renderer"], r["x_r1"], r["y_r2"], f"0x{r['r3_literal_value']:08X}" if r.get("r3_literal_value") is not None else None]
                    for r in call_rows[:8]
                ],
            }
        result["states"][str(state_no)] = {"path": advance_relative(path), "targets": rows}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "out": advance_relative(OUT), "draw_calls": len(calls), "targets": compact}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
