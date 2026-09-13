#!/usr/bin/env python3
"""Patch only the context-confirmed Nu Gundam unit-name rows into MainTip."""
from __future__ import annotations

import hashlib
import json
import struct
import sys
from pathlib import Path
from typing import Any


TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import build_ggen_advance_unified_rom_poc as unified_rom  # noqa: E402


ROM_BASE = 0x08000000
MAIN_TIP_PATH = ROOT / "SD Gundam GGeneration Advance (Korean).gba"
JAPANESE_ROM_PATH = ROOT / "SD Gundam GGeneration Advance (Japan).gba"
MERGED_PATH = ROOT / "integrated" / "translation" / "ggen_advance_translation_merged.json"
TRANSLATION_MANIFEST_PATH = ROOT / "integrated" / "translation" / "ggen_advance_translation_manifest.json"
CHARMAP_PATH = ROOT / "analysis" / "ggen_advance_korean_apply_charmap_20260843.json"
OUTPUT_DIR = ROOT / "outputs" / "20260830_ggen_advance_nu_gundam_main_tip"
OUTPUT_PATH = OUTPUT_DIR / "ggen_advance_nu_gundam_main_tip_candidate_20260830.gba"
MANIFEST_PATH = ROOT / "analysis" / "ggen_advance_nu_gundam_main_tip_20260830.json"

EXTENSION_START = 0x01112A60
TEXT_END = 0x01240000
FONT_8X16_BASE = 0x00094028
FONT_8X16_STRIDE = 32
NU_GLYPH_SLOT = 0x06FC
NU_GLYPH_TOKEN = bytes.fromhex("E6 FC")
EXPECTED_JAPANESE_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"
EXPECTED_BASE_MAIN_TIP_SHA256 = "f033b480bb36aabed3533bdea6dc0ff6da7884ea4ff1e9372cf662edb3295fd6"
EXPECTED_MERGED_SHA256 = "8979b29943099ee95f5051cd1b07803d5265914b83485faa7b31516f679ed8cb"
EXPECTED_RECORD_IDENTITY = "2764a87d0ac3f5d42392b95250b816d1f32ee6bc050053e770e079a4736402f2"
EXPECTED_OVERLAY_IDENTITY = "48926395b0ac1776e562fbd13f07a812cbac8693d1a938a50c537ab8076e90f2"

TARGET_IDS = (
    "GGA-TEXT-0017A5F2",
    "GGA-TEXT-0017A60D",
    "GGA-TEXT-0017ABE3",
    "GGA-TEXT-0017ABEC",
    "GGA-UI-EXT-0017B273",
    "GGA-UI-EXT-0017B27C",
    "GGA-TEXT-0017D6CD",
    "GGA-TEXT-0017D6DB",
)
PROTECTED_TURN_A_IDS = (
    "GGA-TEXT-0017A70E",
    "GGA-TEXT-0017A734",
    "GGA-TEXT-0017AC78",
    "GGA-TEXT-0017AC8B",
    "GGA-UI-EXT-0017B308",
    "GGA-UI-EXT-0017B31B",
    "GGA-TEXT-0017D7BF",
    "GGA-TEXT-0017D7E1",
)


