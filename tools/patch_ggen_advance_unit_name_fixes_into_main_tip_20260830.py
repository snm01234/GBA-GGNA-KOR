#!/usr/bin/env python3
"""Append the user-confirmed remaining unit-name translations to MainTip.

The canonical workbook is built from the clean Japanese ROM, while the
approved MainTip already contains the earlier graphics and extended-name
changes.  This narrow patch starts from that current MainTip, appends only the
eight confirmed unit-name payloads, and redirects only their measured owner
pointers.  Every other byte, including unresolved unit-name candidates, is
left untouched.
"""
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
CHARMAP_PATH = ROOT / "analysis" / "ggen_advance_korean_apply_charmap_20260843.json"
OUTPUT_DIR = ROOT / "outputs" / "20260830_ggen_advance_unit_name_fixes"
OUTPUT_PATH = OUTPUT_DIR / "ggen_advance_unit_name_fixes_main_tip_candidate_20260830.gba"
MANIFEST_PATH = ROOT / "analysis" / "ggen_advance_unit_name_fixes_main_tip_20260830.json"

# The earlier approved extension allocation ends immediately before this
# location.  The extra byte gap preserves the previous manifest's inclusive /
# exclusive-end ambiguity and remains in the zero-filled safe text region.
EXTENSION_START = 0x011129F4
TEXT_END = 0x01240000
EXPECTED_JAPANESE_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"
EXPECTED_BASE_MAIN_TIP_SHA256 = "b1f855702ea4a34b89bb93b879aab188a4336b67b132dcaad9afbbfb592567a6"
EXPECTED_RECORD_IDENTITY_SHA256 = "2764a87d0ac3f5d42392b95250b816d1f32ee6bc050053e770e079a4736402f2"

TARGET_TRANSLATIONS = {
    "GGA-TEXT-0017A308": "백식<MBL>",
    "GGA-TEXT-0017AA30": "백식<MBL>",
    "GGA-TEXT-0017D3D9": "백식<MBL>",
    "GGA-UI-EXT-0017B0C0": "백식<MBL>",
    "GGA-TEXT-0017AE03": "아크엔젤",
    "GGA-TEXT-0017A4AB": "V대시 건담",
    "GGA-TEXT-0017AB31": "V대시 건담",
    "GGA-UI-EXT-0017B1C1": "V대시 건담",
}


def fail(message: str) -> None:
    raise SystemExit(f"gate failed: {message}")


