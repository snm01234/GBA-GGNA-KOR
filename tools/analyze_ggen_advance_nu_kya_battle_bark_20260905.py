#!/usr/bin/env python3
"""Diagnose ν→Hangul collision and untranslated ID-command battle barks.

The captured combat line starts with original token E063 (12x12 slot 0x0143),
which the 12x12 identified charmap treats as ν.  The apply-charmap later
reassigned that slot to Hangul, so untranslated Japanese ν-text renders as
whatever Hangul was painted there.  This pass also checks whether the live
ID-command bark table still points at original Japanese containers.
"""
from __future__ import annotations

import binascii
import hashlib
import json
import struct
import sys
from collections import Counter
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import build_ggen_advance_ko_poc as fontops
import ggen_advance_painted_glyph_identity as identity
import test_ggen_advance_font_pair as fontpair
from ggen_advance_project_paths import (
    ADVANCE_ROOT,
    MAIN_TIP_MANIFEST,
    MAIN_TIP_ROM,
    ORIGINAL_ROM,
    TRANSLATION_MERGED_JSON,
    advance_relative,
)

OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_nu_kya_battle_bark_20260905.json"
APPLY = ADVANCE_ROOT / "analysis" / "ggen_advance_korean_apply_charmap_20260844.json"
CHARMAP12 = ADVANCE_ROOT / "analysis" / "ggen_advance_12x12_identified_charmap_20260828.json"
BARK_OVERLAY = ADVANCE_ROOT / "integrated" / "translation" / "ggen_advance_id_command_battle_barks.json"

NU_SLOT = 0x0143
NU_TOKEN = bytes((0xE0, 0x63))
ID_BARK_TABLE_START = 0x00226984
ID_BARK_TABLE_END = ID_BARK_TABLE_START + 768 * 8
AMURO_CONTINUE_TABLE = 0x00226B14  # character 16 command 2
AMURO_ORIGINAL = 0x00223520


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def slot_raw12(rom: bytes, slot: int) -> bytes:
    return identity.slot_raw(rom, identity.FONT12_RELOCATED, slot, fontops.FONT_12X12_STRIDE)


def slot_raw12_jp(rom: bytes, slot: int) -> bytes:
    return identity.slot_raw(rom, fontops.FONT_12X12_BASE, slot, fontops.FONT_12X12_STRIDE)


