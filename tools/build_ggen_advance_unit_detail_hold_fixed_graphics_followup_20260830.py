#!/usr/bin/env python3
"""Patch the final right-side unit-detail `持` fixed graphic to `지`.

Runtime testing has already approved the parent candidate's E0518/detail and
left-list `지` fixes.  The remaining glyph immediately before ability text
(e.g. `I 필드`) is a separate compressed 1x1 fixed-resource pair at C491C0 /
C491F4 selected by predicate 0x08005D24 and drawn by 0x080638E4.

The original 0x1E-byte compressed payloads are too small for a conservative
literal-only 32-byte tile rebuild (0x24 bytes).  Therefore this builder creates
private descriptor clones in measured zero-filled expanded-ROM space and
redirects only the four literal references that select the two variants.  The
original descriptors and all sibling resources remain byte-exact.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path
from zipfile import ZipFile

from PIL import Image

THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_unit_detail_hold_fixed_graphics_20260830 as audit  # noqa: E402
import build_ggen_advance_hold_badge_full_followup_20260830 as hold  # noqa: E402
import test_ggen_advance_font_pair as fontpair  # noqa: E402
from ggen_advance_project_paths import FONT_ZIP  # noqa: E402

ROM_BASE = 0x08000000
INPUT_ROM = ROOT / "outputs" / "20260830_ggen_advance_status_badges" / "ggen_advance_status_badges_hold_fixed_list_followup_candidate_20260830.gba"
JP_ROM = ROOT / "SD Gundam GGeneration Advance (Japan).gba"
OUT_DIR = ROOT / "outputs" / "20260830_ggen_advance_status_badges"
DEFAULT_OUT = OUT_DIR / "ggen_advance_status_badges_hold_fixed_list_detail_followup_candidate_20260830.gba"
DEFAULT_MANIFEST = ROOT / "analysis" / "ggen_advance_status_badges_hold_fixed_list_detail_followup_20260830.json"
DEFAULT_PREVIEW = OUT_DIR / "ggen_advance_status_badges_hold_fixed_list_detail_followup_preview_20260830.png"

EXPECTED_INPUT_SHA256 = "04bf4f64b3f0512f86152029680fb58cbebb93c64943bf3a09aaff40ec578d80"
EXPECTED_JP_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"
D54_TABLE = 0x000D54E4
D54_ORIGINAL_POINTER = 0x080D45DC

FACE_INDEX = 15
CONTOUR_INDEX = 4
BOTTOM_DELIMITER_INDEX = 15
BACKGROUND_INDEX = {"variant_B": 11, "variant_A": 10}

# The parent candidate leaves 0x01280000+ zero-filled.  Give each cloned
# descriptor a 0x40-byte slot (new descriptor uses 0x14 + 0x24 = 0x38 bytes).
ALLOCATIONS = {
    "variant_B": 0x01280000,
    "variant_A": 0x01280040,
}
ALLOC_SLOT_BYTES = 0x40

PROTECTED_RANGES = {
    "original_detail_B": (0x00C491C0, 0x34),
    "original_detail_A": (0x00C491F4, 0x34),
    "direct_sibling_B": (0x00C43ACC, 0x34),
    "direct_sibling_A": (0x00C43B00, 0x34),
    "left_list_B": (0x00C43954, 0x54),
    "left_list_A": (0x00C439A8, 0x54),
}


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def encode_tile(pixels: list[list[int]]) -> bytes:
    gate(len(pixels) == 8 and all(len(row) == 8 for row in pixels), "8x8 tile shape mismatch")
    raw = bytearray(32)
    for y in range(8):
        for x in range(8):
            raw[y * 4 + (x >> 1)] |= (pixels[y][x] & 0xF) << (4 * (x & 1))
    return bytes(raw)


def literal_only_body(decoded: bytes) -> bytes:
    body = bytearray()
    for start in range(0, len(decoded), 8):
        chunk = decoded[start : start + 8]
        body.append((1 << len(chunk)) - 1)
        body.extend(chunk)
    return bytes(body)


def small_galmuri7_mask(font7: fontpair.BdfFont) -> list[list[bool]]:
    # Reuse exactly the accepted 6x7 Galmuri7 `지` face from the status/list
    # work.  The 8x16 badge stores it at y=4..10; the 1-tile detail form uses
    # those seven occupied rows directly at y=0..6 and reserves row 7 for the
    # native fixed-resource delimiter.
    status_mask = hold.render_badge_mask(font7)
    occupied = [row[:] for row in status_mask if any(row)]
    gate(len(occupied) == 7, f"Galmuri7 `지` occupied height drift: {len(occupied)}")
    gate(all(len(row) == 8 for row in occupied), "Galmuri7 `지` width drift")
    mask = occupied + [[False] * 8]
    gate(sum(v for row in mask for v in row) == sum(v for row in status_mask for v in row), "small mask lost ink")
    return mask


def paint_detail_tile(background_index: int, mask: list[list[bool]]) -> tuple[list[list[int]], int, int]:
    pixels = [[background_index] * 8 for _ in range(8)]
    pixels[7] = [BOTTOM_DELIMITER_INDEX] * 8
    contour = [[False] * 8 for _ in range(8)]

    for y in range(7):
        for x in range(8):
            if not mask[y][x]:
                continue
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    xx, yy = x + dx, y + dy
                    if 0 <= xx < 8 and 0 <= yy < 7 and not mask[yy][xx]:
                        contour[yy][xx] = True

    contour_count = 0
    ink_count = 0
    for y in range(7):
        for x in range(8):
            if contour[y][x]:
                pixels[y][x] = CONTOUR_INDEX
                contour_count += 1
    for y in range(7):
        for x in range(8):
            if mask[y][x]:
                pixels[y][x] = FACE_INDEX
                ink_count += 1

    gate(pixels[7] == [BOTTOM_DELIMITER_INDEX] * 8, "bottom delimiter was modified")
    return pixels, ink_count, contour_count


def build_descriptor(source_header: bytes, decoded_tile: bytes) -> bytes:
    gate(len(source_header) == 0x14, "source descriptor header size drift")
    header = bytearray(source_header)
    gate(header[0] & 0x10, "source descriptor is not compressed")
    gate((header[2], header[3]) == (1, 1), "source descriptor is not 1x1")
    gate(struct.unpack_from("<H", header, 4)[0] == 0x10, "source map offset drift")
    gate(struct.unpack_from("<H", header, 8)[0] == 0x14, "source graphic offset drift")
    body = literal_only_body(decoded_tile)
    gate(len(body) == 0x24, f"literal-only detail payload length drift: {len(body)}")
    struct.pack_into("<H", header, 10, len(body))
    descriptor = bytes(header) + body
    gate(len(descriptor) == 0x38, f"cloned descriptor size drift: {len(descriptor)}")
    return descriptor


def render_preview(before: dict[str, list[list[int]]], after: dict[str, list[list[int]]], out: Path) -> None:
    scale = 12
    pad = 8
    gap = 12
    cell = 8 * scale
    image = Image.new("RGB", (pad * 2 + cell * 2 + gap, pad * 2 + cell * 2 + gap), (255, 255, 255))
    palette = {
        4: (65, 45, 25),
        10: (250, 225, 70),
        11: (255, 250, 155),
        13: (225, 225, 175),
        14: (242, 242, 210),
        15: (255, 255, 255),
    }
    order = [
        before["variant_B"], after["variant_B"],
        before["variant_A"], after["variant_A"],
    ]
    for idx, pixels in enumerate(order):
        col = idx % 2
        row = idx // 2
        ox = pad + col * (cell + gap)
        oy = pad + row * (cell + gap)
        for y, scan in enumerate(pixels):
            for x, value in enumerate(scan):
                color = palette.get(value, (130, 130, 130))
                for yy in range(scale):
                    for xx in range(scale):
                        image.putpixel((ox + x * scale + xx, oy + y * scale + yy), color)
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
    gate(len(source) == 32 * 1024 * 1024, "input candidate must be 32 MiB")
    gate(sha256(source) == EXPECTED_INPUT_SHA256, f"parent candidate hash drift: {sha256(source)}")
    gate(sha256(jp) == EXPECTED_JP_SHA256, "Japanese ROM hash drift")
    gate(struct.unpack_from("<I", source, D54_TABLE)[0] == D54_ORIGINAL_POINTER, "rejected D54 redirect present")

    audit_report = json.loads((ROOT / "analysis" / "ggen_advance_unit_detail_hold_fixed_graphics_20260830.json").read_text(encoding="utf-8"))
    gate(audit_report.get("result") == "PASS", "unit-detail fixed-graphic audit not PASS")

    candidate = bytearray(source)
    protected_before = {name: source[off : off + size] for name, (off, size) in PROTECTED_RANGES.items()}
    before_pixels: dict[str, list[list[int]]] = {}
    after_pixels: dict[str, list[list[int]]] = {}
    reports = []

    with ZipFile(FONT_ZIP) as archive:
        font7 = fontpair.load_bdf(archive, "Galmuri7.bdf")
        korean_mask = small_galmuri7_mask(font7)

    # Prove the 8x8 pair has the same structural segmentation as the accepted
    # 8x16 fixed-list pair: rows 0..6 use A/B background, row 7 is fixed F,
    # and the Japanese glyph footprint is identical between variants.
    jp_b = audit.decode_descriptor(jp, audit.TARGETS["variant_B"]["descriptor"])["pixels"]
    jp_a = audit.decode_descriptor(jp, audit.TARGETS["variant_A"]["descriptor"])["pixels"]
    japanese_footprint = {(x, y) for y in range(7) for x in range(8) if jp_b[y][x] != BACKGROUND_INDEX["variant_B"]}
    gate(len(japanese_footprint) == 47, f"detail Japanese footprint drift: {len(japanese_footprint)}")
    gate(all(jp_a[y][x] == jp_b[y][x] for x, y in japanese_footprint), "A/B detail glyph footprint differs")
    gate(jp_b[7] == [BOTTOM_DELIMITER_INDEX] * 8 and jp_a[7] == [BOTTOM_DELIMITER_INDEX] * 8, "detail bottom delimiter drift")

    allowed_diff_offsets: set[int] = set()

    for name, spec in audit.TARGETS.items():
        old_desc = int(spec["descriptor"])
        old_addr = ROM_BASE + old_desc
        alloc = ALLOCATIONS[name]
        new_addr = ROM_BASE + alloc
        bg = BACKGROUND_INDEX[name]

        current_info = audit.decode_descriptor(source, old_desc)
        jp_info = audit.decode_descriptor(jp, old_desc)
        gate(current_info["decoded"] == jp_info["decoded"], f"remaining source already modified: {name}")
        before_pixels[name] = current_info["pixels"]

        new_pixels, ink_count, contour_count = paint_detail_tile(bg, korean_mask)
        new_raw = encode_tile(new_pixels)
        new_desc = build_descriptor(source[old_desc : old_desc + 0x14], new_raw)
        gate(source[alloc : alloc + ALLOC_SLOT_BYTES] == bytes(ALLOC_SLOT_BYTES), f"allocation is not zero-filled: {name} 0x{alloc:08X}")
        candidate[alloc : alloc + len(new_desc)] = new_desc
        allowed_diff_offsets.update(range(alloc, alloc + len(new_desc)))

        # Redirect every verified literal reference for this variant.
        for ref_addr in spec["literal_refs"]:
            ref_off = int(ref_addr) - ROM_BASE
            gate(struct.unpack_from("<I", source, ref_off)[0] == old_addr, f"literal source drift at 0x{ref_addr:08X}")
            struct.pack_into("<I", candidate, ref_off, new_addr)
            allowed_diff_offsets.update(range(ref_off, ref_off + 4))

        decoded_clone = audit.decode_descriptor(bytes(candidate), alloc)
        gate(decoded_clone["decoded"] == new_raw, f"relocated descriptor round-trip failed: {name}")
        gate(decoded_clone["pixels"] == new_pixels, f"relocated pixel round-trip failed: {name}")
        after_pixels[name] = new_pixels

        reports.append({
            "variant": name,
            "original_descriptor_file_offset": f"0x{old_desc:08X}",
            "original_descriptor_gba_address": f"0x{old_addr:08X}",
            "relocated_descriptor_file_offset": f"0x{alloc:08X}",
            "relocated_descriptor_gba_address": f"0x{new_addr:08X}",
            "literal_refs_redirected": [f"0x{x:08X}" for x in spec["literal_refs"]],
            "background_index": bg,
            "bottom_delimiter_index": BOTTOM_DELIMITER_INDEX,
            "face_index": FACE_INDEX,
            "contour_index": CONTOUR_INDEX,
            "japanese_footprint_pixels_cleared": len(japanese_footprint),
            "korean_ink_pixels": ink_count,
            "korean_contour_pixels": contour_count,
            "font": "Galmuri7.bdf native 6x7; exact accepted `지` mask reduced to the 8x8 fixed-detail cell",
            "compressed_body_bytes_before": current_info["graphic_len"],
            "compressed_body_bytes_after": len(new_desc) - 0x14,
            "decoded_sha256_before": sha256(current_info["decoded"]),
            "decoded_sha256_after": sha256(new_raw),
        })

    # Original fixed resources and the already-approved left-list edits must
    # remain untouched; only code literals + the two private clones may differ.
    for pname, (off, size) in PROTECTED_RANGES.items():
        gate(bytes(candidate[off : off + size]) == protected_before[pname], f"protected fixed graphic changed: {pname}")
    gate(struct.unpack_from("<I", candidate, D54_TABLE)[0] == D54_ORIGINAL_POINTER, "D54 pointer changed")

    diff_offsets = [i for i, (a, b) in enumerate(zip(source, candidate)) if a != b]
    gate(diff_offsets, "candidate has no changes")
    escaped = [i for i in diff_offsets if i not in allowed_diff_offsets]
    gate(not escaped, f"changes escaped allowed regions: {[hex(x) for x in escaped[:16]]}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(candidate)
    render_preview(before_pixels, after_pixels, args.preview)

    manifest = {
        "schema_version": 1,
        "kind": "ggen_advance_status_badges_hold_fixed_list_detail_followup_20260830",
        "result": "PASS",
        "source": {"path": str(args.input.relative_to(ROOT)), "sha256": sha256(source), "size": len(source)},
        "output": {"path": str(args.out.relative_to(ROOT)), "sha256": sha256(candidate), "size": len(candidate)},
        "architecture": {
            "finding": "final right-detail 持 is a compressed C491 1x1 fixed graphic selected by 0x08005D24, independent from E0518/D54 and the C439 left-list resource",
            "predicate": "0x08005D24",
            "draw_helper": "0x080638E4",
            "decompress_helper": "0x08001A84",
            "variants": reports,
            "relocation_reason": "native compressed body is 0x1E bytes while conservative literal-only rebuild is 0x24 bytes; private descriptor clones avoid overwriting adjacent native resources",
        },
        "verification": {
            "result": "PASS",
            "parent_hash_verified": True,
            "jp_hash_verified": True,
            "audit_passed": True,
            "two_detail_variants_patched": True,
            "four_literal_refs_redirected": True,
            "original_descriptors_unchanged": True,
            "direct_siblings_unchanged": True,
            "left_list_fixed_graphics_unchanged": True,
            "d54_pointer_preserved": f"0x{D54_ORIGINAL_POINTER:08X}",
            "allocations_zero_filled_before_write": True,
            "relocated_descriptors_round_trip_verified": True,
            "changes_restricted_to_literal_refs_and_private_clones": True,
            "changed_bytes_vs_input": len(diff_offsets),
        },
        "preview": str(args.preview.relative_to(ROOT)),
        "measurement_checkpoints": [
            "right-side unit-detail badge immediately before ability text such as `I 필드` should render `지` instead of `持`",
            "scroll/select units that exercise both A/B variants and confirm the small badge remains aligned",
            "left list `지`, right detail/lower-status `지`, `방패`, `만`, and existing `간` must remain identical to the previous measured candidates",
            "no neighboring ability text or fixed suffix graphics should shift or corrupt",
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
        "changed_bytes_vs_input": len(diff_offsets),
        "relocated": {name: f"0x{off:08X}" for name, off in ALLOCATIONS.items()},
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
