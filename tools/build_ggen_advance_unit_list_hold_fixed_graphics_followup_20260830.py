#!/usr/bin/env python3
"""Patch the actual left unit-list `持` fixed graphics to Galmuri7 `지`.

Base is the runtime-tested E0518/status follow-up (`de69...`).  The rejected D54
candidate is deliberately not used.  Two literal-referenced C439-family 8x16
payloads are rebuilt in place while their 0x14-byte descriptors and every
sibling fixed graphic remain byte-exact.
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

import analyze_ggen_advance_unit_list_hold_fixed_graphics_20260830 as audit  # noqa: E402
import build_ggen_advance_hold_badge_full_followup_20260830 as hold  # noqa: E402
import test_ggen_advance_font_pair as fontpair  # noqa: E402
from ggen_advance_project_paths import FONT_ZIP  # noqa: E402

INPUT_ROM = ROOT / "outputs" / "20260830_ggen_advance_status_badges" / "ggen_advance_status_badges_hold_full_followup_candidate_20260830.gba"
JP_ROM = ROOT / "SD Gundam GGeneration Advance (Japan).gba"
OUT_DIR = ROOT / "outputs" / "20260830_ggen_advance_status_badges"
DEFAULT_OUT = OUT_DIR / "ggen_advance_status_badges_hold_fixed_list_followup_candidate_20260830.gba"
DEFAULT_MANIFEST = ROOT / "analysis" / "ggen_advance_status_badges_hold_fixed_list_followup_20260830.json"
DEFAULT_PREVIEW = OUT_DIR / "ggen_advance_status_badges_hold_fixed_list_followup_preview_20260830.png"

EXPECTED_INPUT_SHA256 = "de69dbc5f20a83784a1edc39760e3a4a5cb73210b584964fcb0c2070b6ca0ad1"
EXPECTED_JP_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"
D54_TABLE = 0x000D54E4
D54_ORIGINAL_POINTER = 0x080D45DC

HEADER_BYTES = audit.HEADER_BYTES
GRAPHIC_BYTES = audit.GRAPHIC_BYTES
FACE_INDEX = 10
CONTOUR_INDEX = 4
BOTTOM_DELIMITER_INDEX = 15
TARGETS = audit.TARGETS

# Siblings in the same C439 fixed-resource family.  None may change.
PROTECTED_RANGES = {
    "pre_status_B": (0x00C43C04, 0x54),
    "pre_status_A": (0x00C43C58, 0x54),
    "suffix_B": (0x00C43ACC, 0x34),
    "suffix_A": (0x00C43B00, 0x34),
    "other_pair_B": (0x00C438AC, 0x54),
    "other_pair_A": (0x00C43900, 0x54),
}


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def decode_8x16(raw: bytes) -> list[list[int]]:
    return audit.decode_8x16(raw)


def encode_8x16(pixels: list[list[int]]) -> bytes:
    gate(len(pixels) == 16 and all(len(row) == 8 for row in pixels), "8x16 shape mismatch")
    out = bytearray(GRAPHIC_BYTES)
    for y in range(16):
        base = 0 if y < 8 else 32
        row = base + (y & 7) * 4
        for x in range(8):
            value = pixels[y][x] & 0xF
            pos = row + (x >> 1)
            if x & 1:
                out[pos] = (out[pos] & 0x0F) | (value << 4)
            else:
                out[pos] = (out[pos] & 0xF0) | value
    return bytes(out)


def shifted_korean_mask(font7: fontpair.BdfFont) -> list[list[bool]]:
    # Native fixed Japanese art is exactly the status resource[12] geometry one
    # scanline upward.  Apply that same -1 Y relation to the already accepted
    # Galmuri7 mask instead of re-centering by eye.
    status_mask = hold.render_badge_mask(font7)
    out = [[False] * 8 for _ in range(16)]
    for y in range(15):
        out[y] = status_mask[y + 1][:]
    gate(sum(v for row in out for v in row) == sum(v for row in status_mask for v in row), "mask lost pixels during -1 shift")
    return out


def paint_mask(background_index: int, mask: list[list[bool]]) -> tuple[list[list[int]], int, int]:
    pixels = [[background_index] * 8 for _ in range(16)]
    pixels[15] = [BOTTOM_DELIMITER_INDEX] * 8
    contour = [[False] * 8 for _ in range(16)]
    for y in range(16):
        for x in range(8):
            if not mask[y][x]:
                continue
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    xx, yy = x + dx, y + dy
                    if 0 <= xx < 8 and 0 <= yy < 15 and not mask[yy][xx]:
                        contour[yy][xx] = True
    contour_count = 0
    ink_count = 0
    for y in range(15):
        for x in range(8):
            if contour[y][x]:
                pixels[y][x] = CONTOUR_INDEX
                contour_count += 1
    for y in range(15):
        for x in range(8):
            if mask[y][x]:
                pixels[y][x] = FACE_INDEX
                ink_count += 1
    return pixels, ink_count, contour_count


def make_preview(before: dict[str, list[list[int]]], after: dict[str, list[list[int]]], out: Path) -> None:
    scale = 7
    gap = 12
    pad = 8
    cols = 2
    rows = 2
    cell_w = 8 * scale
    cell_h = 16 * scale
    image = Image.new("RGB", (pad * 2 + cols * cell_w + gap, pad * 2 + rows * cell_h + gap), (255, 255, 255))
    palette = {
        4: (65, 45, 25), 5: (105, 70, 35), 9: (245, 160, 30),
        10: (250, 225, 70), 11: (255, 250, 155), 15: (255, 255, 255),
    }
    order = [("variant_B", before["variant_B"]), ("variant_B", after["variant_B"]), ("variant_A", before["variant_A"]), ("variant_A", after["variant_A"])]
    for n, (_, pixels) in enumerate(order):
        cx = n % 2
        cy = n // 2
        ox = pad + cx * (cell_w + gap)
        oy = pad + cy * (cell_h + gap)
        for y, row in enumerate(pixels):
            for x, value in enumerate(row):
                color = palette.get(value, (140, 140, 140))
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
    gate(sha256(source) == EXPECTED_INPUT_SHA256, f"tested status candidate hash drift: {sha256(source)}")
    gate(sha256(jp) == EXPECTED_JP_SHA256, "Japanese ROM hash drift")
    gate(struct.unpack_from("<I", source, D54_TABLE)[0] == D54_ORIGINAL_POINTER, "rejected D54 redirect is present in input")

    # Re-run the source audit as a build gate.
    audit_report_path = ROOT / "analysis" / "ggen_advance_unit_list_hold_fixed_graphics_20260830.json"
    gate(audit_report_path.exists(), "fixed-list source audit missing")
    audit_report = json.loads(audit_report_path.read_text(encoding="utf-8"))
    gate(audit_report.get("result") == "PASS", "fixed-list source audit not PASS")

    protected_before = {name: source[off : off + size] for name, (off, size) in PROTECTED_RANGES.items()}
    candidate = bytearray(source)
    before_pixels: dict[str, list[list[int]]] = {}
    after_pixels: dict[str, list[list[int]]] = {}
    reports = []

    with ZipFile(FONT_ZIP) as archive:
        font7 = fontpair.load_bdf(archive, "Galmuri7.bdf")
        mask = shifted_korean_mask(font7)

    # B is the easy-to-segment source: every Japanese glyph pixel is non-B/F.
    b_spec = TARGETS["variant_B"]
    b_graphic = int(b_spec["graphic_offset"])
    b_old = decode_8x16(jp[b_graphic : b_graphic + GRAPHIC_BYTES])
    japanese_footprint = {(x, y) for y in range(15) for x in range(8) if b_old[y][x] != int(b_spec["background_index"])}
    gate(len(japanese_footprint) == 95, f"Japanese fixed 持 footprint drift: {len(japanese_footprint)}")

    for name, spec in TARGETS.items():
        desc = int(spec["descriptor_offset"])
        graphic = int(spec["graphic_offset"])
        bg = int(spec["background_index"])
        gate(source[desc : desc + HEADER_BYTES + GRAPHIC_BYTES] == jp[desc : desc + HEADER_BYTES + GRAPHIC_BYTES], f"{name} source already modified")
        old = decode_8x16(source[graphic : graphic + GRAPHIC_BYTES])
        before_pixels[name] = old
        # Both variants share the same glyph footprint; they differ only by
        # B->A background substitution.  This proves we can clean the whole old
        # silhouette without touching neighboring/suffix resources.
        if name == "variant_A":
            b_flat = [v for row in b_old for v in row]
            a_flat = [v for row in old for v in row]
            diffs = [(b, a) for b, a in zip(b_flat, a_flat) if b != a]
            gate(len(diffs) == 25 and set(diffs) == {(11, 10)}, f"A/B fixed-resource relationship drift: {len(diffs)} {set(diffs)}")
            gate(all(old[y][x] == b_old[y][x] for x, y in japanese_footprint), "A variant glyph footprint differs from B variant")

        new_pixels, ink_count, contour_count = paint_mask(bg, mask)
        after = encode_8x16(new_pixels)
        gate(after != source[graphic : graphic + GRAPHIC_BYTES], f"{name} generated no change")
        candidate[graphic : graphic + GRAPHIC_BYTES] = after
        after_pixels[name] = new_pixels
        gate(candidate[desc : desc + HEADER_BYTES] == source[desc : desc + HEADER_BYTES], f"{name} descriptor header changed")
        reports.append({
            "variant": name,
            "descriptor_file_offset": f"0x{desc:08X}",
            "graphic_file_offset": f"0x{graphic:08X}",
            "literal_refs": [f"0x{x:08X}" for x in spec["literal_refs"]],
            "background_index": bg,
            "japanese_footprint_pixels_cleared": len(japanese_footprint),
            "korean_ink_pixels": ink_count,
            "korean_contour_pixels": contour_count,
            "font": "Galmuri7.bdf native 6x7; same approved status mask shifted -1 scanline",
            "before_sha256": sha256(source[graphic : graphic + GRAPHIC_BYTES]),
            "after_sha256": sha256(after),
            "descriptor_header_unchanged": True,
        })

    for name, (off, size) in PROTECTED_RANGES.items():
        gate(bytes(candidate[off : off + size]) == protected_before[name], f"protected C439 sibling changed: {name}")

    # Exact mutation gate: only the two 0x40 graphic payloads may differ.
    mutable = set()
    for spec in TARGETS.values():
        graphic = int(spec["graphic_offset"])
        mutable.update(range(graphic, graphic + GRAPHIC_BYTES))
    diff_offsets = [i for i, (a, b) in enumerate(zip(source, candidate)) if a != b]
    gate(diff_offsets, "candidate has no changes")
    gate(all(i in mutable for i in diff_offsets), f"changes escaped fixed graphic payloads: {[hex(i) for i in diff_offsets if i not in mutable][:8]}")
    gate(struct.unpack_from("<I", candidate, D54_TABLE)[0] == D54_ORIGINAL_POINTER, "D54 pointer changed")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(candidate)
    make_preview(before_pixels, after_pixels, args.preview)

    manifest = {
        "schema_version": 1,
        "kind": "ggen_advance_status_badges_hold_fixed_list_followup_20260830",
        "result": "PASS",
        "source": {"path": str(args.input.relative_to(ROOT)), "sha256": sha256(source), "size": len(source)},
        "output": {"path": str(args.out.relative_to(ROOT)), "sha256": sha256(candidate), "size": len(candidate)},
        "architecture": {
            "finding": "left list 持 is a C439-family fixed 8x16 graphic, not E0518/D54 final atlas source",
            "predicate": "0x08005D24",
            "draw_helper": "0x080638E4",
            "variants": reports,
            "rejected_d54_candidate_not_used": True,
            "d54_pointer_preserved": f"0x{D54_ORIGINAL_POINTER:08X}",
        },
        "verification": {
            "result": "PASS",
            "input_hash_verified": True,
            "jp_hash_verified": True,
            "two_fixed_variants_patched": True,
            "only_two_0x40_graphic_payloads_mutated": True,
            "descriptor_headers_unchanged": True,
            "protected_c439_siblings_unchanged": True,
            "d54_untouched": True,
            "status_detail_candidate_carried_forward_byte_exact_outside_two_fixed_payloads": True,
            "changed_bytes_vs_input": len(diff_offsets),
        },
        "preview": str(args.preview.relative_to(ROOT)),
        "measurement_checkpoints": [
            "left unit-list rows: the previously unchanged 持 badge should now read 지",
            "scroll across normal/alternate list states so both C43954 (B) and C439A8 (A) variants are exercised",
            "small right-side suffix/N graphics must remain unchanged and aligned",
            "right detail/status 지 and already approved 방패/만/간 must remain identical to the de69 input candidate",
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
        "patched_graphics": [r["graphic_file_offset"] for r in reports],
        "d54_pointer": f"0x{struct.unpack_from('<I', candidate, D54_TABLE)[0]:08X}",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
