#!/usr/bin/env python3
"""Patch the verified extended unit-name bank into the current MainTip.

The unified ROM builder starts from the clean Japanese ROM, while the active
MainTip also contains separately approved graphics/UI fixes.  For this narrow
follow-up, start from the current MainTip and append only the 83 translated
<07FC> name payloads, then redirect their 92 measured entity-record pointers.
Pending rows are left byte-for-byte untouched.
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

# The preceding unified ROM POC recorded this as the exclusive end of its
# append-only text allocations.  It is a zero-filled range in the active
# MainTip and leaves the later 0x01230000 resource intact.
EXTENSION_START = 0x01112598
TEXT_END = 0x01240000
EXPECTED_JAPANESE_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"


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


def main() -> int:
    current = bytearray(MAIN_TIP_PATH.read_bytes())
    japanese = JAPANESE_ROM_PATH.read_bytes()
    merged = json.loads(MERGED_PATH.read_text(encoding="utf-8"))
    apply_map = load_8x16_charmap()
    verified_charmap = unified_rom.load_verified_charmap(unified_rom.CHARMAP_8X16_PATH)

    check(len(current) == 32 * 1024 * 1024, "current MainTip is not 32 MiB")
    check(len(japanese) == 16 * 1024 * 1024, "Japanese ROM is not 16 MiB")
    check(sha256(japanese) == EXPECTED_JAPANESE_SHA256, "Japanese ROM SHA-256 drift")
    check(merged.get("source", {}).get("sha256", "").lower() == EXPECTED_JAPANESE_SHA256, "merged source SHA drift")

    rows = sorted(
        [
            row
            for row in merged.get("records", [])
            if row.get("record_id", "").startswith("GGA-UI-EXT-")
        ],
        key=lambda row: parse_hex(row["target_file_offset"], f"{row['record_id']}.target_file_offset"),
    )
    check(len(rows) == 85, f"extended unit-name row count drift: {len(rows)}")
    owners_by_id = {str(owner["owner_id"]): owner for owner in merged.get("owners", [])}
    translated_rows = [row for row in rows if row.get("translation_status") == "translated" and row.get("translation_policy") == "translate"]
    pending_rows = [row for row in rows if row.get("translation_status") != "translated"]
    check(len(translated_rows) == 83, f"translated extension row count drift: {len(translated_rows)}")
    check(len(pending_rows) == 2, f"pending extension row count drift: {len(pending_rows)}")

    blob = bytearray()
    new_targets: dict[int, int] = {}
    owner_patches: dict[int, tuple[int, int]] = {}
    for row in rows:
        old_offset = parse_hex(row["target_file_offset"], f"{row['record_id']}.target_file_offset")
        original = raw_bytes(row["raw_hex"])
        check(japanese[old_offset : old_offset + len(original)] == original, f"Japanese source bytes drift: {row['record_id']}")
        check(current[old_offset : old_offset + len(original)] == original, f"active MainTip source bytes already changed: {row['record_id']}")
        for owner_id in row.get("owner_ids", []):
            owner = owners_by_id.get(str(owner_id))
            check(owner is not None, f"owner missing from merged source: {owner_id}")
            source = parse_hex(owner["source_file_offset"], f"{owner_id}.source_file_offset")
            check(int(owner["pointer_width"]) == 4, f"extension owner is not u32: {owner_id}")
            check(struct.unpack_from("<I", japanese, source)[0] == ROM_BASE + old_offset, f"Japanese owner pointer drift: {owner_id}")
            check(struct.unpack_from("<I", current, source)[0] == ROM_BASE + old_offset, f"active owner pointer already changed: {owner_id}")
            check(source not in owner_patches, f"duplicate extension owner patch: 0x{source:08X}")
            owner_patches[source] = (old_offset, 0)

        if row in pending_rows:
            continue
        text = str(row.get("translation_ko") or "")
        check(text.strip(), f"translated extension row has no Korean text: {row['record_id']}")
        encoded, missing = unified_rom.encode_korean_text(
            text,
            apply_map,
            verified_charmap=verified_charmap,
            strict_punctuation=False,
        )
        check(encoded is not None and not missing, f"Korean encode failed for {row['record_id']}: {missing}")
        prefix = unified_rom.leading_reserved_prefix(original)
        check(prefix == b"\xE7\x1C", f"extension leading marker drift: {row['record_id']}")
        payload = prefix + encoded
        rel = len(blob)
        blob.extend(payload)
        new_targets[old_offset] = ROM_BASE + EXTENSION_START + rel

    check(len(owner_patches) == 92, f"extension owner patch count drift: {len(owner_patches)}")
    check(EXTENSION_START % 4 == 0, "extension start is not aligned")
    extension_end = EXTENSION_START + len(blob)
    check(extension_end <= TEXT_END, "extension text allocation exceeds safe text region")
    check(current[EXTENSION_START:extension_end] == b"\x00" * len(blob), "extension allocation overlaps existing MainTip data")

    before = bytes(current)
    current[EXTENSION_START:extension_end] = blob
    redirected_owner_patches = {
        source: old_offset
        for source, (old_offset, _unused) in owner_patches.items()
        if old_offset in new_targets
    }
    for source, old_offset in redirected_owner_patches.items():
        struct.pack_into("<I", current, source, new_targets[old_offset])

    allowed = set(range(EXTENSION_START, extension_end))
    for source in redirected_owner_patches:
        allowed.update(range(source, source + 4))
    changed = {index for index, (left, right) in enumerate(zip(before, current)) if left != right}
    unexpected = sorted(changed - allowed)
    check(not unexpected, f"unexpected MainTip changes: {len(unexpected)}")

    for row in translated_rows:
        old_offset = parse_hex(row["target_file_offset"], f"{row['record_id']}.target_file_offset")
        destination = new_targets[old_offset] - ROM_BASE
        original = raw_bytes(row["raw_hex"])
        prefix = unified_rom.leading_reserved_prefix(original)
        encoded, missing = unified_rom.encode_korean_text(
            str(row["translation_ko"]),
            apply_map,
            verified_charmap=verified_charmap,
            strict_punctuation=False,
        )
        check(encoded is not None and not missing, f"post-encode failed for {row['record_id']}: {missing}")
        check(current[destination : destination + len(prefix) + len(encoded)] == prefix + encoded, f"relocated payload mismatch: {row['record_id']}")
        for owner_id in row.get("owner_ids", []):
            source = parse_hex(owners_by_id[str(owner_id)]["source_file_offset"], f"{owner_id}.source_file_offset")
            check(struct.unpack_from("<I", current, source)[0] == new_targets[old_offset], f"owner redirect mismatch: {owner_id}")

    for row in pending_rows:
        old_offset = parse_hex(row["target_file_offset"], f"{row['record_id']}.target_file_offset")
        original = raw_bytes(row["raw_hex"])
        check(current[old_offset : old_offset + len(original)] == original, f"pending source bytes changed: {row['record_id']}")
        for owner_id in row.get("owner_ids", []):
            source = parse_hex(owners_by_id[str(owner_id)]["source_file_offset"], f"{owner_id}.source_file_offset")
            check(struct.unpack_from("<I", current, source)[0] == ROM_BASE + old_offset, f"pending owner moved: {owner_id}")

    out_dir = ROOT / "outputs" / "20260830_ggen_advance_extended_unit_names"
    out_path = out_dir / "ggen_advance_extended_unit_names_main_tip_candidate_20260830.gba"
    manifest_path = ROOT / "analysis" / "ggen_advance_extended_unit_names_main_tip_20260830.json"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(current)
    manifest = {
        "schema_version": 1,
        "kind": "ggen_advance_extended_unit_names_main_tip_poc",
        "result": "PASS",
        "source": {
            "base_main_tip": MAIN_TIP_PATH.name,
            "base_main_tip_sha256": sha256(before),
            "japanese_rom": JAPANESE_ROM_PATH.name,
            "japanese_rom_sha256": sha256(japanese),
            "merged_translation_source": str(MERGED_PATH.relative_to(ROOT)).replace("\\", "/"),
            "merged_translation_sha256": sha256(MERGED_PATH.read_bytes()),
            "merged_record_identity_sha256": merged.get("identity", {}).get("record_identity_sha256"),
        },
        "extension": {
            "record_count": len(rows),
            "translated_count": len(translated_rows),
            "pending_count": len(pending_rows),
            "owner_count": len(owner_patches),
            "source_range": ["0x0017AFFA", "0x0017B344"],
            "allocation": {
                "file_offset": f"0x{EXTENSION_START:08X}",
                "end_exclusive": f"0x{extension_end:08X}",
                "size": len(blob),
                "leading_marker_preserved": "<07FC>",
            },
            "pending_rows": [row["record_id"] for row in pending_rows],
        },
        "output": {
            "path": str(out_path.relative_to(ROOT)).replace("\\", "/"),
            "size": len(current),
            "sha256": sha256(current),
        },
        "verification": {
            "result": "PASS",
            "changed_byte_count": len(changed),
            "unexpected_changed_byte_count": len(unexpected),
            "translated_payloads_verified": len(translated_rows),
            "pending_rows_unmoved": len(pending_rows),
            "owner_pointers_verified": len(owner_patches),
            "owner_pointers_redirected": len(redirected_owner_patches),
            "base_main_tip_bytes_preserved_except_extension": True,
            "japanese_source_bytes_verified": True,
            "leading_reserved_marker_preserved": True,
            "allocation_zero_filled_before_write": True,
        },
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
