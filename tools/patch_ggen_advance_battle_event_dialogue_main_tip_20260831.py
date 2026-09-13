#!/usr/bin/env python3
"""Patch the 49 translated battle-event streams into the current MainTip."""

from __future__ import annotations

import hashlib
import json
import struct
import sys
from pathlib import Path
from typing import Any

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))

import build_ggen_advance_unified_rom_poc as unified  # noqa: E402

ROM_BASE = 0x08000000
MAIN_TIP = ROOT / "SD Gundam GGeneration Advance (Korean).gba"
JAPANESE = ROOT / "SD Gundam GGeneration Advance (Japan).gba"
MERGED = ROOT / "integrated" / "translation" / "ggen_advance_translation_merged.json"
APPLY_CHARMAP = ROOT / "analysis" / "ggen_advance_korean_apply_charmap_20260843.json"
OUTPUT_DIR = ROOT / "outputs" / "20260831_battle_event_dialogue"
OUTPUT_ROM = OUTPUT_DIR / "ggen_advance_battle_event_dialogue_main_tip_candidate.gba"
MANIFEST = ROOT / "analysis" / "ggen_advance_battle_event_dialogue_main_tip_20260831.json"

EXPECTED_BASE_SHA256 = "c115c21a67a36291968f0729b809e6b6278442a1e70ca0e486bc4487e99da3b2"
EXPECTED_SOURCE_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"
EXPECTED_RECORD_IDENTITY = "edce2504eacacb5b7419cf7e7096b8d1c38c2bcccdef273e4bcf81f34cbfa6e7"
EXPECTED_OVERLAY_IDENTITY = "c3be4e422335f9468962b9bc834660e05450d8d2f2fbd09c2cd2d42715a3ec3b"
EXTENSION_START = 0x01230AC4
TEXT_END = 0x01240000
BATCH_ID = "battle-event-dialogue-complete-20260831"


def check(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"gate failed: {message}")


def sha256(value: bytes | bytearray) -> str:
    return hashlib.sha256(value).hexdigest()


def parse_hex(value: Any) -> int:
    return int(str(value), 16)


def load_12x12_apply_map() -> dict[str, int]:
    payload = json.loads(APPLY_CHARMAP.read_text(encoding="utf-8"))
    result: dict[str, int] = {}
    for item in payload["assignments"]:
        char = str(item.get("char") or "")
        paint = str(item.get("paint") or "")
        if not char:
            continue
        if item.get("slot_12x12"):
            result[char] = int(str(item["slot_12x12"]), 16)
        elif paint in {"both", "12x12"} and item.get("slot"):
            result[char] = int(str(item["slot"]), 16)
    check(result, "12x12 apply charmap is empty")
    return result


