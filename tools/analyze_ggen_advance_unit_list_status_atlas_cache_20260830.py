#!/usr/bin/env python3
"""Prove that the unit-list right pane uses the E0518 status atlas and can show stale savestate VRAM.

Runtime history:
- the C439 direct fixed-resource patch changed the left list `持` to `지`;
- the right pane still showed Japanese `持` together with Japanese `運動/限界/移動`;
- however the ROM candidate already contains Korean `운동/한계/이동` in its active E0518 atlas and Korean `지` in resource[12].

This analyzer closes the contradiction by separating screen setup from row redraw:
- setup loads E0518 table[0] once into BG character VRAM through 0x0800261C;
- row redraw 0x0801E8D4 only blits E0518 resource tilemaps and does not reload the atlas.

Therefore a savestate captured inside this screen can restore old Japanese VRAM even
when the newly selected ROM contains Korean E0518 graphics.  Re-entering the screen
(or loading from SRAM/normal save before this screen is initialized) is required to
measure atlas changes correctly.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB

THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import build_ggen_advance_status_ui_tile_overlay_poc as status  # noqa: E402
from analyze_ggen_advance_fixed_word_semantics_20260830 import parse_map, u32  # noqa: E402

JP_ROM = ROOT / "SD Gundam GGeneration Advance (Japan).gba"
MAIN_ROM = ROOT / "SD Gundam GGeneration Advance (Korean).gba"
GOOD_LIST_CANDIDATE = ROOT / "outputs" / "20260830_ggen_advance_status_badges" / "ggen_advance_status_badges_hold_fixed_list_followup_candidate_20260830.gba"
FALSE_C491_CANDIDATE = ROOT / "outputs" / "20260830_ggen_advance_status_badges" / "ggen_advance_status_badges_hold_fixed_list_detail_followup_candidate_20260830.gba"
OUT = ROOT / "analysis" / "ggen_advance_unit_list_status_atlas_cache_20260830.json"

EXPECTED_JP_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"
EXPECTED_MAIN_SHA256 = "f033b480bb36aabed3533bdea6dc0ff6da7884ea4ff1e9372cf662edb3295fd6"
EXPECTED_GOOD_SHA256 = "04bf4f64b3f0512f86152029680fb58cbebb93c64943bf3a09aaff40ec578d80"
EXPECTED_FALSE_SHA256 = "1a416cd86af1492f8b5a6a21f6536392bd156189c0a667c9933e619375db41a0"

STATUS_TABLE = 0x000E0518
ACTIVE_STATUS_POINTER = 0x09240000
SETUP_LITERAL = 0x0001E334
SETUP_CODE_START = 0x0001E2D6
SETUP_CODE_END = 0x0001E2E2
ROW_RENDERER_START = 0x0001E8D4
ROW_RENDERER_END = 0x0001EBE2
STATUS_UPLOAD_HELPER = 0x0800261C
TILEMAP_BLIT_HELPER = 0x0800269C

RESOURCE_UNIT_BASE = 35
RESOURCE_HOLD = 12

MOTION_TILES = [0x146, 0x147, 0x148, 0x149, 0x14E, 0x14F, 0x150, 0x151]
LIMIT_TILES = [0x156, 0x157, 0x158, 0x159, 0x15D, 0x15E, 0x15F, 0x160]
MOVE_TILES = [0x15A, 0x15B, 0x15C, 0x149, 0x161, 0x162, 0x150, 0x151]
HOLD_TILES = [0x09B, 0x09C]

EXPECTED_JP_HASHES = {
    "motion": "bd901c32f0f0067fe68ad44fcf584f1ef37450dcb73d9b2e7c3562da9e1ec35f",
    "limit": "e90ce087f7c75ae49a76f7bb1361fb821b6909933f71666112612ddbdb515d51",
    "move": "756d3a0c0e15dc42b34c3f49c4e90c6d2b0a23f12af60e47c294c79b6b0f1cdb",
    "hold": "de16d0f6dc14402345ade48056bd9e2ed5768a8dd4c39d802447750cb3acb3c1",
}
EXPECTED_MAIN_KO_HASHES = {
    "motion": "e0625d83b4106969291c5231511031aa450d533a4c8febb35ce035824972e394",
    "limit": "4913fb94e974e6ab8306a5d07d4a6c48a3609843f8e36f03c71ec4315d609994",
    "move": "a7689930ca8f703e61f369e8ca304bdab1ece56e90822e56ae552bc80e7550f4",
}
EXPECTED_GOOD_HOLD_KO_HASH = "c4e2d4bcc1dd447817fe43de71272c2174eaf96bc6f30aab8028f2f7040d0211"


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def decode_active_atlas(data: bytes) -> tuple[int, bytes]:
    ptr = struct.unpack_from("<I", data, STATUS_TABLE)[0]
    gate(0x08000000 <= ptr < 0x0A000000, f"invalid status pointer 0x{ptr:08X}")
    off = ptr - 0x08000000
    header = struct.unpack_from("<I", data, off)[0]
    gate(header & 0x80000000, f"status atlas is not compressed at 0x{off:08X}")
    body_len = header & 0xFFFF
    atlas = status.lzss_decompress(data[off + 4 : off + 4 + body_len])
    gate(len(atlas) == status.ATLAS_EXPECTED_DECODED, f"status decoded size drift: {len(atlas)}")
    return ptr, atlas


def block_hash(atlas: bytes, ids: list[int]) -> str:
    return sha256(b"".join(atlas[t * 32 : (t + 1) * 32] for t in ids))


def thumb_calls(data: bytes, start: int, end: int) -> list[int]:
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    calls: list[int] = []
    for insn in md.disasm(data[start:end], 0x08000000 + start):
        if insn.mnemonic != "bl" or not insn.op_str.startswith("#"):
            continue
        try:
            calls.append(int(insn.op_str[1:], 16))
        except ValueError:
            pass
    return calls


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    jp = JP_ROM.read_bytes()
    main = MAIN_ROM.read_bytes()
    good = GOOD_LIST_CANDIDATE.read_bytes()
    false = FALSE_C491_CANDIDATE.read_bytes()
    gate(sha256(jp) == EXPECTED_JP_SHA256, "Japanese ROM hash drift")
    gate(sha256(main) == EXPECTED_MAIN_SHA256, "main TIP hash drift")
    gate(sha256(good) == EXPECTED_GOOD_SHA256, "good C439 candidate hash drift")
    gate(sha256(false) == EXPECTED_FALSE_SHA256, "C491 diagnostic candidate hash drift")

    jp_ptr, jp_atlas = decode_active_atlas(jp)
    main_ptr, main_atlas = decode_active_atlas(main)
    good_ptr, good_atlas = decode_active_atlas(good)
    false_ptr, false_atlas = decode_active_atlas(false)

    gate(jp_ptr == 0x080DC848, f"clean JP status pointer drift: 0x{jp_ptr:08X}")
    for name, ptr in (("main", main_ptr), ("good", good_ptr), ("false", false_ptr)):
        gate(ptr == ACTIVE_STATUS_POINTER, f"{name} status pointer drift: 0x{ptr:08X}")

    jp_hashes = {
        "motion": block_hash(jp_atlas, MOTION_TILES),
        "limit": block_hash(jp_atlas, LIMIT_TILES),
        "move": block_hash(jp_atlas, MOVE_TILES),
        "hold": block_hash(jp_atlas, HOLD_TILES),
    }
    gate(jp_hashes == EXPECTED_JP_HASHES, f"Japanese status tile hashes drift: {jp_hashes}")

    main_hashes = {
        "motion": block_hash(main_atlas, MOTION_TILES),
        "limit": block_hash(main_atlas, LIMIT_TILES),
        "move": block_hash(main_atlas, MOVE_TILES),
        "hold": block_hash(main_atlas, HOLD_TILES),
    }
    for name, expected in EXPECTED_MAIN_KO_HASHES.items():
        gate(main_hashes[name] == expected, f"main Korean {name} tile hash drift: {main_hashes[name]}")
        gate(main_hashes[name] != jp_hashes[name], f"main {name} unexpectedly matches Japanese")
    gate(main_hashes["hold"] == jp_hashes["hold"], "main TIP should still have Japanese resource[12] before hold follow-up")

    good_hashes = {
        "motion": block_hash(good_atlas, MOTION_TILES),
        "limit": block_hash(good_atlas, LIMIT_TILES),
        "move": block_hash(good_atlas, MOVE_TILES),
        "hold": block_hash(good_atlas, HOLD_TILES),
    }
    for name, expected in EXPECTED_MAIN_KO_HASHES.items():
        gate(good_hashes[name] == expected, f"good candidate lost Korean {name}: {good_hashes[name]}")
    gate(good_hashes["hold"] == EXPECTED_GOOD_HOLD_KO_HASH, f"good candidate hold hash drift: {good_hashes['hold']}")
    gate(good_hashes["hold"] != jp_hashes["hold"], "good candidate resource[12] still Japanese")

    # The false C491 experiment changes only unrelated fixed-resource references;
    # it must leave the E0518 atlas identical to the good C439 parent.
    gate(false_atlas == good_atlas, "C491 experiment unexpectedly changed active E0518 atlas")

    # Unit base map proves the neighboring Japanese labels observed at runtime
    # are the exact same logical tiles whose ROM payload is already Korean.
    base_map = parse_map(good, u32(good, STATUS_TABLE + RESOURCE_UNIT_BASE * 4))
    gate(base_map is not None and (base_map["width"], base_map["height"]) == (32, 20), "unit base map drift")
    w = int(base_map["width"])
    expected_positions = {
        (13, 7): 0x146, (14, 7): 0x147, (15, 7): 0x148, (16, 7): 0x149,
        (13, 8): 0x14E, (14, 8): 0x14F, (15, 8): 0x150, (16, 8): 0x151,
        (13, 9): 0x156, (14, 9): 0x157, (15, 9): 0x158, (16, 9): 0x159,
        (19, 9): 0x15A, (20, 9): 0x15B, (21, 9): 0x15C, (22, 9): 0x149,
    }
    for (x, y), tile in expected_positions.items():
        actual = int(base_map["cells"][y * w + x]) & 0x03FF
        gate(actual == tile, f"resource[35] tile drift at {x},{y}: 0x{actual:03X}")

    hold_map = parse_map(good, u32(good, STATUS_TABLE + RESOURCE_HOLD * 4))
    gate(hold_map is not None and (hold_map["width"], hold_map["height"]) == (1, 2), "resource[12] map drift")
    gate([(int(c) & 0x03FF) for c in hold_map["cells"]] == HOLD_TILES, "resource[12] tile IDs drift")

    # Setup path: ldr r0, [literal E0518]; ldr r0, [r0]; movs r1,#1;
    # bl 0x0800261C.  This loads the active atlas once into char VRAM.
    gate(struct.unpack_from("<I", jp, SETUP_LITERAL)[0] == 0x080E0518, "setup E0518 literal drift")
    setup_calls = thumb_calls(jp, SETUP_CODE_START, SETUP_CODE_END)
    gate(STATUS_UPLOAD_HELPER in setup_calls, f"setup no longer calls status upload helper: {setup_calls}")

    # Row renderer uses E0518 resource maps repeatedly but never reloads the
    # character atlas.  It therefore consumes whatever graphics are already in VRAM.
    row_calls = thumb_calls(jp, ROW_RENDERER_START, ROW_RENDERER_END)
    gate(TILEMAP_BLIT_HELPER in row_calls, "row renderer no longer blits status tilemaps")
    gate(STATUS_UPLOAD_HELPER not in row_calls, "row renderer unexpectedly reloads status atlas")
    gate(struct.unpack_from("<I", jp, 0x0001EBE8)[0] == 0x080E0518, "row renderer E0518 literal drift")

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_unit_list_status_atlas_cache_20260830",
        "result": "PASS",
        "runtime_observation": {
            "observed": "right pane still displayed Japanese 持 together with Japanese 運動/限界/移動 after ROM replacement, while left C439 fixed badge did update",
            "interpretation": "the observed right-pane graphics are stale/cached character VRAM, not the current ROM's active E0518 payload",
        },
        "rom_proof": {
            "main_tip": {"sha256": sha256(main), "active_status_pointer": f"0x{main_ptr:08X}", "tile_hashes": main_hashes},
            "good_c439_candidate": {"sha256": sha256(good), "active_status_pointer": f"0x{good_ptr:08X}", "tile_hashes": good_hashes},
            "japanese_reference": {"sha256": sha256(jp), "active_status_pointer": f"0x{jp_ptr:08X}", "tile_hashes": jp_hashes},
            "facts": [
                "main TIP already contains Korean 운동/한계/이동 graphics in active E0518",
                "04bf candidate additionally contains Korean 지 in E0518 resource[12]",
                "resource[35] still references the same 운동/한계/이동 tile IDs",
                "resource[12] still references logical tiles 0x09B/0x09C, whose active payload is Korean in 04bf",
            ],
        },
        "execution_path": {
            "screen_setup": {
                "code": "0x0801E2D6..0x0801E2E0",
                "table_literal": "0x0801E334 -> 0x080E0518",
                "operation": "load table[0], set r1=1, call 0x0800261C",
                "upload_helper": "0x0800261C",
                "effect": "decompress/copy active status atlas to BG character VRAM at screen setup",
            },
            "row_redraw": {
                "renderer": "0x0801E8D4",
                "table_literal": "0x0801EBE8 -> 0x080E0518",
                "tilemap_blit_helper": "0x0800269C",
                "status_upload_helper_called": False,
                "effect": "redraws resource tilemaps but reuses graphics already resident in VRAM",
            },
        },
        "false_hypothesis": {
            "candidate": str(FALSE_C491_CANDIDATE.relative_to(ROOT)),
            "sha256": sha256(false),
            "status": "superseded",
            "reason": "C491 fixed-resource redirection cannot affect the E0518 character graphics actually used by the unit-list right pane; the active E0518 atlas remained byte-exact to 04bf",
        },
        "testing_protocol": [
            "do not load a savestate captured while already inside the unit-list/status screen when validating E0518 graphic changes",
            "boot the candidate or load SRAM/normal save, then enter the unit-list screen fresh",
            "if a savestate is needed, use one from before this screen initializes, or leave the screen and re-enter it after loading the state so 0x0801E2D6 reloads E0518 into VRAM",
            "on a valid fresh entry, 운동/한계/이동 should already be Korean and the 04bf resource[12] badge should show 지; if all four remain Japanese after a fresh entry, then collect a new savestate from that fresh candidate for VRAM/source tracing",
        ],
        "recommended_parent": {
            "path": str(GOOD_LIST_CANDIDATE.relative_to(ROOT)),
            "sha256": sha256(good),
            "reason": "contains the verified left C439 지 patch and the correct E0518 지 payload without the unrelated C491 experiment",
        },
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "out": str(args.out),
        "recommended_parent": str(GOOD_LIST_CANDIDATE),
        "recommended_sha256": sha256(good),
        "false_c491_superseded": True,
        "screen_setup_upload": "0x0801E2D6 -> [0x080E0518][0] -> 0x0800261C",
        "row_renderer_reloads_atlas": False,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
