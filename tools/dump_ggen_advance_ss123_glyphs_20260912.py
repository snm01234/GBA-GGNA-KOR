#!/usr/bin/env python3
"""Render 8x16 slots and Bio Field animation IDs for the ss123 fix."""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import build_ggen_advance_ko_poc as fontops  # noqa: E402
import build_ggen_advance_turn_ability_overlays_20260905 as ability  # noqa: E402
import ggen_advance_painted_glyph_identity as glyph  # noqa: E402
import patch_ggen_profile_followup2_20260912 as f2  # noqa: E402
from ggen_advance_project_paths import MAIN_TIP_ROM, ORIGINAL_ROM, TRANSLATION_MERGED_JSON
from ggen_advance_text_codec import DICT_8X16_BASE, DICT_8X16_END, ROM_BASE, load_dictionary

OUT = ROOT / "outputs" / "20260912_ss123_zeon_nt001_biofield"
SLOTS = (0x00C8, 0x01A9, 0x01C0, 0x0782)


def decode_tile(raw: bytes) -> list[list[int]]:
    return [
        [((raw[y * 4 + x // 2] >> (4 * (x & 1))) & 0xF) for x in range(8)]
        for y in range(8)
    ]


def glyph_image(rom: bytes, slot: int, relocated: bool) -> Image.Image:
    base = glyph.FONT8_RELOCATED if relocated else fontops.FONT_8X16_BASE
    raw = glyph.slot_raw(rom, base, slot, fontops.FONT_8X16_STRIDE)
    tile = decode_tile(raw)
    img = Image.new("L", (8, 8), 0)
    for y in range(8):
        for x in range(8):
            img.putpixel((x, y), 255 if tile[y][x] else 0)
    return img.resize((64, 64), Image.Resampling.NEAREST)


def plate_ids(values: list[int], tile_count: int) -> list[list[int]]:
    plates = []
    i = 0
    while i < len(values):
        v = values[i]
        if not (8 <= v < tile_count):
            i += 1
            continue
        run = [v]
        i += 1
        while i < len(values):
            nxt = values[i]
            if not (6 <= nxt < tile_count):
                break
            if nxt == 64 and i + 1 < len(values) and values[i + 1] in {1, 4, 7}:
                break
            run.append(nxt)
            i += 1
            if len(run) >= 16:
                break
        if len(run) >= 6:
            plates.append(run)
    return plates


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    rom = MAIN_TIP_ROM.read_bytes()
    japan = ORIGINAL_ROM.read_bytes()
    sheet = Image.new("RGB", (64 * len(SLOTS) * 2 + 32, 96), (20, 20, 24))
    for i, slot in enumerate(SLOTS):
        jp = glyph_image(japan, slot, relocated=False)
        ko = glyph_image(rom, slot, relocated=True)
        sheet.paste(jp.convert("RGB"), (i * 128, 16))
        sheet.paste(ko.convert("RGB"), (i * 128 + 64, 16))
        jp.save(OUT / f"slot_{slot:04X}_jp.png")
        ko.save(OUT / f"slot_{slot:04X}_live.png")
    sheet.save(OUT / "slots_jp_live.png")

    live_ptr = struct.unpack_from("<I", rom, ability.ABILITY_POINTER)[0]
    hdr, blob = ability.resource_blob(rom, live_ptr)
    records = ability.animation_records(blob, hdr)
    bio = []
    for index, rec in enumerate(records):
        values = list(struct.unpack_from(f"<{len(rec) // 2}H", rec))
        if any(240 <= v <= 245 for v in values):
            plates = plate_ids(values, hdr["tiles"])
            bio.append({"anim": index, "plates": plates, "hits": [v for v in values if 228 <= v <= 245]})
    (OUT / "bio_frames.json").write_text(json.dumps(bio, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    dict8 = load_dictionary(rom, DICT_8X16_BASE, DICT_8X16_END)
    hangul = f2.hangul_slot_map(rom, mode=8)
    pending = []
    for row in merged["records"]:
        if row.get("semantic_category") not in {"character_name", "character_name_alternate", "unit_name", "unit_name_alternate"}:
            continue
        source = str(row.get("source_text") or "")
        ko = str(row.get("translation_ko") or "")
        if "ジオン" in source or "지온" in ko:
            owners = [
                int(str(oid).removeprefix("OWNER-U32-"), 16)
                for oid in row.get("owner_ids") or []
                if str(oid).startswith("OWNER-U32-")
            ]
            lives = []
            for owner in owners:
                ptr = struct.unpack_from("<I", rom, owner)[0]
                lives.append(f2.decode_text(rom, ptr, dict8, hangul))
            pending.append(
                {
                    "id": row.get("record_id"),
                    "cat": row.get("semantic_category"),
                    "status": row.get("translation_status"),
                    "source": source,
                    "ko": ko,
                    "live": lives,
                }
            )
    print(json.dumps({"bio": bio, "zion": pending}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
