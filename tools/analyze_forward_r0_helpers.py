#!/usr/bin/env python3
"""Close owner provenance for the 44 draw calls that forward helper r0 -> r3.

This tool consumes the advance-local draw inventory and validates the clean-ROM
accessor signatures behind each helper.  It intentionally separates structural
owner closure from exact user-visible semantic naming.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

ROM_BASE = 0x08000000
EXPECTED_SIZE = 16 * 1024 * 1024
EXPECTED_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"

EXPECTED_HELPER_CALLS = {
    0x080072D0: 11,
    0x080051EC: 10,
    0x08006640: 4,
    0x08005474: 3,
    0x08005EDC: 2,
    0x0800752C: 2,
    0x08007974: 2,
    0x080123B0: 2,
    0x0806B148: 2,
    0x08005804: 1,
    0x08005EAC: 1,
    0x08007AA0: 1,
    0x08007AE8: 1,
    0x08012250: 1,
    0x08012308: 1,
}


def u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def thumb_bl_target(data: bytes, offset: int) -> int | None:
    high = u16(data, offset)
    low = u16(data, offset + 2)
    if high & 0xF800 != 0xF000 or low & 0xF800 != 0xF800:
        return None
    displacement = ((high & 0x07FF) << 12) | ((low & 0x07FF) << 1)
    if displacement & (1 << 22):
        displacement -= 1 << 23
    return (ROM_BASE + offset + 4 + displacement) & 0xFFFFFFFF


def check(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"gate failed: {message}")


def count_leading_pointer_records(data: bytes, offset: int, stride: int, max_records: int = 1024) -> int:
    count = 0
    for index in range(max_records):
        value = u32(data, offset + index * stride)
        if not (ROM_BASE <= value < ROM_BASE + len(data)):
            break
        count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rom", type=Path)
    parser.add_argument("--inventory", type=Path, default=Path("legacy/analysis/draw_source_inventory_20260826.json"))
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    data = args.rom.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    check(len(data) == EXPECTED_SIZE, f"unexpected ROM size {len(data)}")
    check(digest == EXPECTED_SHA256, f"unexpected ROM SHA-256 {digest}")

    inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
    groups = {
        int(row["helper_target"], 16): row["draw_call_count"]
        for row in inventory["forward_r0_helper_groups"]
    }
    check(groups == EXPECTED_HELPER_CALLS, f"forward-r0 helper group drift: {groups}")
    check(sum(groups.values()) == 44, "forward-r0 call total drift")

    # entity_name chain: RAM 0x2C record -> u16 id -> 512-entry id map -> 0xAC entity record +4 text.
    check(u32(data, 0x00005204) == 0x0200D3C0, "0x51EC RAM 0x2C table base drift")
    check(u16(data, 0x000051F4) == 0x212C, "0x51EC 0x2C stride drift")
    check(thumb_bl_target(data, 0x000051FC) == 0x08005474, "0x51EC -> 0x5474 chain drift")
    check(thumb_bl_target(data, 0x0000547A) == 0x080045B0, "0x5474 -> entity resolver drift")
    check(u32(data, 0x000045C4) == 0x081A4298, "entity ID map base drift")
    check(u32(data, 0x000045C8) == 0x0818E2E4, "0xAC entity DB base drift")
    check(u16(data, 0x000045BA) == 0x20AC, "0xAC entity record stride drift")
    check(u16(data, 0x0000547E) == 0x6840, "entity record +4 text load drift")

    # character primary text: active slot -> mapped character id -> 0x78-byte character DB +0.
    check(u32(data, 0x00007144) == 0x020056C0, "character slot map base drift")
    check(thumb_bl_target(data, 0x000072D6) == 0x08007138, "0x72D0 character id resolver drift")
    check(thumb_bl_target(data, 0x000072DE) == 0x0800752C, "0x72D0 -> character text accessor drift")
    check(u32(data, 0x00007540) == 0x081A476C, "character DB base drift")
    check(u16(data, 0x00007532) == 0x0101, "character DB stride formula component drift")
    check(u16(data, 0x00007534) == 0x1A09, "character DB stride formula component drift 2")
    check(u16(data, 0x00007536) == 0x00C9, "character DB stride formula component drift 3")
    # Formula: ((id<<4)-id)<<3 = id*120 = id*0x78; then +4 and ldr pointer.

    # normalized lookup: input IDs 1001..1030 -> 0..29, otherwise fallback slot 30; 8-byte records.
    check(u32(data, 0x0000665C) == 0xFC170000, "normalized ID bias drift")
    check(u32(data, 0x00006660) == 0x0818DD68, "normalized lookup table base drift")
    check(u16(data, 0x0000664A) == 0x291D, "normalized index <=29 gate drift")
    check(u16(data, 0x0000664E) == 0x211E, "normalized fallback index 30 drift")
    check(u16(data, 0x00006652) == 0x00C9, "normalized 8-byte stride drift")

    # entity subtext: same 0xAC entity DB, offset +0x28 + slot*20, first u32 text.
    check(thumb_bl_target(data, 0x0000580C) == 0x08005024, "entity-subtext state->id resolver drift")
    check(thumb_bl_target(data, 0x00005814) == 0x080045B0, "entity-subtext entity resolver drift")
    check(u16(data, 0x0000581E) == 0x3028, "entity-subtext +0x28 base drift")
    check(u16(data, 0x00005818) == 0x00A1 and u16(data, 0x0000581A) == 0x1909 and u16(data, 0x0000581C) == 0x0089, "entity-subtext 20-byte slot stride drift")

    # 24-byte ID records: 16 live keyed records, three text pointers at +0C/+10/+14.
    check(u32(data, 0x00005D74) == 0x081C86C8, "id24 DB base drift")
    check(u16(data, 0x00005D7C) == 0x3018, "id24 0x18 stride drift")
    id24_live = 0
    while data[0x001C86C8 + id24_live * 0x18] != 0:
        id24_live += 1
    check(id24_live == 16, f"id24 live-record count drift: {id24_live}")
    for index in range(id24_live):
        row = 0x001C86C8 + index * 0x18
        for field in (0x0C, 0x10, 0x14):
            value = u32(data, row + field)
            check(ROM_BASE <= value < ROM_BASE + len(data), f"id24 text field drift at 0x{row+field:08X}")

    # ID-command accessors use the 256x0x78 character DB and 3x0x1C command subrecords.
    check(u32(data, 0x00007AC0) == 0x081A476C, "ID-command name DB base drift")
    check(u32(data, 0x00007B08) == 0x081A476C, "ID-command effect DB base drift")

    # Fixed-record and sparse lookup helpers used directly by draw code.
    check(u32(data, 0x0001225C) == 0x081ABF6C, "fixed16 DB base drift")
    check(u32(data, 0x0001231C) == 0x081AFB5C, "fixed40 DB base drift")
    check(u32(data, 0x000123C0) == 0x081B4CEC, "sparse pointer table base drift")
    fixed16_leading = count_leading_pointer_records(data, 0x001ABF6C, 16)
    fixed40_leading = count_leading_pointer_records(data, 0x001AFB5C, 40)
    sparse_leading = count_leading_pointer_records(data, 0x001B4CEC, 4)
    check(fixed16_leading == 138, f"fixed16 leading count drift: {fixed16_leading}")
    check(fixed40_leading == 175, f"fixed40 leading count drift: {fixed40_leading}")
    check(sparse_leading == 23, f"sparse leading count drift: {sparse_leading}")

    # Search bridge shares the 64x0x20 search-record DB and a parallel ROM pointer table.
    check(u32(data, 0x0006B168) == 0x08D55888, "search-record DB base drift")
    check(u32(data, 0x0006B170) == 0x08FCE1A0, "search bridge parallel pointer table drift")
    check(u16(data, 0x0006B174) == 0x3320, "search-record 0x20 stride drift")
    check(u16(data, 0x0006B176) == 0x3120, "search-record pointer advance drift")
    check(u16(data, 0x0006B178) == 0x3204, "search bridge parallel table +4 drift")

    helper_rows = [
        {"helper": "0x080051EC", "draw_calls": 10, "owner": "entity_name_via_ram_state", "structural_family": "entity_name", "semantic_status": "already-reviewed owner family; exact mapping inherited from semantic layer"},
        {"helper": "0x08005474", "draw_calls": 3, "owner": "entity_record_plus4", "structural_family": "entity_name", "semantic_status": "already-reviewed owner family; exact mapping inherited from semantic layer"},
        {"helper": "0x08005804", "draw_calls": 1, "owner": "entity_record_plus28_slot20", "structural_family": "entity_subtext", "semantic_status": "owner structure closed; direct semantic noun not reasserted here"},
        {"helper": "0x080072D0", "draw_calls": 11, "owner": "character_db_primary_via_slot_map", "structural_family": "character_primary", "semantic_status": "character_name provenance high-confidence"},
        {"helper": "0x0800752C", "draw_calls": 2, "owner": "character_db_primary", "structural_family": "character_primary", "semantic_status": "character_name provenance high-confidence"},
        {"helper": "0x08006640", "draw_calls": 4, "owner": "normalized_1001_1030_table", "structural_family": "normalized_lookup", "semantic_status": "owner structure closed; semantic noun inherited only if independently reviewed"},
        {"helper": "0x08005EAC", "draw_calls": 1, "owner": "id24_record_plus0C", "structural_family": "id24_record", "semantic_status": "unresolved exact noun"},
        {"helper": "0x08005EDC", "draw_calls": 2, "owner": "id24_record_plus10_or14", "structural_family": "id24_record", "semantic_status": "unresolved exact noun"},
        {"helper": "0x08007974", "draw_calls": 2, "owner": "id_command_field_A", "structural_family": "id_command", "semantic_status": "reviewed ID-command name path"},
        {"helper": "0x08007AA0", "draw_calls": 1, "owner": "id_command_field_A", "structural_family": "id_command", "semantic_status": "reviewed ID-command name path"},
        {"helper": "0x08007AE8", "draw_calls": 1, "owner": "id_command_field_B", "structural_family": "id_command", "semantic_status": "reviewed ID-command effect-summary path"},
        {"helper": "0x08012250", "draw_calls": 1, "owner": "fixed16_primary", "structural_family": "fixed_record_text", "semantic_status": "unresolved exact noun"},
        {"helper": "0x08012308", "draw_calls": 1, "owner": "fixed40_primary", "structural_family": "fixed_record_text", "semantic_status": "unresolved exact noun"},
        {"helper": "0x080123B0", "draw_calls": 2, "owner": "sparse_pointer_run_23", "structural_family": "sparse_lookup", "semantic_status": "unresolved exact noun"},
        {"helper": "0x0806B148", "draw_calls": 2, "owner": "search_record_parallel_pointer_bridge", "structural_family": "search_record", "semantic_status": "unresolved exact noun"},
    ]

    unresolved_semantic_draws = sum(row["draw_calls"] for row in helper_rows if row["semantic_status"] == "unresolved exact noun")

    report = {
        "schema_version": 1,
        "rom_sha256": digest,
        "forward_r0_draw_calls": 44,
        "helper_groups": helper_rows,
        "owner_facts": {
            "entity_id_map": "0x081A4298",
            "entity_db": {"base": "0x0818E2E4", "stride": 172},
            "character_db": {"base": "0x081A476C", "stride": 120, "records": 256},
            "normalized_lookup": {"base": "0x0818DD68", "record_stride": 8, "normal_indices": "0..29", "fallback_index": 30},
            "id24_record": {"base": "0x081C86C8", "stride": 24, "live_records": id24_live, "text_fields": [12, 16, 20], "text_fields_total": id24_live * 3},
            "fixed16": {"base": "0x081ABF6C", "stride": 16, "leading_primary_text_records": fixed16_leading},
            "fixed40": {"base": "0x081AFB5C", "stride": 40, "leading_primary_text_records": fixed40_leading},
            "sparse_pointer_run": {"base": "0x081B4CEC", "leading_pointer_entries": sparse_leading},
            "search_record_db": {"base": "0x08D55888", "stride": 32, "parallel_pointer_table": "0x08FCE1A0"},
        },
        "semantic_followup": {
            "draw_calls_whose_exact_noun_remains_unresolved_in_this_analyzer": unresolved_semantic_draws,
            "note": "This is a draw-call count, not a unique translation-record count. Target identity must be deduplicated before changing semantic corpus totals.",
        },
    }

    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
