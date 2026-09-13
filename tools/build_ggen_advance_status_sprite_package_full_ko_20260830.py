#!/usr/bin/env python3
"""Koreanize duplicated status graphics in the live OBJ/fixed sprite paths.

Parent: current canonical main TIP 1a416cd8...

The already translated E0518 atlas is the canonical Korean artwork source.  For
C5A5DC/C64140 sprite-package copies and C43 direct type descriptors, this
builder applies only pixels that differ between clean-JP E0518 and the approved
Korean E0518 tile.  Package-specific border/background pixels are preserved.

The right-panel 持 uses the same source badge shifted two pixels left; its
proven six-column overlap receives the same shifted JP->KO delta.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path
from typing import Any

from PIL import Image

THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_status_sprite_package_duplicates_20260830 as audit  # noqa: E402

INPUT_ROM = ROOT / "SD Gundam GGeneration Advance (Korean).gba"
JP_ROM = ROOT / "SD Gundam GGeneration Advance (Japan).gba"
OUT_DIR = ROOT / "outputs" / "20260830_ggen_advance_status_badges"
DEFAULT_OUT = OUT_DIR / "ggen_advance_status_sprite_package_full_ko_candidate_20260830.gba"
DEFAULT_MANIFEST = ROOT / "analysis" / "ggen_advance_status_sprite_package_full_ko_20260830.json"
DEFAULT_PREVIEW = OUT_DIR / "ggen_advance_status_sprite_package_full_ko_preview_20260830.png"
AUDIT_REPORT = ROOT / "analysis" / "ggen_advance_status_sprite_package_duplicates_20260830.json"

EXPECTED_INPUT_SHA256 = audit.EXPECTED_MAIN_SHA256
EXPECTED_JP_SHA256 = audit.EXPECTED_JP_SHA256
D54_TABLE = 0x000D54E4
D54_EXPECTED_POINTER = 0x080D45DC

# Previously measured/fixed graphics that this follow-up must not alter.
PROTECTED_RANGES = {
    "left_list_C439_B": (0x00C43968, 0x40),
    "left_list_C439_A": (0x00C439BC, 0x40),
    "C491_private_B": (0x01280000, 0x40),
    "C491_private_A": (0x01280040, 0x40),
}


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def decode_tile(raw: bytes) -> list[int]:
    gate(len(raw) == 32, "tile must be 32 bytes")
    result = []
    for y in range(8):
        for x in range(8):
            value = raw[y * 4 + x // 2]
            result.append((value >> (4 * (x & 1))) & 0x0F)
    return result


def encode_tile(pixels: list[int]) -> bytes:
    gate(len(pixels) == 64, "tile pixel count drift")
    out = bytearray(32)
    for y in range(8):
        for x in range(8):
            value = pixels[y * 8 + x] & 0x0F
            pos = y * 4 + x // 2
            if x & 1:
                out[pos] = (out[pos] & 0x0F) | (value << 4)
            else:
                out[pos] = (out[pos] & 0xF0) | value
    return bytes(out)


def atlas_tile(atlas: bytes, tile_id: int) -> bytes:
    return atlas[tile_id * 32:(tile_id + 1) * 32]


def apply_delta(package_raw: bytes, jp_raw: bytes, ko_raw: bytes) -> tuple[bytes, dict[str, int]]:
    p = decode_tile(package_raw)
    j = decode_tile(jp_raw)
    k = decode_tile(ko_raw)
    translated = already = changed = 0
    for i in range(64):
        if j[i] == k[i]:
            continue
        translated += 1
        if p[i] == k[i]:
            already += 1
            continue
        gate(p[i] == j[i], f"translation-delta conflict at pixel {i}: pkg={p[i]} jp={j[i]} ko={k[i]}")
        p[i] = k[i]
        changed += 1
    return encode_tile(p), {
        "translation_pixels": translated,
        "already_korean_pixels": already,
        "changed_pixels": changed,
    }


def collect_assignments() -> tuple[dict[int, int], dict[int, list[str]]]:
    assignments: dict[int, int] = {}
    owners: dict[int, list[str]] = {}
    for family, mapping in (("C5", audit.C5_LABELS), ("C64", audit.C64_LABELS)):
        for label, rows in mapping.items():
            for off, tile_id in rows:
                if off in assignments:
                    gate(assignments[off] == tile_id, f"conflicting shared source mapping at 0x{off:08X}")
                assignments[off] = tile_id
                owners.setdefault(off, []).append(f"{family}:{label}")
    for label, (desc, tile_ids) in audit.DIRECT_TYPES.items():
        for i, tile_id in enumerate(tile_ids):
            off = desc + 0x20 + i * 32
            gate(off not in assignments or assignments[off] == tile_id, f"direct mapping conflict at 0x{off:08X}")
            assignments[off] = tile_id
            owners.setdefault(off, []).append(f"C43:{label}")
    return assignments, owners


def apply_hold_shift(candidate: bytearray, source: bytes, jp_atlas: bytes, ko_atlas: bytes) -> dict[str, Any]:
    pkg_parts = [decode_tile(source[audit.HOLD_TOP:audit.HOLD_TOP + 32]), decode_tile(source[audit.HOLD_BOTTOM:audit.HOLD_BOTTOM + 32])]
    jp_parts = [decode_tile(atlas_tile(jp_atlas, audit.HOLD_STATUS_TOP)), decode_tile(atlas_tile(jp_atlas, audit.HOLD_STATUS_BOTTOM))]
    ko_parts = [decode_tile(atlas_tile(ko_atlas, audit.HOLD_STATUS_TOP)), decode_tile(atlas_tile(ko_atlas, audit.HOLD_STATUS_BOTTOM))]
    translated = already = changed = 0
    for part in range(2):
        for y in range(8):
            for x in range(6):
                sx = x + audit.HOLD_STATUS_X_SHIFT
                j = jp_parts[part][y * 8 + sx]
                k = ko_parts[part][y * 8 + sx]
                if j == k:
                    continue
                translated += 1
                pos = y * 8 + x
                p = pkg_parts[part][pos]
                if p == k:
                    already += 1
                    continue
                gate(p == j, f"shifted hold conflict part={part} x={x} y={y}: pkg={p} jp={j} ko={k}")
                pkg_parts[part][pos] = k
                changed += 1
    gate(translated == 50, f"hold translated pixel count drift: {translated}")
    candidate[audit.HOLD_TOP:audit.HOLD_TOP + 32] = encode_tile(pkg_parts[0])
    candidate[audit.HOLD_BOTTOM:audit.HOLD_BOTTOM + 32] = encode_tile(pkg_parts[1])
    return {
        "source_offsets": [f"0x{audit.HOLD_TOP:08X}", f"0x{audit.HOLD_BOTTOM:08X}"],
        "translation_pixels": translated,
        "already_korean_pixels": already,
        "changed_pixels": changed,
        "status_x_shift": audit.HOLD_STATUS_X_SHIFT,
    }


def canvas_from_mapping(data: bytes | bytearray, rows: list[tuple[int, int]]) -> list[list[int]]:
    gate(len(rows) == 8, "preview mapping must be 4x2")
    tiles = [decode_tile(bytes(data[off:off + 32])) for off, _ in rows]
    canvas = [[0] * 32 for _ in range(16)]
    for n, tile_pixels in enumerate(tiles):
        tx = n % 4
        ty = n // 4
        for y in range(8):
            for x in range(8):
                canvas[ty * 8 + y][tx * 8 + x] = tile_pixels[y * 8 + x]
    return canvas


def hold_canvas(data: bytes | bytearray) -> list[list[int]]:
    top = decode_tile(bytes(data[audit.HOLD_TOP:audit.HOLD_TOP + 32]))
    bottom = decode_tile(bytes(data[audit.HOLD_BOTTOM:audit.HOLD_BOTTOM + 32]))
    return [[top[y * 8 + x] for x in range(8)] for y in range(8)] + [[bottom[y * 8 + x] for x in range(8)] for y in range(8)]


def make_preview(before: bytes, after: bytes, out: Path) -> None:
    labels: list[tuple[str, list[list[int]], list[list[int]]]] = []
    for label in ("근접", "사격", "반응", "운동", "장갑", "한계", "이동", "범용"):
        labels.append((label, canvas_from_mapping(before, audit.C5_LABELS[label]), canvas_from_mapping(after, audit.C5_LABELS[label])))
    labels.append(("지", hold_canvas(before), hold_canvas(after)))
    for label in ("우주", "지상", "만능", "수륙", "비행"):
        desc, ids = audit.DIRECT_TYPES[label]
        rows = [(desc + 0x20 + i * 32, tile_id) for i, tile_id in enumerate(ids)]
        labels.append((label, canvas_from_mapping(before, rows), canvas_from_mapping(after, rows)))

    scale = 2
    pad = 8
    gap = 8
    cell_w = 32 * scale
    cell_h = 16 * scale
    cols = 4  # each label consumes before+after in two columns
    pair_rows = (len(labels) + 1) // 2
    image = Image.new("RGB", (pad * 2 + cols * cell_w + (cols - 1) * gap, pad * 2 + pair_rows * cell_h + (pair_rows - 1) * gap), (255, 255, 255))
    palette = {
        0: (255, 115, 213), 1: (32, 49, 0), 2: (115, 57, 0), 3: (213, 49, 24),
        4: (70, 45, 25), 5: (115, 57, 0), 6: (238, 41, 16), 7: (255, 82, 16),
        8: (255, 115, 24), 9: (255, 180, 41), 10: (255, 230, 65), 11: (255, 255, 139),
        12: (255, 255, 255), 13: (41, 180, 106), 14: (0, 230, 139), 15: (0, 255, 164),
    }
    for index, (_label, old, new) in enumerate(labels):
        pair_col = (index % 2) * 2
        row = index // 2
        for state_index, canvas in enumerate((old, new)):
            ox = pad + (pair_col + state_index) * (cell_w + gap)
            oy = pad + row * (cell_h + gap)
            width = len(canvas[0])
            # Center 8px hold badge in a 32px preview cell.
            xpad = (32 - width) // 2
            for y, line in enumerate(canvas):
                for x, value in enumerate(line):
                    color = palette.get(value, (140, 140, 140))
                    px = ox + (xpad + x) * scale
                    py = oy + y * scale
                    for yy in range(scale):
                        for xx in range(scale):
                            image.putpixel((px + xx, py + yy), color)
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", type=Path, default=INPUT_ROM)
    ap.add_argument("--jp", type=Path, default=JP_ROM)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--preview", type=Path, default=DEFAULT_PREVIEW)
    args = ap.parse_args()

    source = args.input.read_bytes()
    jp = args.jp.read_bytes()
    gate(sha256(source) == EXPECTED_INPUT_SHA256, f"input main TIP hash drift: {sha256(source)}")
    gate(sha256(jp) == EXPECTED_JP_SHA256, f"Japanese ROM hash drift: {sha256(jp)}")
    gate(len(source) == 32 * 1024 * 1024, "input ROM must be 32 MiB")

    report = json.loads(AUDIT_REPORT.read_text(encoding="utf-8"))
    gate(report.get("result") == "PASS", "same-case sprite duplicate audit is not PASS")

    jp_pointer, jp_atlas = audit.decode_status_atlas(jp)
    ko_pointer, ko_atlas = audit.decode_status_atlas(source)
    gate(jp_pointer == 0x080DC848, "clean E0518 pointer drift")
    gate(ko_pointer == 0x09240000, "main E0518 pointer drift")

    protected_before = {name: source[off:off + size] for name, (off, size) in PROTECTED_RANGES.items()}
    status_resource_off = ko_pointer - audit.ROM_BASE
    status_header = audit.u32(source, status_resource_off)
    status_body_len = status_header & 0xFFFF
    status_resource_before = source[status_resource_off:status_resource_off + 4 + status_body_len]
    d54_before = struct.unpack_from("<I", source, D54_TABLE)[0]
    gate(d54_before == D54_EXPECTED_POINTER, f"D54 pointer drift: 0x{d54_before:08X}")

    candidate = bytearray(source)
    assignments, owners = collect_assignments()
    tile_reports = []
    allowed_ranges: list[tuple[int, int]] = []

    for off in sorted(assignments):
        tile_id = assignments[off]
        new_raw, stats = apply_delta(source[off:off + 32], atlas_tile(jp_atlas, tile_id), atlas_tile(ko_atlas, tile_id))
        gate(new_raw != source[off:off + 32], f"mapped source produced no change at 0x{off:08X}")
        candidate[off:off + 32] = new_raw
        allowed_ranges.append((off, off + 32))
        tile_reports.append({
            "source_offset": f"0x{off:08X}",
            "e0518_tile": f"0x{tile_id:03X}",
            "owners": owners[off],
            **stats,
            "before_sha256": sha256(source[off:off + 32]),
            "after_sha256": sha256(new_raw),
        })

    hold_report = apply_hold_shift(candidate, source, jp_atlas, ko_atlas)
    allowed_ranges.extend([(audit.HOLD_TOP, audit.HOLD_TOP + 32), (audit.HOLD_BOTTOM, audit.HOLD_BOTTOM + 32)])

    # Every translated pixel must now match the approved Korean E0518 source.
    for off, tile_id in assignments.items():
        p = decode_tile(bytes(candidate[off:off + 32]))
        j = decode_tile(atlas_tile(jp_atlas, tile_id))
        k = decode_tile(atlas_tile(ko_atlas, tile_id))
        for i in range(64):
            if j[i] != k[i]:
                gate(p[i] == k[i], f"post-patch Korean delta mismatch at 0x{off:08X} pixel {i}")

    # Protected active/previously tested resources remain byte-exact.
    for name, (off, size) in PROTECTED_RANGES.items():
        gate(bytes(candidate[off:off + size]) == protected_before[name], f"protected resource changed: {name}")
    gate(bytes(candidate[status_resource_off:status_resource_off + 4 + status_body_len]) == status_resource_before, "active E0518 atlas changed")
    gate(struct.unpack_from("<I", candidate, D54_TABLE)[0] == D54_EXPECTED_POINTER, "D54 pointer changed")

    diff_offsets = [i for i, (a, b) in enumerate(zip(source, candidate)) if a != b]
    gate(diff_offsets, "candidate has no differences")
    unexpected = [i for i in diff_offsets if not any(lo <= i < hi for lo, hi in allowed_ranges)]
    gate(not unexpected, f"changes escaped approved sprite tiles: {[hex(x) for x in unexpected[:12]]}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(candidate)
    make_preview(source, bytes(candidate), args.preview)

    manifest = {
        "schema_version": 1,
        "kind": "ggen_advance_status_sprite_package_full_ko_20260830",
        "result": "PASS",
        "source": {"path": str(args.input.relative_to(ROOT)), "sha256": sha256(source)},
        "output": {"path": str(args.out.relative_to(ROOT)), "sha256": sha256(candidate), "size": len(candidate)},
        "audit": str(AUDIT_REPORT.relative_to(ROOT)),
        "implementation": {
            "method": "JP E0518 -> approved Korean E0518 per-pixel delta transplant",
            "C5_labels": list(audit.C5_LABELS),
            "C64_labels": list(audit.C64_LABELS),
            "direct_type_labels": list(audit.DIRECT_TYPES),
            "hold_badge": hold_report,
            "unique_source_tiles_patched": len(assignments) + 2,
            "mapped_tile_reports": tile_reports,
            "not_forced": ["조종계: no zero-conflict package/direct duplicate identified"],
        },
        "verification": {
            "result": "PASS",
            "input_hash_verified": True,
            "japanese_hash_verified": True,
            "fresh_state_sprite_audit_passed": True,
            "all_mapped_translation_pixels_equal_approved_korean_E0518": True,
            "package_specific_nontranslation_pixels_preserved": True,
            "active_E0518_resource_preserved_byte_exact": True,
            "left_list_C439_preserved": True,
            "C491_previous_clones_preserved": True,
            "D54_pointer_preserved": f"0x{D54_EXPECTED_POINTER:08X}",
            "palette_changes": False,
            "pointer_changes": False,
            "diffs_restricted_to_mapped_raw_sprite_tiles": True,
        },
        "changed_bytes_vs_main_tip": len(diff_offsets),
        "changed_byte_range": [f"0x{min(diff_offsets):08X}", f"0x{max(diff_offsets):08X}"],
        "preview": str(args.preview.relative_to(ROOT)),
        "runtime_checkpoints": [
            "unit-list right pane: 運動/装甲/限界/移動 -> 운동/장갑/한계/이동",
            "unit-list right pane ability prefix: 持 -> 지",
            "terrain/type badges: 汎用/地上/水陸/宇宙/万能/飛行 -> 범용/지상/수륙/우주/만능/비행",
            "pilot-status duplicate copies: 近接/射撃/反応 -> 근접/사격/반응 when that sprite-package view is entered",
            "left-list 지, 방패, 만, 간 and existing Korean E0518 labels must remain unchanged",
        ],
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "out": str(args.out),
        "sha256": sha256(candidate),
        "manifest": str(args.manifest),
        "preview": str(args.preview),
        "unique_source_tiles_patched": len(assignments) + 2,
        "changed_bytes_vs_main_tip": len(diff_offsets),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