def check(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_hex(value: Any, field: str) -> int:
    text = str(value).strip()
    check(text.lower().startswith("0x"), f"{field} is not hexadecimal: {value!r}")
    return int(text, 16)


def raw_bytes(value: str) -> bytes:
    return bytes.fromhex(str(value).replace(" ", ""))


def read_u32(data: bytes | bytearray, offset: int) -> int:
    check(0 <= offset <= len(data) - 4, f"u32 offset out of range: 0x{offset:08X}")
    return struct.unpack_from("<I", data, offset)[0]


def load_8x16_charmap() -> dict[str, int]:
    payload = json.loads(CHARMAP_PATH.read_text(encoding="utf-8"))
    result: dict[str, int] = {}
    for item in payload.get("assignments", []):
        char = item.get("char")
        if not isinstance(char, str) or not char:
            continue
        paint = str(item.get("paint") or "")
        if item.get("slot_8x16"):
            result[char] = int(str(item["slot_8x16"]), 16)
        elif paint in {"both", "8x16"} and item.get("slot"):
            result[char] = int(str(item["slot"]), 16)
    check(bool(result), "8x16 apply-charmap is empty")
    return result


def encode(text: str, apply_map: dict[str, int], verified_charmap: dict[str, int]) -> bytes:
    encoded, missing = unified_rom.encode_korean_text(
        text,
        apply_map,
        verified_charmap=verified_charmap,
        strict_punctuation=False,
    )
    check(encoded is not None and not missing, f"Korean encode failed for {text!r}: {missing}")
    return encoded


def main() -> int:
    before = MAIN_TIP_PATH.read_bytes()
    current = bytearray(before)
    japanese = JAPANESE_ROM_PATH.read_bytes()
    merged_raw = MERGED_PATH.read_bytes()
    merged = json.loads(merged_raw)
    translation_manifest = json.loads(TRANSLATION_MANIFEST_PATH.read_text(encoding="utf-8"))
    apply_map = load_8x16_charmap()
    verified_charmap = unified_rom.load_verified_charmap(unified_rom.CHARMAP_8X16_PATH)

    check(len(before) == 32 * 1024 * 1024, "current MainTip is not 32 MiB")
    check(sha256(before) == EXPECTED_BASE_MAIN_TIP_SHA256, "current MainTip SHA-256 drift")
    check(len(japanese) == 16 * 1024 * 1024, "Japanese ROM is not 16 MiB")
    check(sha256(japanese) == EXPECTED_JAPANESE_SHA256, "Japanese ROM SHA-256 drift")
    check(sha256(merged_raw) == EXPECTED_MERGED_SHA256, "merged translation SHA-256 drift")
    check(translation_manifest.get("sha256") == EXPECTED_MERGED_SHA256, "translation manifest SHA drift")
    check(merged.get("identity", {}).get("record_identity_sha256") == EXPECTED_RECORD_IDENTITY, "record identity drift")
    check(merged.get("identity", {}).get("translation_overlay_identity_sha256") == EXPECTED_OVERLAY_IDENTITY, "overlay identity drift")

    records = merged.get("records", [])
    by_id = {str(row.get("record_id")): row for row in records}
    owners_by_id = {str(owner.get("owner_id")): owner for owner in merged.get("owners", [])}
    check(len(by_id) == len(records), "duplicate record IDs")
    check(by_id["GGA-TEXT-0017A5FB"].get("source_text") == "ニューハイパーバズーカ", "Nu weapon context drift")
    check(by_id["GGA-TEXT-0017A602"].get("source_text") == "フィン・ファンネル<0813>", "Fin Funnel context drift")
    check(all(by_id[rid].get("translation_ko") == "ν건담" for rid in TARGET_IDS), "Nu translation target drift")
    check(all("턴에이 건담" in str(by_id[rid].get("translation_ko") or "") for rid in PROTECTED_TURN_A_IDS), "protected Turn A translation drift")

    old_translation = encode("턴에이 건담", apply_map, verified_charmap)
    new_korean_tail = encode("건담", apply_map, verified_charmap)
    nu_glyph_offset = FONT_8X16_BASE + NU_GLYPH_SLOT * FONT_8X16_STRIDE
    japanese_nu_glyph = japanese[nu_glyph_offset:nu_glyph_offset + FONT_8X16_STRIDE]
    check(len(japanese_nu_glyph) == FONT_8X16_STRIDE, "original Nu glyph range drift")
    check(before[nu_glyph_offset:nu_glyph_offset + FONT_8X16_STRIDE] == japanese_nu_glyph, "original Nu 8x16 glyph was overwritten")
    protected_owner_bytes: dict[int, bytes] = {}
    for record_id in PROTECTED_TURN_A_IDS:
        for owner_id in by_id[record_id].get("owner_ids", []):
            owner = owners_by_id[str(owner_id)]
            source = parse_hex(owner["source_file_offset"], f"{owner_id}.source_file_offset")
            protected_owner_bytes[source] = before[source:source + 4]

    blob = bytearray()
    owner_patches: list[dict[str, Any]] = []
    payloads: list[dict[str, Any]] = []
    seen_owner_offsets: set[int] = set()
    for record_id in TARGET_IDS:
        row = by_id[record_id]
        check(row.get("scope_status") == "included", f"target is not included: {record_id}")
        check(row.get("semantic_category") == "unit_name", f"target is not unit_name: {record_id}")
        original_offset = parse_hex(row["target_file_offset"], f"{record_id}.target_file_offset")
        original = raw_bytes(row["raw_hex"])
        check(japanese[original_offset:original_offset + len(original)] == original, f"Japanese source drift: {record_id}")
        prefix = unified_rom.leading_reserved_prefix(original)
        expected_old_payload = prefix + old_translation
        # Reuse the original, still-preserved 8x16 Nu glyph and encode only
        # the Korean tail.  This avoids inventing a substitute such as '뉴'.
        new_payload = prefix + NU_GLYPH_TOKEN + new_korean_tail
        payload_offset = EXTENSION_START + len(blob)
        blob.extend(new_payload)
        payloads.append({
            "record_id": record_id,
            "source_text": row.get("source_text"),
            "translation_ko": row.get("translation_ko"),
            "original_target_file_offset": f"0x{original_offset:08X}",
            "preserved_leading_prefix_hex": prefix.hex(" ").upper(),
            "previous_encoded_translation_hex": old_translation.hex(" ").upper(),
            "preserved_nu_glyph_token_hex": NU_GLYPH_TOKEN.hex(" ").upper(),
            "encoded_korean_tail_hex": new_korean_tail.hex(" ").upper(),
            "payload_hex": new_payload.hex(" ").upper(),
            "payload_file_offset": f"0x{payload_offset:08X}",
            "payload_size": len(new_payload),
            "owner_ids": list(row.get("owner_ids", [])),
        })
        for owner_id in row.get("owner_ids", []):
            owner = owners_by_id[str(owner_id)]
            owner_offset = parse_hex(owner["source_file_offset"], f"{owner_id}.source_file_offset")
            check(owner_offset not in seen_owner_offsets, f"duplicate target owner: 0x{owner_offset:08X}")
            seen_owner_offsets.add(owner_offset)
            japanese_pointer = read_u32(japanese, owner_offset)
            check(japanese_pointer == ROM_BASE + original_offset, f"Japanese owner pointer drift: {owner_id}")
            old_pointer = read_u32(before, owner_offset)
            check(ROM_BASE <= old_pointer < ROM_BASE + len(before), f"active owner pointer out of ROM: {owner_id}")
            old_target = old_pointer - ROM_BASE
            check(before[old_target:old_target + len(expected_old_payload)] == expected_old_payload, f"active 턴에이 payload drift: {owner_id}")
            owner_patches.append({
                "owner_id": str(owner_id),
                "record_id": record_id,
                "owner_file_offset": f"0x{owner_offset:08X}",
                "old_pointer": f"0x{old_pointer:08X}",
                "old_pointer_file_offset": f"0x{old_target:08X}",
                "new_pointer": f"0x{ROM_BASE + payload_offset:08X}",
            })

    check(len(payloads) == 8, f"target payload count drift: {len(payloads)}")
    check(len(owner_patches) == 8, f"target owner count drift: {len(owner_patches)}")
    extension_end = EXTENSION_START + len(blob)
    check(EXTENSION_START % 4 == 0, "extension start is not aligned")
    check(extension_end <= TEXT_END, "Nu allocation exceeds safe text region")
    check(before[EXTENSION_START:extension_end] == b"\x00" * len(blob), "Nu allocation overlaps existing data")

    current[EXTENSION_START:extension_end] = blob
    payload_by_id = {item["record_id"]: item for item in payloads}
    for patch in owner_patches:
        owner_offset = int(patch["owner_file_offset"], 16)
        payload_offset = int(payload_by_id[patch["record_id"]]["payload_file_offset"], 16)
        struct.pack_into("<I", current, owner_offset, ROM_BASE + payload_offset)

    allowed = set(range(EXTENSION_START, extension_end))
    for patch in owner_patches:
        owner_offset = int(patch["owner_file_offset"], 16)
        allowed.update(range(owner_offset, owner_offset + 4))
    changed = {index for index, (left, right) in enumerate(zip(before, current)) if left != right}
    unexpected = sorted(changed - allowed)
    check(not unexpected, f"unexpected changed bytes: {len(unexpected)}")
    check(all(current[offset:offset + 4] == value for offset, value in protected_owner_bytes.items()), "protected Turn A owner changed")
    for item in payloads:
        offset = int(item["payload_file_offset"], 16)
        payload = bytes.fromhex(item["payload_hex"].replace(" ", ""))
        check(current[offset:offset + len(payload)] == payload, f"Nu payload verification failed: {item['record_id']}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_bytes(current)
    manifest = {
        "schema_version": 1,
        "kind": "ggen_advance_nu_gundam_main_tip_candidate",
        "result": "PASS",
        "source": {
            "base_main_tip": MAIN_TIP_PATH.name,
            "base_main_tip_sha256": sha256(before),
            "japanese_rom": JAPANESE_ROM_PATH.name,
            "japanese_rom_sha256": sha256(japanese),
            "merged_translation_source": str(MERGED_PATH.relative_to(ROOT)).replace("\\", "/"),
            "merged_translation_sha256": sha256(merged_raw),
            "merged_record_identity_sha256": merged.get("identity", {}).get("record_identity_sha256"),
            "merged_translation_overlay_identity_sha256": merged.get("identity", {}).get("translation_overlay_identity_sha256"),
        },
        "nu_gundam_fix": {
            "record_count": len(payloads),
            "owner_count": len(owner_patches),
            "mapping": "context-proven Nu Gundam rows: 턴에이 건담 → ν건담",
            "records": payloads,
            "owner_pointers": owner_patches,
            "protected_turn_a_record_ids": list(PROTECTED_TURN_A_IDS),
            "allocation": {
                "file_offset": f"0x{EXTENSION_START:08X}",
                "end_exclusive": f"0x{extension_end:08X}",
                "size": len(blob),
                "safe_text_end_exclusive": f"0x{TEXT_END:08X}",
            },
        },
        "output": {
            "path": str(OUTPUT_PATH.relative_to(ROOT)).replace("\\", "/"),
            "size": len(current),
            "sha256": sha256(current),
        },
        "verification": {
            "result": "PASS",
            "nu_weapon_context_verified": True,
            "translated_payloads_verified": len(payloads),
            "owner_pointers_verified": len(owner_patches),
            "protected_turn_a_records_unchanged": True,
            "previous_turn_a_payloads_verified": True,
            "original_nu_8x16_glyph_preserved_and_reused": True,
            "allocation_zero_filled_before_write": True,
            "changed_byte_count": len(changed),
            "unexpected_changed_byte_count": len(unexpected),
            "base_main_tip_preserved_except_allocation_and_eight_owner_pointers": True,
        },
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
