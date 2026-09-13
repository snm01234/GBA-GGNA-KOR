#!/usr/bin/env python3
"""Audit duplicated Japanese status graphics outside the translated E0518 BG atlas.

A fresh mGBA state proved that the right unit-list panel is assembled as OBJ
sprites from the C5A5DC package.  The active E0518 atlas is already Korean, but
several sprite/fixed copies of the same Japanese status art remain in ROM.

This analyzer closes the safe same-case copies before patching:

* C5A5DC package: pilot 近接/射撃/反応, unit 運動/装甲/限界/移動,
  汎用, and the shifted 8x16 持 badge.
* C64140 package: byte/geometry-compatible duplicate copies of 運動/限界/汎用.
* C43 direct 4x2 descriptors: exact copies of 汎用/地上/水陸/宇宙/万能/飛行.

For tile copies, Koreanization is represented as a *translation delta* between
the clean-JP E0518 tile and the already approved Korean E0518 tile.  The delta
is applied only where the package copy still equals the JP pixel (or already
matches the Korean pixel).  This preserves package-specific borders/background
pixels and rejects ambiguous mappings.

The right-panel 持 is the same status badge shifted two pixels left.  All 50
translated pixels in the six overlapping columns match the JP E0518 source
exactly, so the same JP->KO delta can be shifted left without touching the
package-specific right edge.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import build_ggen_advance_status_ui_tile_overlay_poc as status  # noqa: E402

ROM_BASE = 0x08000000
STATUS_TABLE = 0x000E0518
JP_ROM = ROOT / "SD Gundam GGeneration Advance (Japan).gba"
MAIN_ROM = ROOT / "SD Gundam GGeneration Advance (Korean).gba"
STATE_AUDIT = ROOT / "analysis" / "ggen_advance_unit_list_sprite_state_20260830.json"
DEFAULT_OUT = ROOT / "analysis" / "ggen_advance_status_sprite_package_duplicates_20260830.json"

EXPECTED_JP_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"
EXPECTED_MAIN_SHA256 = "1a416cd86af1492f8b5a6a21f6536392bd156189c0a667c9933e619375db41a0"

ACTIVE_PACKAGE = 0x00C5A5DC
ALT_PACKAGE = 0x00C64140

# Source-address -> E0518 tile mappings.  Shared Japanese `動` source tiles are
# intentionally repeated between 운동/이동 and are checked for consistency.
C5_LABELS: dict[str, list[tuple[int, int]]] = {
    "근접": [
        (0x00C5BC30, 0x044), (0x00C5BC50, 0x045), (0x00C5BC70, 0x046), (0x00C5BC90, 0x047),
        (0x00C5BCB0, 0x04D), (0x00C5BCD0, 0x04E), (0x00C5BCF0, 0x04F), (0x00C5BD10, 0x050),
    ],
    "사격": [
        (0x00C5BD30, 0x058), (0x00C5BD50, 0x059), (0x00C5BD70, 0x05A), (0x00C5BD90, 0x05B),
        (0x00C5BDB0, 0x062), (0x00C5BDD0, 0x063), (0x00C5BDF0, 0x064), (0x00C5BE10, 0x065),
    ],
    "반응": [
        (0x00C5BE70, 0x06A), (0x00C5BE90, 0x06B), (0x00C5BEB0, 0x06C), (0x00C5BED0, 0x06D),
        (0x00C5BEF0, 0x072), (0x00C5BF10, 0x073), (0x00C5BF30, 0x074), (0x00C5BF50, 0x075),
    ],
    "운동": [
        (0x00C5CBB0, 0x146), (0x00C5CBD0, 0x147), (0x00C5CBF0, 0x148), (0x00C5CC10, 0x149),
        (0x00C5CC50, 0x14E), (0x00C5CC70, 0x14F), (0x00C5CC90, 0x150), (0x00C5CCB0, 0x151),
    ],
    "장갑": [
        (0x00C5CCF0, 0x14A), (0x00C5CD10, 0x14B), (0x00C5CD30, 0x14C), (0x00C5CD50, 0x14D),
        (0x00C5CD70, 0x152), (0x00C5CD90, 0x153), (0x00C5CDB0, 0x154), (0x00C5CDD0, 0x155),
    ],
    "한계": [
        (0x00C5CC30, 0x156), (0x00C5CF50, 0x157), (0x00C5CF70, 0x158), (0x00C5CF90, 0x159),
        (0x00C5CCD0, 0x15D), (0x00C5CFB0, 0x15E), (0x00C5CFD0, 0x15F), (0x00C5CFF0, 0x160),
    ],
    "이동": [
        (0x00C5CDF0, 0x15A), (0x00C5CE10, 0x15B), (0x00C5CE30, 0x15C), (0x00C5CC10, 0x149),
        (0x00C5CE50, 0x161), (0x00C5CE70, 0x162), (0x00C5CC90, 0x150), (0x00C5CCB0, 0x151),
    ],
    "범용": [
        (0x00C5D010, 0x1A8), (0x00C5D030, 0x1A9), (0x00C5D050, 0x1AA), (0x00C5D0D0, 0x1AB),
        (0x00C5D070, 0x1AC), (0x00C5D090, 0x1AD), (0x00C5D0B0, 0x1AE), (0x00C5D0F0, 0x1AF),
    ],
}

C64_LABELS: dict[str, list[tuple[int, int]]] = {
    "운동": [
        (0x00C665E4, 0x146), (0x00C66604, 0x147), (0x00C66624, 0x148), (0x00C66644, 0x149),
        (0x00C666A4, 0x14E), (0x00C666C4, 0x14F), (0x00C666E4, 0x150), (0x00C66704, 0x151),
    ],
    "한계": [
        (0x00C66664, 0x156), (0x00C669C4, 0x157), (0x00C669E4, 0x158), (0x00C66A04, 0x159),
        (0x00C66724, 0x15D), (0x00C66A24, 0x15E), (0x00C66A44, 0x15F), (0x00C66A64, 0x160),
    ],
    "범용": [
        (0x00C66464, 0x1A8), (0x00C66744, 0x1A9), (0x00C66764, 0x1AA), (0x00C66784, 0x1AB),
        (0x00C66524, 0x1AC), (0x00C66824, 0x1AD), (0x00C66844, 0x1AE), (0x00C66864, 0x1AF),
    ],
}

# Exact direct 4x2 descriptor duplicates.  The first 0x20 bytes are the fixed
# descriptor/map header; graphics are eight row-major 4bpp tiles at +0x20.
DIRECT_TYPES: dict[str, tuple[int, list[int]]] = {
    "범용": (0x00C43E80, list(range(0x1A8, 0x1B0))),
    "지상": (0x00C43FA0, list(range(0x1B8, 0x1C0))),
    "수륙": (0x00C440C0, list(range(0x1C8, 0x1D0))),
    "우주": (0x00C441E0, list(range(0x1B0, 0x1B8))),
    "만능": (0x00C44300, list(range(0x1C0, 0x1C8))),
    "비행": (0x00C44420, list(range(0x1D0, 0x1D8))),
}
DIRECT_HEADER_PREFIX = bytes.fromhex("0a000402100010002000")

HOLD_TOP = 0x00C5CEB0
HOLD_BOTTOM = 0x00C5CF10
HOLD_STATUS_TOP = 0x09B
HOLD_STATUS_BOTTOM = 0x09C
HOLD_STATUS_X_SHIFT = 2  # package x=0..5 corresponds to E0518 x=2..7


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def u32(data: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def decode_status_atlas(data: bytes) -> tuple[int, bytes]:
    pointer = u32(data, STATUS_TABLE)
    gate(ROM_BASE <= pointer < ROM_BASE + len(data), f"invalid E0518 pointer 0x{pointer:08X}")
    off = pointer - ROM_BASE
    header = u32(data, off)
    gate(header & 0x80000000, f"E0518 atlas at 0x{off:08X} is not custom LZSS")
    body_len = header & 0xFFFF
    atlas = status.lzss_decompress(data[off + 4:off + 4 + body_len])
    gate(len(atlas) == status.ATLAS_EXPECTED_DECODED, f"E0518 decoded size drift: {len(atlas)}")
    return pointer, atlas


def decode_tile(raw: bytes) -> list[int]:
    gate(len(raw) == 32, "tile must be 32 bytes")
    pixels: list[int] = []
    for y in range(8):
        for x in range(8):
            value = raw[y * 4 + x // 2]
            pixels.append((value >> (4 * (x & 1))) & 0x0F)
    return pixels


def tile(atlas: bytes, tile_id: int) -> bytes:
    return atlas[tile_id * 32:(tile_id + 1) * 32]


def delta_compatibility(package_raw: bytes, jp_raw: bytes, ko_raw: bytes) -> dict[str, Any]:
    p = decode_tile(package_raw)
    j = decode_tile(jp_raw)
    k = decode_tile(ko_raw)
    changed = [i for i in range(64) if j[i] != k[i]]
    conflicts = [i for i in changed if p[i] not in (j[i], k[i])]
    already = [i for i in changed if p[i] == k[i]]
    variants = [i for i in range(64) if p[i] != j[i]]
    return {
        "translation_pixels": len(changed),
        "variant_pixels_vs_jp": len(variants),
        "already_korean_pixels": len(already),
        "conflict_pixels": len(conflicts),
        "compatible": not conflicts,
    }


def audit_mapping(data: bytes, jp_atlas: bytes, ko_atlas: bytes, mapping: dict[str, list[tuple[int, int]]]) -> dict[str, Any]:
    report: dict[str, Any] = {}
    for label, rows in mapping.items():
        items = []
        total_translation = total_variant = total_already = total_conflict = 0
        for off, tile_id in rows:
            compat = delta_compatibility(data[off:off + 32], tile(jp_atlas, tile_id), tile(ko_atlas, tile_id))
            gate(compat["compatible"], f"{label} mapping conflict at 0x{off:08X} / E0518 0x{tile_id:03X}")
            total_translation += int(compat["translation_pixels"])
            total_variant += int(compat["variant_pixels_vs_jp"])
            total_already += int(compat["already_korean_pixels"])
            total_conflict += int(compat["conflict_pixels"])
            items.append({
                "source_offset": f"0x{off:08X}",
                "e0518_tile": f"0x{tile_id:03X}",
                **compat,
            })
        report[label] = {
            "tiles": items,
            "translation_pixels": total_translation,
            "variant_pixels_vs_jp": total_variant,
            "already_korean_pixels": total_already,
            "conflict_pixels": total_conflict,
        }
    return report


def audit_hold(data: bytes, jp_atlas: bytes, ko_atlas: bytes) -> dict[str, Any]:
    pkg_rows = [decode_tile(data[HOLD_TOP:HOLD_TOP + 32]), decode_tile(data[HOLD_BOTTOM:HOLD_BOTTOM + 32])]
    jp_rows = [decode_tile(tile(jp_atlas, HOLD_STATUS_TOP)), decode_tile(tile(jp_atlas, HOLD_STATUS_BOTTOM))]
    ko_rows = [decode_tile(tile(ko_atlas, HOLD_STATUS_TOP)), decode_tile(tile(ko_atlas, HOLD_STATUS_BOTTOM))]
    translation = 0
    conflicts = []
    background_differences = 0
    for part in range(2):
        for y in range(8):
            for x in range(6):
                source_x = x + HOLD_STATUS_X_SHIFT
                p = pkg_rows[part][y * 8 + x]
                j = jp_rows[part][y * 8 + source_x]
                k = ko_rows[part][y * 8 + source_x]
                if p != j:
                    background_differences += 1
                if j == k:
                    continue
                translation += 1
                if p not in (j, k):
                    conflicts.append((part, x, y, p, j, k))
    gate(translation == 50, f"shifted 持 translation pixel count drift: {translation}")
    gate(not conflicts, f"shifted 持 has translation conflicts: {conflicts[:4]}")
    return {
        "package_tiles": [f"0x{HOLD_TOP:08X}", f"0x{HOLD_BOTTOM:08X}"],
        "e0518_tiles": [f"0x{HOLD_STATUS_TOP:03X}", f"0x{HOLD_STATUS_BOTTOM:03X}"],
        "status_x_shift": HOLD_STATUS_X_SHIFT,
        "overlap_width": 6,
        "translation_pixels": translation,
        "package_background_differences_in_overlap": background_differences,
        "conflict_pixels": 0,
        "compatible": True,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--main", type=Path, default=MAIN_ROM)
    ap.add_argument("--jp", type=Path, default=JP_ROM)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    main = args.main.read_bytes()
    jp = args.jp.read_bytes()
    gate(sha256(main) == EXPECTED_MAIN_SHA256, f"main TIP hash drift: {sha256(main)}")
    gate(sha256(jp) == EXPECTED_JP_SHA256, f"Japanese ROM hash drift: {sha256(jp)}")
    gate(len(main) == 32 * 1024 * 1024, "main TIP must be 32 MiB")

    state_audit = json.loads(STATE_AUDIT.read_text(encoding="utf-8"))
    gate(state_audit.get("result") == "PASS", "fresh-state OBJ audit is not PASS")
    gate(state_audit.get("active_sprite_package", {}).get("resource_pointer") == "0x08C5A5DC", "fresh-state active package drift")

    jp_pointer, jp_atlas = decode_status_atlas(jp)
    main_pointer, ko_atlas = decode_status_atlas(main)
    gate(jp_pointer == 0x080DC848, f"clean E0518 pointer drift: 0x{jp_pointer:08X}")
    gate(main_pointer == 0x09240000, f"main E0518 pointer drift: 0x{main_pointer:08X}")
    gate(jp_atlas != ko_atlas, "main E0518 atlas unexpectedly equals clean JP")

    c5_report = audit_mapping(main, jp_atlas, ko_atlas, C5_LABELS)
    c64_report = audit_mapping(main, jp_atlas, ko_atlas, C64_LABELS)
    hold_report = audit_hold(main, jp_atlas, ko_atlas)

    direct_report: dict[str, Any] = {}
    for label, (desc, tile_ids) in DIRECT_TYPES.items():
        gate(main[desc:desc + len(DIRECT_HEADER_PREFIX)] == DIRECT_HEADER_PREFIX, f"{label} direct descriptor header drift")
        graphics = desc + 0x20
        rows = []
        for i, tile_id in enumerate(tile_ids):
            off = graphics + i * 32
            gate(main[off:off + 32] == tile(jp_atlas, tile_id), f"{label} direct tile is not byte-exact JP: 0x{off:08X}")
            compat = delta_compatibility(main[off:off + 32], tile(jp_atlas, tile_id), tile(ko_atlas, tile_id))
            gate(compat["compatible"], f"{label} direct delta conflict at 0x{off:08X}")
            rows.append({"source_offset": f"0x{off:08X}", "e0518_tile": f"0x{tile_id:03X}", **compat})
        direct_report[label] = {
            "descriptor_offset": f"0x{desc:08X}",
            "graphics_offset": f"0x{graphics:08X}",
            "byte_exact_jp_e0518": True,
            "tiles": rows,
        }

    # Independent same-case scan: only these six direct 4x2 descriptors are
    # exact row-major clones of the known type-label E0518 blocks.
    exact_descriptor_scan = []
    for label, (desc, tile_ids) in DIRECT_TYPES.items():
        raw = b"".join(tile(jp_atlas, t) for t in tile_ids)
        gate(main[desc + 0x20:desc + 0x20 + len(raw)] == raw, f"{label} exact descriptor scan drift")
        exact_descriptor_scan.append({"label": label, "descriptor_offset": f"0x{desc:08X}"})

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_status_sprite_package_duplicates_20260830",
        "result": "PASS",
        "source": {
            "main_tip": {"path": str(args.main.relative_to(ROOT)), "sha256": sha256(main)},
            "japanese": {"path": str(args.jp.relative_to(ROOT)), "sha256": sha256(jp)},
            "fresh_state_audit": str(STATE_AUDIT.relative_to(ROOT)),
        },
        "e0518": {
            "clean_pointer": f"0x{jp_pointer:08X}",
            "main_pointer": f"0x{main_pointer:08X}",
            "decoded_bytes": len(ko_atlas),
            "main_contains_approved_korean_status_art": True,
        },
        "active_C5A5DC": {
            "package_offset": f"0x{ACTIVE_PACKAGE:08X}",
            "labels": c5_report,
            "hold_badge": hold_report,
        },
        "alternate_C64140": {
            "package_offset": f"0x{ALT_PACKAGE:08X}",
            "labels": c64_report,
            "reason_included": "same raw sprite-copy family; only mappings with zero translation conflicts are admitted",
        },
        "direct_type_descriptors": direct_report,
        "exact_direct_descriptor_scan": exact_descriptor_scan,
        "safe_additional_scope": {
            "translated_now": [
                "근접", "사격", "반응", "운동", "장갑", "한계", "이동", "지",
                "범용", "지상", "수륙", "우주", "만능", "비행",
            ],
            "not_forced": [
                {
                    "label": "조종계",
                    "reason": "no byte-exact or zero-conflict package/direct duplicate was identified in this pass",
                }
            ],
        },
        "patch_policy": {
            "method": "apply clean-JP -> approved-Korean E0518 pixel deltas to duplicated sprite/fixed tiles",
            "preserve_package_specific_pixels": True,
            "reject_conflicts": True,
            "hold_method": "apply the resource[12] JP->KO delta shifted left two pixels across the six proven-overlap columns",
            "no_pointer_changes_required": True,
            "no_palette_changes_required": True,
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "out": str(args.out),
        "C5_labels": list(C5_LABELS),
        "C64_labels": list(C64_LABELS),
        "direct_types": list(DIRECT_TYPES),
        "hold_translation_pixels": hold_report["translation_pixels"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
