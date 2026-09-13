#!/usr/bin/env python3
"""Rebind the fresh real-run ss3 save-progress popup to its actual runtime owner.

The previous follow-up redirected 0x0801212C, but a fresh state captured after
booting from SAV still shows the Japanese save-progress warning.  This analyzer
uses the live sprite object and OBJ VRAM to distinguish the two candidate
consumers and proves the screen is owned by the 0x08073818 path/literal
0x0807385C instead.
"""
from __future__ import annotations

import hashlib
import json
import struct
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_settings_suspend_ui as sprite
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
from ggen_advance_project_paths import ADVANCE_ROOT

ROM_BASE = 0x08000000
CANDIDATE = ADVANCE_ROOT / "outputs" / "20260831_ggen_advance_load_summary_ui" / "ggen_advance_load_summary_ui_ko_save_progress_followup_candidate_20260831.gba"
CANDIDATE_SHA256 = "a88b7bd56662381f0f1bd4295dfccdee9a3f81dbb12396bfa705155937bf7a36"
STATE3 = ADVANCE_ROOT / "outputs" / "20260831_ggen_advance_load_summary_ui" / "ggen_advance_load_summary_ui_ko_save_progress_followup_candidate_20260831.ss3"
OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_save_progress_runtime_owner_followup_20260831.json"