def main() -> int:
    before = MAIN_TIP.read_bytes()
    japanese = JAPANESE.read_bytes()
    merged_raw = MERGED.read_bytes()
    merged = json.loads(merged_raw)
    check(len(before) == 32 * 1024 * 1024, "current MainTip is not 32 MiB")
    check(sha256(before) == EXPECTED_BASE_SHA256, "current MainTip SHA drift")
    check(sha256(japanese) == EXPECTED_SOURCE_SHA256, "Japanese ROM SHA drift")
    check(merged["identity"]["record_identity_sha256"] == EXPECTED_RECORD_IDENTITY, "record identity drift")
    check(merged["identity"]["translation_overlay_identity_sha256"] == EXPECTED_OVERLAY_IDENTITY, "overlay identity drift")

    rows = sorted(
        [
            row
            for row in merged["records"]
            if row.get("source_scope") == "battle_event_dialogue"
            and row.get("scope_status") == "included"
            and row.get("translation_status") == "translated"
        ],
        key=lambda row: parse_hex(row["target_file_offset"]),
    )
    owners = {owner["owner_id"]: owner for owner in merged["owners"]}
    check(len(rows) == 49, f"battle-event record count drift: {len(rows)}")
    check(all(row.get("overlay_batch_id") == BATCH_ID for row in rows), "battle-event batch drift")

    apply_map = load_12x12_apply_map()
    verified = unified.load_verified_charmap(unified.CHARMAP_12X12_PATH)
    blob = bytearray()
    patches: list[dict[str, Any]] = []
    payloads: list[dict[str, Any]] = []
    current = bytearray(before)
    for row in rows:
        original_offset = parse_hex(row["target_file_offset"])
        original, missing = unified.rebuild_scenario_payload(row, apply_map, verified, translate=False)
        check(original is not None and not missing, f"original rebuild failed: {row['record_id']}")
        check(original == bytes.fromhex(str(row["raw_hex"]).replace(" ", "")), f"original raw drift: {row['record_id']}")
        check(japanese[original_offset:original_offset + len(original)] == original, f"Japanese payload drift: {row['record_id']}")
        translated, missing = unified.rebuild_scenario_payload(row, apply_map, verified, translate=True)
        check(translated is not None and not missing, f"Korean encode failed: {row['record_id']} {missing}")
        payload_offset = EXTENSION_START + len(blob)
        blob.extend(translated)
        payloads.append(
            {
                "record_id": row["record_id"],
                "source_text": row["source_text"],
                "translation_ko": row["translation_ko"],
                "source_file_offset": row["target_file_offset"],
                "payload_file_offset": f"0x{payload_offset:08X}",
                "payload_size": len(translated),
                "payload_sha256": sha256(translated),
            }
        )
        check(len(row["owner_ids"]) == 1, f"owner count drift: {row['record_id']}")
        owner = owners[row["owner_ids"][0]]
        owner_offset = parse_hex(owner["source_file_offset"])
        source_pointer = struct.unpack_from("<I", japanese, owner_offset)[0]
        active_pointer = struct.unpack_from("<I", before, owner_offset)[0]
        check(source_pointer == ROM_BASE + original_offset, f"Japanese owner drift: {owner['owner_id']}")
        check(active_pointer == source_pointer, f"omitted battle-event owner was already modified: {owner['owner_id']}")
        patches.append(
            {
                "owner_id": owner["owner_id"],
                "owner_file_offset": f"0x{owner_offset:08X}",
                "old_pointer": f"0x{active_pointer:08X}",
                "new_pointer": f"0x{ROM_BASE + payload_offset:08X}",
                "record_id": row["record_id"],
            }
        )

    extension_end = EXTENSION_START + len(blob)
    check(extension_end <= TEXT_END, "battle-event allocation exceeds safe text region")
    check(before[EXTENSION_START:extension_end] == b"\x00" * len(blob), "battle-event allocation overlaps current MainTip data")
    check(all(value == 0 for value in before[extension_end:TEXT_END]), "safe text tail is not zero-filled")
    current[EXTENSION_START:extension_end] = blob
    for patch in patches:
        struct.pack_into("<I", current, parse_hex(patch["owner_file_offset"]), parse_hex(patch["new_pointer"]))

    allowed = set(range(EXTENSION_START, extension_end))
    for patch in patches:
        offset = parse_hex(patch["owner_file_offset"])
        allowed.update(range(offset, offset + 4))
    changed = {index for index, (left, right) in enumerate(zip(before, current)) if left != right}
    unexpected = changed - allowed
    check(not unexpected, f"unexpected changed bytes: {len(unexpected)}")
    check(current[0x00D34130:0x00D34588] == before[0x00D34130:0x00D34588], "Japanese battle-event source pool changed")
    for item in payloads:
        start = parse_hex(item["payload_file_offset"])
        check(sha256(current[start:start + item["payload_size"]]) == item["payload_sha256"], f"payload verify failed: {item['record_id']}")
    for patch in patches:
        check(struct.unpack_from("<I", current, parse_hex(patch["owner_file_offset"]))[0] == parse_hex(patch["new_pointer"]), f"owner verify failed: {patch['owner_id']}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_ROM.write_bytes(current)
    manifest = {
        "schema_version": 1,
        "kind": "ggen_advance_battle_event_dialogue_main_tip_candidate",
        "source": {
            "base_main_tip": MAIN_TIP.name,
            "base_main_tip_sha256": sha256(before),
            "japanese_rom_sha256": sha256(japanese),
            "merged_translation_source": str(MERGED.relative_to(ROOT)).replace("\\", "/"),
            "merged_translation_sha256": sha256(merged_raw),
            "merged_record_identity_sha256": merged["identity"]["record_identity_sha256"],
            "merged_translation_overlay_identity_sha256": merged["identity"]["translation_overlay_identity_sha256"],
            "apply_charmap": str(APPLY_CHARMAP.relative_to(ROOT)).replace("\\", "/"),
        },
        "battle_event_dialogue": {
            "record_count": len(payloads),
            "owner_count": len(patches),
            "allocation": {
                "file_offset": f"0x{EXTENSION_START:08X}",
                "end_exclusive": f"0x{extension_end:08X}",
                "size": len(blob),
                "safe_text_end_exclusive": f"0x{TEXT_END:08X}",
            },
            "payloads": payloads,
            "owner_patches": patches,
        },
        "output": {
            "path": str(OUTPUT_ROM.relative_to(ROOT)).replace("\\", "/"),
            "size": len(current),
            "sha256": sha256(current),
        },
        "verification": {
            "result": "PASS",
            "records_encoded": len(payloads),
            "owners_patched": len(patches),
            "translation_width_limit_cells": 15,
            "all_payload_hashes_match": True,
            "all_owner_pointers_match": True,
            "original_japanese_pool_unchanged": True,
            "allocation_zero_filled_before_write": True,
            "changed_byte_count": len(changed),
            "unexpected_changed_byte_count": len(unexpected),
            "current_main_tip_preserved_except_allocation_and_49_owner_pointers": True,
        },
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "output": manifest["output"], "verification": manifest["verification"], "allocation": manifest["battle_event_dialogue"]["allocation"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
