#!/usr/bin/env python3
"""Recover Hangul tokens from the glyphs actually painted in a promoted ROM.

The dated apply-charmap is not authoritative after later allocator or analysis
changes.  Encoding 8x16 UI against metadata slots while the relocated font still
holds a shifted Hangul raster is what turns 으 into 짊.  Future 8x16 writers
must recover slots from the active font, paint any missing glyph onto a free
slot, and refuse to emit a token whose painted cell is not the intended character.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from zipfile import ZipFile

import build_ggen_advance_ko_poc as fontops
import build_ggen_advance_unified_rom_poc as unified
import test_ggen_advance_font_pair as fontpair
from ggen_advance_project_paths import ADVANCE_ROOT, FONT_ZIP, ORIGINAL_ROM


FONT8_RELOCATED = 0x01008C20
FONT12_RELOCATED = 0x01000000
PLAN_PATH = ADVANCE_ROOT / "font_tables" / "ggen_advance_korean_charmap_plan_20260825.json"


def gate(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"gate failed: {message}")


def token_from_slot(slot: int) -> int:
    return slot if slot <= 0xDF else 0xDF20 + slot


def slot_raw(data: bytes | bytearray, base: int, slot: int, stride: int) -> bytes:
    start = base + slot * stride
    return bytes(data[start : start + stride])


def load_galmuri8() -> fontpair.BdfFont:
    with ZipFile(FONT_ZIP) as archive:
        return fontpair.load_bdf(archive, "Galmuri11-Condensed.bdf")


def load_galmuri12() -> fontpair.BdfFont:
    with ZipFile(FONT_ZIP) as archive:
        return fontpair.load_bdf(archive, "Galmuri11.bdf")


def packed_8x16(char: str, font: fontpair.BdfFont) -> bytes:
    return fontops.pack_8x16(fontpair.render_condensed_8x16_basic(char, font))


def packed_12x12(char: str, font: fontpair.BdfFont) -> bytes:
    return fontops.pack_12x12(fontpair.render_12x12_basic(char, font))


def recover_unique_slots(
    rom: bytes | bytearray,
    font: fontpair.BdfFont,
    chars: set[str],
    *,
    base: int,
    stride: int,
    count: int,
    packer,
    label: str,
) -> dict[str, int]:
    by_glyph: dict[bytes, list[int]] = {}
    for slot in range(count):
        by_glyph.setdefault(slot_raw(rom, base, slot, stride), []).append(slot)
    recovered: dict[str, int] = {}
    for char in sorted(chars):
        if char == " ":
            continue
        hits = by_glyph.get(packer(char, font), [])
        gate(len(hits) != 0, f"{label} glyph is not painted for {char!r}")
        gate(len(hits) == 1, f"{label} glyph is not unique for {char!r}: {[hex(slot) for slot in hits]}")
        recovered[char] = hits[0]
    return recovered


def recover_unique_8x16_slots(
    rom: bytes | bytearray,
    font: fontpair.BdfFont,
    chars: set[str],
) -> dict[str, int]:
    return recover_unique_slots(
        rom,
        font,
        chars,
        base=FONT8_RELOCATED,
        stride=fontops.FONT_8X16_STRIDE,
        count=fontops.FONT_8X16_COUNT,
        packer=packed_8x16,
        label="8x16",
    )


def recover_unique_12x12_slots(
    rom: bytes | bytearray,
    font: fontpair.BdfFont,
    chars: set[str],
) -> dict[str, int]:
    return recover_unique_slots(
        rom,
        font,
        chars,
        base=FONT12_RELOCATED,
        stride=fontops.FONT_12X12_STRIDE,
        count=fontops.FONT_12X12_COUNT,
        packer=packed_12x12,
        label="12x12",
    )


def painted_8x16_char_at(rom: bytes | bytearray, slot: int, expected: dict[bytes, str]) -> str | None:
    return expected.get(slot_raw(rom, FONT8_RELOCATED, slot, fontops.FONT_8X16_STRIDE))


def audit_apply_charmap_8x16(
    rom: bytes,
    original: bytes,
    apply_map: dict[str, Any],
    font: fontpair.BdfFont,
) -> dict[str, Any]:
    expected_by_glyph = {
        packed_8x16(str(row["char"]), font): str(row["char"])
        for row in apply_map["assignments"]
        if str(row.get("paint") or "") in {"both", "8x16", "split"} and "가" <= str(row["char"]) <= "힣"
    }
    mismatches = []
    for row in apply_map["assignments"]:
        char = str(row["char"])
        paint = str(row.get("paint") or "")
        if paint not in {"both", "8x16", "split"} or not ("가" <= char <= "힣"):
            continue
        slot = int(str(row["slot"]), 16)
        actual = slot_raw(rom, FONT8_RELOCATED, slot, fontops.FONT_8X16_STRIDE)
        expected = packed_8x16(char, font)
        orig = slot_raw(original, fontops.FONT_8X16_BASE, slot, fontops.FONT_8X16_STRIDE)
        if actual == expected:
            continue
        mismatches.append(
            {
                "char": char,
                "metadata_slot": f"0x{slot:04X}",
                "painted_as": expected_by_glyph.get(actual),
                "still_japanese": actual == orig,
            }
        )
    return {"mismatch_count": len(mismatches), "mismatches": mismatches}


def painted_slots(rom: bytes, original: bytes) -> set[int]:
    painted: set[int] = set()
    for slot in range(fontops.FONT_8X16_COUNT):
        if slot_raw(rom, FONT8_RELOCATED, slot, fontops.FONT_8X16_STRIDE) != slot_raw(
            original, fontops.FONT_8X16_BASE, slot, fontops.FONT_8X16_STRIDE
        ):
            painted.add(slot)
    return painted


def choose_free_8x16_slot(
    rom: bytes,
    original: bytes,
    records: list[dict[str, Any]],
    *,
    preferred: int | None = None,
) -> int:
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    live8, _live12 = unified.collect_live_slots(original, records)
    compatibility_only = {int(slot, 16) for slot in plan["slot_domain"]["compatibility_only_slots"]}
    domain = (
        set(range(unified.SLOT_MIN, unified.SLOT_MAX + 1))
        - unified.RESERVED_GLYPH_SLOTS
        - compatibility_only
        - unified.SPECIAL_SLOTS
    )
    already = painted_slots(rom, original)
    safe = sorted(domain - live8 - already, reverse=True)
    jp_charmap = unified.load_identified_slot_to_char(unified.CHARMAP_8X16_PATH)
    ideograph_safe = [
        slot
        for slot in safe
        if len(jp_charmap.get(slot, "")) == 1 and 0x4E00 <= ord(jp_charmap[slot]) <= 0x9FFF
    ]
    if preferred is not None and preferred in ideograph_safe:
        return preferred
    gate(bool(ideograph_safe), "no audited-free 8x16 ideograph slot available")
    return ideograph_safe[0]


def paint_8x16(candidate: bytearray, slot: int, char: str, font: fontpair.BdfFont) -> int:
    packed = packed_8x16(char, font)
    start = FONT8_RELOCATED + slot * fontops.FONT_8X16_STRIDE
    candidate[start : start + fontops.FONT_8X16_STRIDE] = packed
    gate(
        bytes(candidate[start : start + fontops.FONT_8X16_STRIDE]) == packed,
        f"failed to paint 8x16 {char!r} at 0x{slot:04X}",
    )
    return start


def encode_literal(text: str, tokens: dict[str, int]) -> bytes:
    out = bytearray()
    for char in text:
        if char == " ":
            out.append(0x01)
            continue
        token = tokens.get(char)
        gate(token is not None, f"missing painted 8x16 token for {char!r}")
        if token <= 0xDF:
            out.append(token)
        else:
            gate(0xE000 <= token <= 0xEFFF, f"invalid literal token for {char!r}: 0x{token:04X}")
            out.extend((token >> 8, token & 0xFF))
    out.append(0)
    return bytes(out)


def verify_payload_painted(
    rom: bytes | bytearray,
    payload: bytes,
    text: str,
    font: fontpair.BdfFont,
    *,
    base: int = FONT8_RELOCATED,
    stride: int = fontops.FONT_8X16_STRIDE,
    packer=packed_8x16,
    label: str = "8x16",
) -> None:
    expected_chars = [char for char in text if char != " "]
    index = 0
    seen = 0
    while index < len(payload):
        value = payload[index]
        if value == 0:
            break
        if value == 1:
            index += 1
            continue
        if value >= 0xE0:
            token = (value << 8) | payload[index + 1]
            slot = (token + 0x20E0) & 0xFFFF
            index += 2
        else:
            slot = value
            index += 1
        gate(seen < len(expected_chars), f"payload has extra glyph beyond {text!r}")
        char = expected_chars[seen]
        actual = slot_raw(rom, base, slot, stride)
        gate(actual == packer(char, font), f"{label} painted glyph for {char!r} is not at slot 0x{slot:04X}")
        seen += 1
    gate(seen == len(expected_chars), f"payload missing glyphs for {text!r}")


def verify_payload_painted_12x12(
    rom: bytes | bytearray,
    payload: bytes,
    text: str,
    font: fontpair.BdfFont,
) -> None:
    verify_payload_painted(
        rom,
        payload,
        text,
        font,
        base=FONT12_RELOCATED,
        stride=fontops.FONT_12X12_STRIDE,
        packer=packed_12x12,
        label="12x12",
    )


def paint_8x16_matching_12x12_slot(
    candidate: bytearray,
    original: bytes,
    records: list[dict[str, Any]],
    slot: int,
    char: str,
    font8: fontpair.BdfFont,
) -> int | None:
    """Paint 8x16 Hangul onto the slot already used by 12x12, if that cell is free."""
    live8, _live12 = unified.collect_live_slots(original, records)
    current8 = slot_raw(candidate, FONT8_RELOCATED, slot, fontops.FONT_8X16_STRIDE)
    native8 = slot_raw(original, fontops.FONT_8X16_BASE, slot, fontops.FONT_8X16_STRIDE)
    wanted = packed_8x16(char, font8)
    if current8 == wanted:
        return None
    gate(slot not in live8, f"8x16 slot 0x{slot:04X} is still live Japanese; cannot paint {char!r}")
    gate(current8 == native8, f"8x16 slot 0x{slot:04X} is already painted; cannot steal it for {char!r}")
    return paint_8x16(candidate, slot, char, font8)


def tokens_from_recovered(slots: dict[str, int]) -> dict[str, int]:
    return {char: token_from_slot(slot) for char, slot in slots.items()}