SHARED_RESOURCE = 0x0928C000
KOREAN_RESOURCE = 0x09298000
WRONG_LITERAL = 0x0001212C
ACTUAL_LITERAL = 0x0007385C
SPRITE_SLOT_ADDRESS = 0x03002010
ANIMATION = 10


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def u16(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def explicit_animation_match(rom: bytes, resource: int, obj_vram: bytes) -> tuple[int, int]:
    off = resource - ROM_BASE
    graphics_rel = u32(rom, off + 0x08)
    palette_rel = u32(rom, off + 0x0C)
    graphics = rom[off + graphics_rel : off + palette_rel]
    _gr, records = sprite.animation_records(rom, resource)
    _record_start, record = records[ANIMATION]
    parsed = sprite.parse_animation_oam(record)
    gate(parsed["object_count"] == 12, f"animation10 object count drift at 0x{resource:08X}")
    source_table = int(parsed["entries_end"])
    gate(len(record) - source_table == 244, f"animation10 explicit-table span drift at 0x{resource:08X}")
    source_ids = list(struct.unpack_from("<122H", record, source_table))
    exact = 0
    for destination, source_id in enumerate(source_ids):
        expected = graphics[source_id * 32 : (source_id + 1) * 32]
        actual = obj_vram[destination * 32 : (destination + 1) * 32]
        exact += expected == actual
    return exact, len(source_ids)


def main() -> int:
    gate(CANDIDATE.is_file(), f"missing candidate: {CANDIDATE}")
    gate(STATE3.is_file(), f"missing fresh state3: {STATE3}")
    rom = CANDIDATE.read_bytes()
    gate(sha256(rom) == CANDIDATE_SHA256, f"candidate hash drift: {sha256(rom)}")

    state, chunks = statefmt.parse_png_state(STATE3)
    oam = state[statefmt.STATE_OAM : statefmt.STATE_VRAM]
    vram = state[statefmt.STATE_VRAM : statefmt.STATE_IWRAM]
    obj_vram = bytes(vram[statefmt.OBJ_VRAM :])
    iwram = state[statefmt.STATE_IWRAM :]

    visible = []
    for index in range(128):
        row = statefmt.parse_oam_entry(oam, index)
        if 0 <= int(row["x"]) < 240 and 0 <= int(row["y"]) < 160:
            visible.append(row)
    gate(len(visible) == 12, f"fresh save-progress OAM count drift: {len(visible)}")
    gate([(int(x["x"]), int(x["y"]), int(x["tile"])) for x in visible[:3]] == [(28, 64, 0), (28, 96, 16), (60, 64, 24)], "fresh save-progress OAM geometry drift")

    slot_off = SPRITE_SLOT_ADDRESS - 0x03000000
    slot = iwram[slot_off : slot_off + 40]
    gate(len(slot) == 40, "sprite slot truncated")
    runtime_resource = u32(slot, 0)
    field_11 = slot[0x11]
    x = u16(slot, 0x0A)
    y = u16(slot, 0x0C)
    current_frame = u32(slot, 0x20)
    gate(runtime_resource == SHARED_RESOURCE, f"fresh runtime resource was not shared clone: 0x{runtime_resource:08X}")
    gate((field_11, x, y) == (10, 120, 88), f"fresh runtime animation/anchor drift: {(field_11, x, y)}")
    gate(SHARED_RESOURCE <= current_frame < SHARED_RESOURCE + 0x0E04, f"fresh current-frame pointer not inside shared resource: 0x{current_frame:08X}")

    # The 22.110 ROM redirected the earlier 0x080120D6 path, but left the
    # actual save-data screen consumer at 0x08073818 on the shared resource.
    gate(u32(rom, WRONG_LITERAL) == KOREAN_RESOURCE, "earlier dedicated literal drift")
    gate(u32(rom, ACTUAL_LITERAL) == SHARED_RESOURCE, "actual runtime literal no longer points to shared resource")

    # Static signature of the actual path:
    #   08073818 ldr r0,[pc,#0x40] -> literal 0807385C
    #   ...
    #   0807387E movs r0,#10
    #   08073880 strb r0,[r4,#0x11]
    #   08073892 movs r0,#0x58 ; y=88
    #   08073898 movs r1,#0x78 ; x=120 passed to position helper
    gate(u16(rom, 0x00073818) == 0x4810, "0x08073818 resource LDR opcode drift")
    gate(u16(rom, 0x0007387E) == 0x200A and u16(rom, 0x00073880) == 0x7460, "0x0807387E animation10 setter drift")
    gate(u16(rom, 0x00073892) == 0x2058 and u16(rom, 0x00073898) == 0x2178, "0x080738xx save-progress anchor setter drift")

    shared_match = explicit_animation_match(rom, SHARED_RESOURCE, obj_vram)
    korean_match = explicit_animation_match(rom, KOREAN_RESOURCE, obj_vram)
    gate(shared_match == (122, 122), f"fresh OBJ VRAM does not match shared animation10: {shared_match}")
    gate(korean_match[0] < korean_match[1], "fresh OBJ VRAM unexpectedly matches Korean animation10")

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_save_progress_runtime_owner_followup_20260831",
        "result": "PASS",
        "candidate": {
            "path": str(CANDIDATE.relative_to(ADVANCE_ROOT)).replace("\\", "/"),
            "sha256": sha256(rom),
        },
        "fresh_state3": {
            "path": str(STATE3.relative_to(ADVANCE_ROOT)).replace("\\", "/"),
            "sha256": sha256(STATE3.read_bytes()),
            "chunks": [row["kind"] for row in chunks],
            "visible_oam_count": len(visible),
        },
        "runtime_sprite": {
            "slot_address": f"0x{SPRITE_SLOT_ADDRESS:08X}",
            "resource_pointer": f"0x{runtime_resource:08X}",
            "animation_field_11": field_11,
            "anchor_xy": [x, y],
            "current_frame_pointer": f"0x{current_frame:08X}",
        },
        "ownership_correction": {
            "previously_patched_literal_file_offset": f"0x{WRONG_LITERAL:08X}",
            "previously_patched_literal_value": f"0x{u32(rom, WRONG_LITERAL):08X}",
            "actual_consumer_instruction": "0x08073818",
            "actual_consumer_literal_file_offset": f"0x{ACTUAL_LITERAL:08X}",
            "actual_consumer_literal_value": f"0x{u32(rom, ACTUAL_LITERAL):08X}",
            "actual_path_sets_animation10_at": "0x0807387E/0x08073880",
            "actual_path_sets_anchor": "y=88 at 0x08073892, x=120 via 0x08073898 -> 0x08074374",
        },
        "obj_vram_match": {
            "shared_resource_animation10": {"exact": shared_match[0], "total": shared_match[1]},
            "korean_resource_animation10": {"exact": korean_match[0], "total": korean_match[1]},
        },
        "root_cause": "The real save-progress screen is created through the 0x08073818 consumer whose literal at file offset 0x0007385C still points to 0x0928C000. Redirecting only 0x0001212C therefore cannot affect this runtime path.",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "fresh_state3_sha256": report["fresh_state3"]["sha256"],
        "runtime_resource": report["runtime_sprite"]["resource_pointer"],
        "animation": field_11,
        "shared_match": shared_match,
        "korean_match": korean_match,
        "actual_literal": report["ownership_correction"]["actual_consumer_literal_file_offset"],
        "out": str(OUT),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