def main() -> int:
    main_rom = MAIN_TIP_ROM.read_bytes()
    jp_rom = ORIGINAL_ROM.read_bytes()
    manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(main_rom) == manifest["sha256"], "parent is not current main TIP")

    apply_map = json.loads(APPLY.read_text(encoding="utf-8"))
    cmap12 = json.loads(CHARMAP12.read_text(encoding="utf-8"))
    identified = cmap12.get("verified_charmap") or {}
    gate(identified.get("0x0143") == "ν", "12x12 identified 0x0143 is not ν")

    hangul_by_slot = {
        int(str(row["slot"]), 16): str(row["char"])
        for row in apply_map["assignments"]
        if str(row.get("paint") or "") in {"both", "12x12", "split"} and "가" <= str(row["char"]) <= "힣"
    }
    font12 = identity.load_galmuri12()
    expected_by_glyph = {}
    for char in sorted(set(hangul_by_slot.values()) | {"꺄", "깃"}):
        expected_by_glyph[identity.packed_12x12(char, font12)] = char

    painted_0143 = slot_raw12(main_rom, NU_SLOT)
    jp_0143 = slot_raw12_jp(jp_rom, NU_SLOT)
    painted_as = expected_by_glyph.get(painted_0143)
    metadata_char = hangul_by_slot.get(NU_SLOT)

    collisions = []
    for slot, char in sorted(hangul_by_slot.items()):
        identified_char = identified.get(f"0x{slot:04X}") or identified.get(f"0x{slot:04x}")
        if not identified_char:
            continue
        if identified_char == char:
            continue
        actual = slot_raw12(main_rom, slot)
        jp = slot_raw12_jp(jp_rom, slot)
        collisions.append({
            "slot": f"0x{slot:04X}",
            "identified_original": identified_char,
            "hangul_metadata": char,
            "painted_as": expected_by_glyph.get(actual),
            "still_japanese_glyph": actual == jp,
            "japanese_overwritten": actual != jp,
        })

    # Bark table pointer audit.
    original_ptrs = 0
    relocated_ptrs = 0
    null_ptrs = 0
    other_ptrs = 0
    samples = []
    for index in range(768):
        off = ID_BARK_TABLE_START + index * 8
        ptr = struct.unpack_from("<I", main_rom, off)[0]
        if ptr == 0:
            null_ptrs += 1
            continue
        if 0x082231B4 <= ptr < 0x08226984:
            original_ptrs += 1
        elif 0x09000000 <= ptr < 0x0A000000:
            relocated_ptrs += 1
        else:
            other_ptrs += 1
        if len(samples) < 8 and ptr:
            samples.append({"index": index, "pointer": f"0x{ptr:08X}", "table_off": f"0x{off:08X}"})

    amuro_ptr = struct.unpack_from("<I", main_rom, AMURO_CONTINUE_TABLE)[0]
    amuro_original = bytes(main_rom[AMURO_ORIGINAL:AMURO_ORIGINAL + 16])
    jp_amuro = bytes(jp_rom[AMURO_ORIGINAL:AMURO_ORIGINAL + 16])

    overlay = json.loads(BARK_OVERLAY.read_text(encoding="utf-8"))
    amuro_row = next(row for row in overlay["records"] if row["record_id"] == "GGA-IDBARK-00223520")
    translated_barks = sum(1 for row in overlay["records"] if str(row.get("translation_status")) == "translated" and str(row.get("translation_ko") or "").strip())
    untranslated_barks = sum(1 for row in overlay["records"] if not str(row.get("translation_ko") or "").strip())

    # Live remaining Japanese specials that Hangul stole.
    special_like = [row for row in collisions if row["japanese_overwritten"] and row["identified_original"] in {"ν", "∀", "α", "γ", "β", "Δ", "μ", "λ", "Ω", "I", "F91"}]

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_nu_kya_battle_bark_20260905",
        "result": "PASS",
        "current_main_tip": {"path": advance_relative(MAIN_TIP_ROM), "sha256": sha256(main_rom), "crc32": f"0x{binascii.crc32(main_rom) & 0xFFFFFFFF:08X}"},
        "nu_slot": {
            "slot": "0x0143",
            "token": "0xE063",
            "identified_original": "ν",
            "hangul_metadata": metadata_char,
            "painted_as": painted_as,
            "matches_metadata_hangul": painted_as == metadata_char,
            "matches_kya": painted_as == "꺄",
            "matches_git": painted_as == "깃",
            "still_japanese_nu_glyph": painted_0143 == jp_0143,
            "overwritten": painted_0143 != jp_0143,
        },
        "hangul_over_identified_12x12": collisions,
        "special_like_collisions": special_like,
        "id_bark_table": {
            "start": f"0x{ID_BARK_TABLE_START:08X}",
            "null": null_ptrs,
            "original_japanese_range": original_ptrs,
            "relocated_09": relocated_ptrs,
            "other": other_ptrs,
            "samples": samples,
            "amuro_nu_line": {
                "table_entry": f"0x{AMURO_CONTINUE_TABLE:08X}",
                "pointer": f"0x{amuro_ptr:08X}",
                "points_at_original": amuro_ptr == 0x08223520,
                "original_payload_hex": amuro_original.hex(" ").upper(),
                "japan_payload_hex": jp_amuro.hex(" ").upper(),
                "payload_still_japanese": amuro_original == jp_amuro,
                "starts_with_nu_token": amuro_original.startswith(NU_TOKEN),
                "overlay_translation_ko": amuro_row.get("translation_ko"),
                "overlay_status": amuro_row.get("translation_status"),
            },
            "overlay_translated_count": translated_barks,
            "overlay_empty_ko_count": untranslated_barks,
            "overlay_record_count": len(overlay["records"]),
        },
        "diagnosis": {
            "nu_to_hangul": "12x12 slot 0x0143 is the original ν token E063; Hangul was painted there so untranslated Japanese ν-text renders as that Hangul cell",
            "battle_dialogue_japanese": "ID-command bark table still points at original 0x0822xxxx Japanese containers even though overlay translations exist",
        },
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "out": advance_relative(OUT),
        "nu_slot": report["nu_slot"],
        "collision_count": len(collisions),
        "special_like": special_like,
        "bark_ptrs": {"original": original_ptrs, "relocated": relocated_ptrs, "other": other_ptrs, "null": null_ptrs},
        "amuro": report["id_bark_table"]["amuro_nu_line"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
