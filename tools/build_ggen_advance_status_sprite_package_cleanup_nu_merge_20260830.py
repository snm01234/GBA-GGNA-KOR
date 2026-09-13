#!/usr/bin/env python3
"""Merge the approved sprite-package Koreanization, left-residue cleanup, and Nu Gundam fix.

Parent main TIP at the time of this build:
  1a416cd86af1492f8b5a6a21f6536392bd156189c0a667c9933e619375db41a0

This builder starts from the measured sprite-package candidate (1144...),
clears only the eight visible stale pixels in the left-most column of the
right-panel `지` badge, then merges the previously audited context-proven
Nu Gundam correction (턴에이 건담 -> ν건담) by replaying its exact diff over
locations that are still byte-identical to the historical f033... base.

No other bytes are allowed to change.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

CURRENT_MAIN = ROOT / "SD Gundam GGeneration Advance (Korean).gba"
FULL_KO_CANDIDATE = ROOT / "outputs" / "20260830_ggen_advance_status_badges" / "ggen_advance_status_sprite_package_full_ko_candidate_20260830.gba"
HISTORICAL_F033 = ROOT / "SD Gundam GGeneration Advance (Korean)_allclear.gba"
NU_CANDIDATE = ROOT / "outputs" / "20260830_ggen_advance_nu_gundam_main_tip" / "ggen_advance_nu_gundam_main_tip_candidate_20260830.gba"
NU_MANIFEST = ROOT / "analysis" / "ggen_advance_nu_gundam_main_tip_20260830.json"

OUT_DIR = ROOT / "outputs" / "20260830_ggen_advance_status_badges"
DEFAULT_OUT = OUT_DIR / "ggen_advance_status_sprite_package_full_ko_hold_cleanup_nu_candidate_20260830.gba"
DEFAULT_MANIFEST = ROOT / "analysis" / "ggen_advance_status_sprite_package_full_ko_hold_cleanup_nu_20260830.json"

EXPECTED_CURRENT_MAIN = "1a416cd86af1492f8b5a6a21f6536392bd156189c0a667c9933e619375db41a0"
EXPECTED_FULL_KO = "1144cbc817eeb0aa1d33e63593ffd0c89db047bf9300982d655778a503817d2a"
EXPECTED_F033 = "f033b480bb36aabed3533bdea6dc0ff6da7884ea4ff1e9372cf662edb3295fd6"
EXPECTED_NU = "1b3c98c6f70dddf9989755bebf1c9897a6945856a45d0de2e3e7fe35b60605c5"

# Actual right-panel hold source identified from the fresh mGBA state.
HOLD_TOP = 0x00C5CEB0
HOLD_BOTTOM = 0x00C5CF10
HOLD_BYTES = 32

# Screenshot/live-tile measurement: the visible stale Japanese vertical stroke
# is exactly x=0, y=3..10 in the 8x16 composed badge.  The native panel column
# is the normal 6/7/8.../7/6 edge gradient; only the middle eight pixels need
# to be restored from glyph colors (4/A) to background index 8.
RESIDUE_X = 0
RESIDUE_YS = tuple(range(3, 11))
RESIDUE_BACKGROUND_INDEX = 8
EXPECTED_BEFORE_RESIDUE_VALUES = (4, 10, 4, 4, 10, 10, 4, 4)


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def decode_tile(raw: bytes | bytearray) -> list[int]:
    gate(len(raw) == 32, f"4bpp tile must be 32 bytes, got {len(raw)}")
    out: list[int] = []
    for byte in raw:
        out.append(byte & 0x0F)
        out.append((byte >> 4) & 0x0F)
    return out


def encode_tile(pixels: list[int]) -> bytes:
    gate(len(pixels) == 64, f"4bpp tile must have 64 pixels, got {len(pixels)}")
    raw = bytearray(32)
    for i in range(32):
        raw[i] = (pixels[i * 2] & 0x0F) | ((pixels[i * 2 + 1] & 0x0F) << 4)
    return bytes(raw)


def get_hold_canvas(data: bytes | bytearray) -> list[list[int]]:
    top = decode_tile(data[HOLD_TOP:HOLD_TOP + HOLD_BYTES])
    bottom = decode_tile(data[HOLD_BOTTOM:HOLD_BOTTOM + HOLD_BYTES])
    return [top[y * 8:(y + 1) * 8] for y in range(8)] + [bottom[y * 8:(y + 1) * 8] for y in range(8)]


def put_hold_canvas(data: bytearray, canvas: list[list[int]]) -> None:
    gate(len(canvas) == 16 and all(len(row) == 8 for row in canvas), "hold canvas must be 8x16")
    top = [value for row in canvas[:8] for value in row]
    bottom = [value for row in canvas[8:] for value in row]
    data[HOLD_TOP:HOLD_TOP + HOLD_BYTES] = encode_tile(top)
    data[HOLD_BOTTOM:HOLD_BOTTOM + HOLD_BYTES] = encode_tile(bottom)


def ranges_from_offsets(offsets: list[int]) -> list[tuple[int, int]]:
    if not offsets:
        return []
    result: list[tuple[int, int]] = []
    start = prev = offsets[0]
    for value in offsets[1:]:
        if value != prev + 1:
            result.append((start, prev + 1))
            start = value
        prev = value
    result.append((start, prev + 1))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()

    current_main = CURRENT_MAIN.read_bytes()
    source = FULL_KO_CANDIDATE.read_bytes()
    historical = HISTORICAL_F033.read_bytes()
    nu = NU_CANDIDATE.read_bytes()
    nu_manifest = json.loads(NU_MANIFEST.read_text(encoding="utf-8"))

    gate(len(current_main) == len(source) == len(historical) == len(nu) == 32 * 1024 * 1024, "ROM size drift")
    gate(sha256(current_main) == EXPECTED_CURRENT_MAIN, f"current main TIP hash drift: {sha256(current_main)}")
    gate(sha256(source) == EXPECTED_FULL_KO, f"full-KO candidate hash drift: {sha256(source)}")
    gate(sha256(historical) == EXPECTED_F033, f"historical f033 base hash drift: {sha256(historical)}")
    gate(sha256(nu) == EXPECTED_NU, f"Nu candidate hash drift: {sha256(nu)}")
    gate(nu_manifest.get("result") == "PASS", "Nu Gundam manifest is not PASS")

    # The measured full-KO candidate must be a pure child of the current main.
    full_diff = [i for i, (a, b) in enumerate(zip(current_main, source)) if a != b]
    gate(len(full_diff) == 2711, f"full-KO diff count drift: {len(full_diff)}")

    candidate = bytearray(source)

    # 1) Minimal left-residue cleanup.
    before_canvas = get_hold_canvas(candidate)
    before_values = tuple(before_canvas[y][RESIDUE_X] for y in RESIDUE_YS)
    gate(before_values == EXPECTED_BEFORE_RESIDUE_VALUES, f"hold residue pattern drift: {before_values}")
    for y in RESIDUE_YS:
        before_canvas[y][RESIDUE_X] = RESIDUE_BACKGROUND_INDEX
    put_hold_canvas(candidate, before_canvas)
    after_canvas = get_hold_canvas(candidate)
    gate(all(after_canvas[y][RESIDUE_X] == RESIDUE_BACKGROUND_INDEX for y in RESIDUE_YS), "hold residue cleanup did not stick")
    # Native top/bottom edge values remain untouched.
    gate([after_canvas[y][0] for y in (0, 1, 2, 11, 12, 13, 14, 15)] == [6, 7, 8, 8, 8, 8, 7, 6], "hold native edge geometry drift")
    cleanup_diff = [i for i, (a, b) in enumerate(zip(source, candidate)) if a != b]
    gate(len(cleanup_diff) == 8, f"expected exactly 8 residue-byte changes, got {len(cleanup_diff)}")
    gate(all(HOLD_TOP <= i < HOLD_TOP + HOLD_BYTES or HOLD_BOTTOM <= i < HOLD_BOTTOM + HOLD_BYTES for i in cleanup_diff), "hold cleanup escaped target tiles")

    # 2) Replay the already audited Nu Gundam correction.
    nu_diff = [i for i, (a, b) in enumerate(zip(historical, nu)) if a != b]
    gate(len(nu_diff) == 82, f"Nu diff count drift: {len(nu_diff)}")
    conflicts = [i for i in nu_diff if candidate[i] != historical[i]]
    gate(not conflicts, f"Nu patch conflicts with graphics candidate at {[hex(x) for x in conflicts[:16]]}")
    for i in nu_diff:
        candidate[i] = nu[i]

    # Verify the eight context-proven owner pointers and payloads against the
    # audited Nu candidate.  The protected true Turn A records stay untouched
    # because the exact Nu candidate diff is replayed with zero conflicts.
    nu_section = nu_manifest.get("nu_gundam_fix", {})
    owners = nu_section.get("owner_pointers", [])
    payloads = nu_section.get("records", [])
    gate(len(owners) == 8 and len(payloads) == 8, "Nu manifest target count drift")
    for item in owners:
        off = int(item["owner_file_offset"], 16)
        gate(candidate[off:off + 4] == nu[off:off + 4], f"Nu owner pointer mismatch at 0x{off:08X}")
    for item in payloads:
        off = int(item["payload_file_offset"], 16)
        payload = bytes.fromhex(str(item["payload_hex"]).replace(" ", ""))
        gate(candidate[off:off + len(payload)] == payload, f"Nu payload mismatch for {item['record_id']}")

    final = bytes(candidate)
    final_diff_vs_main = [i for i, (a, b) in enumerate(zip(current_main, final)) if a != b]
    new_vs_full = [i for i, (a, b) in enumerate(zip(source, final)) if a != b]
    expected_new = set(cleanup_diff) | set(nu_diff)
    gate(set(new_vs_full) == expected_new, "final changes versus full-KO source are not exactly cleanup + Nu")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(final)

    manifest: dict[str, Any] = {
        "schema_version": 1,
        "kind": "ggen_advance_status_sprite_package_full_ko_hold_cleanup_nu_20260830",
        "result": "PASS",
        "source": {
            "current_main_tip": str(CURRENT_MAIN.relative_to(ROOT)).replace("\\", "/"),
            "current_main_tip_sha256": sha256(current_main),
            "measured_full_ko_candidate": str(FULL_KO_CANDIDATE.relative_to(ROOT)).replace("\\", "/"),
            "measured_full_ko_sha256": sha256(source),
            "historical_nu_base_sha256": sha256(historical),
            "nu_candidate_sha256": sha256(nu),
            "nu_manifest": str(NU_MANIFEST.relative_to(ROOT)).replace("\\", "/"),
        },
        "output": {
            "path": str(args.out.relative_to(ROOT)).replace("\\", "/"),
            "size": len(final),
            "sha256": sha256(final),
        },
        "hold_cleanup": {
            "target": "right-panel C5A5DC `지` badge",
            "tile_offsets": [f"0x{HOLD_TOP:08X}", f"0x{HOLD_BOTTOM:08X}"],
            "cleared_column": RESIDUE_X,
            "cleared_rows": list(RESIDUE_YS),
            "before_values": list(EXPECTED_BEFORE_RESIDUE_VALUES),
            "after_value": RESIDUE_BACKGROUND_INDEX,
            "changed_bytes": len(cleanup_diff),
            "policy": "remove only the measured stale Japanese left vertical stroke; preserve Korean body and native edge geometry",
        },
        "nu_gundam_fix": {
            "mapping": "context-proven Nu Gundam rows: 턴에이 건담 -> ν건담",
            "records": len(payloads),
            "owners": len(owners),
            "replayed_diff_bytes": len(nu_diff),
            "merge_conflicts": 0,
            "protected_true_turn_a_records_preserved_by_audited_source_patch": True,
        },
        "verification": {
            "result": "PASS",
            "full_ko_parent_hash_verified": True,
            "hold_cleanup_exact_eight_byte_scope": True,
            "hold_korean_body_preserved_except_left_residue_column": True,
            "nu_patch_exact_diff_replayed": True,
            "nu_merge_conflicts": 0,
            "nu_owner_and_payload_verification": True,
            "palette_modified": False,
            "resource_pointer_modified_by_hold_cleanup": False,
            "changed_bytes_vs_current_main_tip": len(final_diff_vs_main),
            "changed_bytes_vs_measured_full_ko_candidate": len(new_vs_full),
            "new_change_ranges_vs_full_ko": [[f"0x{a:08X}", f"0x{b:08X}"] for a, b in ranges_from_offsets(new_vs_full)],
        },
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "result": "PASS",
        "out": str(args.out),
        "sha256": sha256(final),
        "manifest": str(args.manifest),
        "hold_cleanup_changed_bytes": len(cleanup_diff),
        "nu_diff_bytes": len(nu_diff),
        "changed_bytes_vs_current_main_tip": len(final_diff_vs_main),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
