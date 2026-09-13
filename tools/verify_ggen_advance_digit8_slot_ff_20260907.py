#!/usr/bin/env python3
"""Verify 12x12 Korean digit 8 now uses slot 0x00FF (glyph 8)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import build_ggen_advance_unified_rom_poc as unified  # noqa: E402
import patch_ggen_advance_digit8_slot_ff_20260907 as b  # noqa: E402
from ggen_advance_painted_glyph_identity import FONT12_RELOCATED, slot_raw  # noqa: E402
from ggen_advance_text_codec import expand_to_slots, load_dictionary, read_tokens  # noqa: E402
from ggen_advance_text_codec import DICT_12X12_BASE, DICT_12X12_END  # noqa: E402
from patch_ggen_advance_intermission_text_consumers_20260904 import gate, sha256, u32  # noqa: E402
import build_ggen_advance_ko_poc as fontops  # noqa: E402


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    manifest = json.loads(b.MANIFEST.read_text(encoding="utf-8"))
    parent = b.MAIN_TIP_ROM.read_bytes()
    rom = (b.ROOT / manifest["output"]["path"]).read_bytes()
    jp = b.ORIGINAL_ROM.read_bytes()
    gate(sha256(parent) == manifest["parent"]["sha256"], "parent hash drift")
    gate(sha256(rom) == manifest["output"]["sha256"], "candidate hash drift")
    gate(manifest["verification"]["result"] == "PASS", "manifest verification is not PASS")

    verified = unified.load_verified_charmap(b.CHARMAP)
    gate(verified.get("8") == 0x00FF, "encoder 8 is not 0x00FF")
    gate(verified.get("7") == 0x00FE, "encoder 7 is not 0x00FE")

    fe = slot_raw(rom, FONT12_RELOCATED, 0x00FE, fontops.FONT_12X12_STRIDE)
    ff = slot_raw(rom, FONT12_RELOCATED, 0x00FF, fontops.FONT_12X12_STRIDE)
    fe_jp = slot_raw(jp, fontops.FONT_12X12_BASE, 0x00FE, fontops.FONT_12X12_STRIDE)
    ff_jp = slot_raw(jp, fontops.FONT_12X12_BASE, 0x00FF, fontops.FONT_12X12_STRIDE)
    gate(fe == fe_jp and ff == ff_jp, "digit glyphs were overwritten")
    gate(fe != ff, "slots 0x00FE and 0x00FF collapsed")

    lookup = b.load_lookup_entries(rom)
    amada = [entry for entry in lookup if entry[1] == b.AMADA_SECOND_ORIG]
    gate(len(amada) == 1, "Amada intro lookup missing")
    tokens, _raw = read_tokens(rom, amada[0][2] - 0x08000000)
    gate(b.WRONG_TOKEN not in tokens, "Amada intro still has 0x00FE")
    gate(b.RIGHT_TOKEN in tokens, "Amada intro missing 0x00FF")

    jp_tokens, _ = read_tokens(jp, 0x00F717BA)
    dic = load_dictionary(jp, DICT_12X12_BASE, DICT_12X12_END)
    jp_slots = expand_to_slots(jp_tokens, dic)
    gate(0x00FF in jp_slots, "JP Amada intro no longer uses slot 0x00FF")
    gate(rom[b.MAP_BANK[0] : b.MAP_BANK[1]] == parent[b.MAP_BANK[0] : b.MAP_BANK[1]], "map bank mutated")

    merged = json.loads(b.TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    ez8 = next(row for row in merged["records"] if row["record_id"] == b.EZ8_8X16)
    ez8_off = int(str(ez8["owner_ids"][0]).removeprefix("OWNER-U32-"), 16)
    ez8_tokens, _ = read_tokens(rom, u32(rom, ez8_off) - 0x08000000)
    parent_ez8, _ = read_tokens(parent, u32(parent, ez8_off) - 0x08000000)
    gate(ez8_tokens == parent_ez8, "8x16 Ez8 mutated")

    leftover = 0
    for _pos, _orig, neu, _end in lookup:
        tokens, _raw = read_tokens(rom, neu - 0x08000000)
        leftover += sum(1 for token in tokens if token == b.WRONG_TOKEN)
    gate(leftover == 0, f"map-script Korean still has {leftover} 0x00FE-as-8 tokens")

    print(
        "PASS: 12x12 digit 8 encodes as 0x00FF; Amada 제08MS소대 payload retargeted; "
        "map bank and 8x16 Ez8 unchanged."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