def check(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def sha256(value: bytes | bytearray) -> str:
    return hashlib.sha256(value).hexdigest()


def parse_hex(value: Any, field: str) -> int:
    text = str(value).strip()
    check(text.lower().startswith("0x"), f"{field} is not hexadecimal: {value!r}")
    return int(text, 16)


def raw_bytes(value: str) -> bytes:
    return bytes.fromhex(str(value).replace(" ", ""))


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
    check(result, "8x16 apply-charmap is empty")
    return result


def read_u32(data: bytes | bytearray, offset: int) -> int:
    check(0 <= offset <= len(data) - 4, f"u32 pointer offset out of range: 0x{offset:08X}")
    return struct.unpack_from("<I", data, offset)[0]


def main() -> int:
    current = bytearray(MAIN_TIP_PATH.read_bytes())
    japanese = JAPANESE_ROM_PATH.read_bytes()
    merged = json.loads(MERGED_PATH.read_text(encoding="utf-8"))
    apply_map = load_8x16_charmap()
    verified_charmap = unified_rom.load_verified_charmap(unified_rom.CHARMAP_8X16_PATH)

    check(len(current) == 32 * 1024 * 1024, "current MainTip is not 32 MiB")
    check(sha256(current) == EXPECTED_BASE_MAIN_TIP_SHA256, "current MainTip SHA-256 is not the expected prior approval")
    check(len(japanese) == 16 * 1024 * 1024, "Japanese ROM is not 16 MiB")
    check(sha256(japanese) == EXPECTED_JAPANESE_SHA256, "Japanese ROM SHA-256 drift")
    check(merged.get("source", {}).get("sha256", "").lower() == EXPECTED_JAPANESE_SHA256, "merged source SHA drift")
    check(merged.get("identity", {}).get("record_identity_sha256") == EXPECTED_RECORD_IDENTITY_SHA256, "merged record identity drift")

    by_id = {str(row.get("record_id")): row for row in merged.get("records", [])}
    check(len(by_id) == len(merged.get("records", [])), "duplicate record IDs in merged source")
    rows = []
    for record_id, expected_translation in TARGET_TRANSLATIONS.items():
        row = by_id.get(record_id)
        check(row is not None, f"target row missing from merged source: {record_id}")
        check(row.get("scope_status") == "included", f"target row is not included: {record_id}")
        check(row.get("semantic_category") == "unit_name", f"target row is not unit_name: {record_id}")
        check(row.get("translation_policy") == "translate", f"target row is not translatable: {record_id}")
        check(row.get("translation_status") == "translated", f"target row is not translated: {record_id}")
        check(row.get("translation_ko") == expected_translation, f"target translation drift: {record_id}")
        rows.append(row)
    rows.sort(key=lambda row: parse_hex(row["target_file_offset"], f"{row['record_id']}.target_file_offset"))

    owners_by_id = {str(owner["owner_id"]): owner for owner in merged.get("owners", [])}
    blob = bytearray()
    new_targets: dict[int, int] = {}
    owner_patches: dict[int, dict[str, Any]] = {}
    payload_meta: list[dict[str, Any]] = []

    for row in rows:
        record_id = str(row["record_id"])
        old_offset = parse_hex(row["target_file_offset"], f"{record_id}.target_file_offset")
        original = raw_bytes(row["raw_hex"])
        check(old_offset not in new_targets, f"duplicate target file offset: 0x{old_offset:08X}")
        check(japanese[old_offset : old_offset + len(original)] == original, f"Japanese source bytes drift: {record_id}")
        check(current[old_offset : old_offset + len(original)] == original, f"active MainTip source bytes already changed: {record_id}")

        owner_ids = [str(owner_id) for owner_id in row.get("owner_ids", [])]
        check(owner_ids, f"target row has no measured owner: {record_id}")
        for owner_id in owner_ids:
            owner = owners_by_id.get(owner_id)
            check(owner is not None, f"owner missing from merged source: {owner_id}")
            source = parse_hex(owner["source_file_offset"], f"{owner_id}.source_file_offset")
            check(int(owner["pointer_width"]) == 4, f"target owner is not u32: {owner_id}")
            japanese_pointer = read_u32(japanese, source)
            check(japanese_pointer == ROM_BASE + old_offset, f"Japanese owner pointer drift: {owner_id}")
            current_pointer = read_u32(current, source)
            check(current_pointer >= ROM_BASE, f"active owner pointer is not a GBA pointer: {owner_id}")
            current_file_offset = current_pointer - ROM_BASE
            check(current_file_offset + len(original) <= len(current), f"active owner target out of range: {owner_id}")
            check(current[current_file_offset : current_file_offset + len(original)] == original, f"active owner target bytes drift: {owner_id}")
            check(source not in owner_patches, f"duplicate owner pointer patch: 0x{source:08X}")
            owner_patches[source] = {
                "owner_id": owner_id,
                "record_id": record_id,
                "old_pointer": current_pointer,
                "old_pointer_file_offset": current_file_offset,
                "new_pointer": None,
            }

        encoded, missing = unified_rom.encode_korean_text(
            str(row["translation_ko"]),
            apply_map,
            verified_charmap=verified_charmap,
            strict_punctuation=False,
        )
        check(encoded is not None and not missing, f"Korean encode failed for {record_id}: {missing}")
        prefix = unified_rom.leading_reserved_prefix(original)
        payload = prefix + encoded
        rel = len(blob)
        blob.extend(payload)
        destination = ROM_BASE + EXTENSION_START + rel
        new_targets[old_offset] = destination
        payload_meta.append(
            {
                "record_id": record_id,
                "source_text": row.get("source_text"),
                "translation_ko": row["translation_ko"],
                "target_file_offset": f"0x{old_offset:08X}",
                "old_raw_hex": original.hex(" ").upper(),
                "preserved_leading_prefix_hex": prefix.hex(" ").upper(),
                "encoded_translation_hex": encoded.hex(" ").upper(),
                "payload_hex": payload.hex(" ").upper(),
                "payload_file_offset": f"0x{EXTENSION_START + rel:08X}",
                "payload_size": len(payload),
                "owner_ids": owner_ids,
            }
        )

    check(len(rows) == 8, f"target row count drift: {len(rows)}")
    check(len(owner_patches) == 8, f"owner pointer count drift: {len(owner_patches)}")
    check(EXTENSION_START % 4 == 0, "extension start is not aligned")
    extension_end = EXTENSION_START + len(blob)
    check(extension_end <= TEXT_END, "unit-name text allocation exceeds safe text region")
    check(current[EXTENSION_START:extension_end] == b"\x00" * len(blob), "unit-name allocation overlaps existing MainTip data")

    before = bytes(current)
    current[EXTENSION_START:extension_end] = blob
    for source, patch in owner_patches.items():
        old_offset = parse_hex(by_id[patch["record_id"]]["target_file_offset"], f"{patch['record_id']}.target_file_offset")
        new_pointer = new_targets[old_offset]
        struct.pack_into("<I", current, source, new_pointer)
        patch["new_pointer"] = new_pointer

    allowed = set(range(EXTENSION_START, extension_end))
    allowed.update(index for source in owner_patches for index in range(source, source + 4))
    changed = {index for index, (left, right) in enumerate(zip(before, current)) if left != right}
    unexpected = sorted(changed - allowed)
    check(not unexpected, f"unexpected MainTip changes: {len(unexpected)}")

    for item in payload_meta:
        payload_offset = int(item["payload_file_offset"], 16)
        payload = bytes.fromhex(item["payload_hex"].replace(" ", ""))
        check(current[payload_offset : payload_offset + len(payload)] == payload, f"relocated payload mismatch: {item['record_id']}")
    for source, patch in owner_patches.items():
        check(read_u32(current, source) == patch["new_pointer"], f"owner redirect mismatch: {patch['owner_id']}")

    # The old Japanese payloads and any pre-existing MainTip text remain intact.
    for row in rows:
        old_offset = parse_hex(row["target_file_offset"], f"{row['record_id']}.target_file_offset")
        original = raw_bytes(row["raw_hex"])
        check(japanese[old_offset : old_offset + len(original)] == original, f"post-write Japanese source mismatch: {row['record_id']}")
        check(current[old_offset : old_offset + len(original)] == original, f"post-write source mismatch: {row['record_id']}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_bytes(current)
    merged_sha = sha256(MERGED_PATH.read_bytes())
    manifest = {
        "schema_version": 1,
        "kind": "ggen_advance_unit_name_fixes_main_tip_poc",
        "result": "PASS",
        "source": {
            "base_main_tip": MAIN_TIP_PATH.name,
            "base_main_tip_sha256": sha256(before),
            "japanese_rom": JAPANESE_ROM_PATH.name,
            "japanese_rom_sha256": sha256(japanese),
            "merged_translation_source": str(MERGED_PATH.relative_to(ROOT)).replace("\\", "/"),
            "merged_translation_sha256": merged_sha,
            "merged_record_identity_sha256": merged.get("identity", {}).get("record_identity_sha256"),
            "merged_translation_overlay_identity_sha256": merged.get("identity", {}).get("translation_overlay_identity_sha256"),
        },
        "unit_name_fix": {
            "record_count": len(rows),
            "owner_count": len(owner_patches),
            "mapping": {
                "V<07E8>ガンダム": "V대시 건담",
                "百式<MB<00EC>>": "백식<MBL>",
                "アークエンジェル<021D>": "아크엔젤",
            },
            "records": payload_meta,
            "owner_pointers": sorted(
                [
                    {
                        **patch,
                        "old_pointer": f"0x{patch['old_pointer']:08X}",
                        "old_pointer_file_offset": f"0x{patch['old_pointer_file_offset']:08X}",
                        "new_pointer": f"0x{patch['new_pointer']:08X}",
                    }
                    for patch in owner_patches.values()
                ],
                key=lambda item: item["owner_id"],
            ),
            "allocation": {
                "file_offset": f"0x{EXTENSION_START:08X}",
                "end_exclusive": f"0x{extension_end:08X}",
                "size": len(blob),
                "safe_text_end_exclusive": f"0x{TEXT_END:08X}",
                "leading_reserved_markers_preserved": True,
            },
        },
        "output": {
            "path": str(OUTPUT_PATH.relative_to(ROOT)).replace("\\", "/"),
            "size": len(current),
            "sha256": sha256(current),
        },
        "verification": {
            "result": "PASS",
            "changed_byte_count": len(changed),
            "unexpected_changed_byte_count": len(unexpected),
            "translated_payloads_verified": len(payload_meta),
            "owner_pointers_verified": len(owner_patches),
            "owner_pointers_redirected": len(owner_patches),
            "base_main_tip_bytes_preserved_except_unit_name_allocation_and_pointers": True,
            "japanese_source_bytes_verified": True,
            "active_owner_target_bytes_verified": True,
            "allocation_zero_filled_before_write": True,
        },
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
