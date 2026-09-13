#!/usr/bin/env python3
"""Restore the C5A5DC hold badge's left cap from the live HP reference.

The 8x16 ``지`` cell starts at x=136, but its rounded left cap begins two
pixels earlier in the neighbouring C5A5DC tiles.  Those two columns still
contained the irregular Japanese ``持`` edge after the glyph-only follow-up.
Copy the measured two-column geometry from the HP plaque above and preserve
the Korean cell and every other package pixel byte-exactly.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parent.parent
MAIN_TIP = ROOT / "SD Gundam GGeneration Advance (Korean).gba"
MAIN_MANIFEST = ROOT / "integrated" / "main_tip" / "ggen_advance_main_tip_manifest.json"
OUT_DIR = ROOT / "outputs" / "20260830_ggen_advance_status_badges"
DEFAULT_OUT = OUT_DIR / "ggen_advance_status_sprite_package_hold_left_cap_candidate_20260830.gba"
DEFAULT_MANIFEST = ROOT / "analysis" / "ggen_advance_status_sprite_package_hold_left_cap_20260830.json"
DEFAULT_PREVIEW = OUT_DIR / "ggen_advance_status_sprite_package_hold_left_cap_preview_20260830.png"

EXPECTED_MAIN_SHA256 = "c6ab73870c122a16881a31189995eb412a3bb5149452ac543edc2b1f094c6c22"
LEFT_TOP = 0x00C5CE90
LEFT_BOTTOM = 0x00C5CEF0
GLYPH_TOP = 0x00C5CEB0
GLYPH_BOTTOM = 0x00C5CF10
TILE_BYTES = 32

# Current 16x16 live package canvas (left neighbour + Korean cell).
EXPECTED_BEFORE = (
    "04EFFFF666666666", "04EFFF6677777777", "04EFF66588876888",
    "04EFF67444444449", "04EFF6544AAAAA49", "04EFF649444A4A49",
    "04EFF64A844A4A49", "04EFF65484A4AA49", "04EFF65444A4AA49",
    "04EFF6544A444A49", "04EFF64A44484A49", "04EFF65488884449",
    "04EFF67488887889", "04EFF66488876888", "04EFFF6577766777",
    "04EFFFF666666666",
)

# Exact x=134..135 pixels measured from the HP plaque's live 16-row cap.
# Only these two columns are copied; 4 is the native dark inner rim adjacent
# to the label, while 5/6/7 form the red rounded gradient.
HP_LEFT_CAP = ("66", "65", "64") + ("74",) * 10 + ("66", "65", "66")

EXPECTED_AFTER = tuple(
    row[:6] + cap + row[8:] for row, cap in zip(EXPECTED_BEFORE, HP_LEFT_CAP)
)


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def decode_tile(raw: bytes | bytearray) -> list[int]:
    gate(len(raw) == TILE_BYTES, "4bpp tile size drift")
    pixels: list[int] = []
    for value in raw:
        pixels.extend((value & 0x0F, value >> 4))
    return pixels


def encode_tile(pixels: list[int]) -> bytes:
    gate(len(pixels) == 64, "4bpp tile pixel count drift")
    return bytes(pixels[i] | (pixels[i + 1] << 4) for i in range(0, 64, 2))


def rows_for(data: bytes | bytearray) -> tuple[str, ...]:
    tiles = [decode_tile(data[o:o + TILE_BYTES]) for o in
             (LEFT_TOP, GLYPH_TOP, LEFT_BOTTOM, GLYPH_BOTTOM)]
    rows: list[str] = []
    for pair in ((tiles[0], tiles[1]), (tiles[2], tiles[3])):
        for y in range(8):
            rows.append("".join(f"{v:X}" for tile in pair for v in tile[y * 8:(y + 1) * 8]))
    return tuple(rows)


def put_left_tile(data: bytearray, rows: tuple[str, ...]) -> None:
    for offset, band in ((LEFT_TOP, rows[:8]), (LEFT_BOTTOM, rows[8:])):
        pixels = [int(ch, 16) for row in band for ch in row[:8]]
        data[offset:offset + TILE_BYTES] = encode_tile(pixels)


def changed_ranges(offsets: list[int]) -> list[list[str]]:
    result: list[list[str]] = []
    if not offsets:
        return result
    start = previous = offsets[0]
    for value in offsets[1:]:
        if value != previous + 1:
            result.append([f"0x{start:08X}", f"0x{previous + 1:08X}"])
            start = value
        previous = value
    result.append([f"0x{start:08X}", f"0x{previous + 1:08X}"])
    return result


def make_preview(before: tuple[str, ...], after: tuple[str, ...], out: Path) -> None:
    palette = {
        0: (0, 255, 165), 4: (49, 47, 2), 5: (119, 56, 2),
        6: (239, 42, 15), 7: (255, 82, 15), 8: (255, 183, 43),
        9: (255, 227, 63), 10: (255, 255, 141), 14: (0, 232, 142),
        15: (0, 255, 165),
    }
    scale, pad, label_h, gap = 10, 14, 20, 24
    w, h = 16 * scale, 16 * scale
    image = Image.new("RGB", (pad * 2 + w * 2 + gap, pad * 2 + label_h + h), (244, 244, 244))
    draw = ImageDraw.Draw(image)
    for index, (label, canvas) in enumerate((("BEFORE", before), ("AFTER", after))):
        ox, oy = pad + index * (w + gap), pad + label_h
        draw.text((ox, pad), label, fill=(20, 20, 20))
        for y, row in enumerate(canvas):
            for x, char in enumerate(row):
                color = palette.get(int(char, 16), (130, 130, 130))
                draw.rectangle((ox + x * scale, oy + y * scale,
                                ox + (x + 1) * scale - 1, oy + (y + 1) * scale - 1), fill=color)
        draw.rectangle((ox + 6 * scale, oy, ox + 8 * scale - 1, oy + h - 1), outline=(255, 255, 255), width=1)
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=MAIN_TIP)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--preview", type=Path, default=DEFAULT_PREVIEW)
    args = parser.parse_args()

    source = args.input.read_bytes()
    gate(len(source) == 32 * 1024 * 1024, "input must be a 32 MiB ROM")
    gate(sha256(source) == EXPECTED_MAIN_SHA256, f"Main TIP hash drift: {sha256(source)}")
    approved = json.loads(MAIN_MANIFEST.read_text(encoding="utf-8"))
    gate(approved.get("status") == "approved_main_tip", "Main TIP is not approved")
    gate(approved.get("sha256") == EXPECTED_MAIN_SHA256, "Main TIP manifest hash drift")

    before = rows_for(source)
    gate(before == EXPECTED_BEFORE, f"live 16x16 canvas drift: {before}")
    candidate = bytearray(source)
    put_left_tile(candidate, EXPECTED_AFTER)
    after = rows_for(candidate)
    gate(after == EXPECTED_AFTER, "patched canvas did not round-trip")
    gate(tuple(row[8:] for row in after) == tuple(row[8:] for row in before), "Korean glyph cell changed")
    gate(all(after[y][:6] == before[y][:6] for y in range(16)), "pixels left of cap changed")
    gate(tuple(row[6:8] for row in after) == HP_LEFT_CAP, "HP cap geometry mismatch")

    changed = [i for i, (old, new) in enumerate(zip(source, candidate)) if old != new]
    gate(changed, "cap patch made no changes")
    gate(all(LEFT_TOP <= i < LEFT_TOP + TILE_BYTES or LEFT_BOTTOM <= i < LEFT_BOTTOM + TILE_BYTES for i in changed),
         "cap patch escaped adjacent tiles")

    output = bytes(candidate)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(output)
    make_preview(before, after, args.preview)
    manifest = {
        "schema_version": 1,
        "kind": "ggen_advance_status_sprite_package_hold_left_cap_20260830",
        "result": "PASS",
        "source": {"path": str(args.input.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256(source)},
        "output": {"path": str(args.out.relative_to(ROOT)).replace("\\", "/"), "size": len(output),
                   "sha256": sha256(output), "preview": str(args.preview.relative_to(ROOT)).replace("\\", "/")},
        "patch": {"target": "C5A5DC hold badge left cap at screen x=134..135,y=128..143",
                  "tile_offsets": [f"0x{LEFT_TOP:08X}", f"0x{LEFT_BOTTOM:08X}"],
                  "reference": "live HP plaque x=134..135,y=64..79",
                  "changed_bytes": len(changed), "changed_ranges": changed_ranges(changed)},
        "verification": {"result": "PASS", "parent_main_tip_hash_verified": True,
                         "hp_cap_16_rows_exactly_copied": True, "korean_glyph_cell_preserved": True,
                         "pixels_outside_two_cap_columns_preserved": True,
                         "changes_restricted_to_two_adjacent_tiles": True, "palette_modified": False},
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "out": str(args.out), "sha256": sha256(output),
                      "manifest": str(args.manifest), "preview": str(args.preview),
                      "changed_bytes": len(changed)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
