#!/usr/bin/env python3
"""Build a Korean fixed-graphic map popup-menu test ROM.

The five normal command rows and the five cursor-focus overlays are stored in
one custom-LZSS 4bpp atlas.  This builder keeps every resource dimension and
palette-bank selection intact, paints Korean labels into the decoded atlas,
relocates the rebuilt stream to the 32 MiB graphics append region, and redirects
only resource_table[0].
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path
from zipfile import ZipFile

from PIL import Image, ImageDraw

THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from ggen_advance_project_paths import FONT_ZIP  # noqa: E402
import test_ggen_advance_font_pair as fontpair  # noqa: E402

JP_ROM = ROOT / "SD Gundam GGeneration Advance (Japan).gba"
MAIN_ROM = ROOT / "SD Gundam GGeneration Advance (Korean).gba"
DEFAULT_OUT = (
    ROOT
    / "outputs"
    / "20260830_ggen_advance_map_menu"
    / "ggen_advance_map_menu_ko_test_v4_20260830.gba"
)
DEFAULT_MANIFEST = ROOT / "analysis" / "ggen_advance_map_menu_ko_poc_v4_20260830.json"
DEFAULT_PREVIEW = (
    ROOT
    / "outputs"
    / "20260830_ggen_advance_map_menu"
    / "ggen_advance_map_menu_ko_preview_v4_20260830.png"
)

EXPECTED_JP_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"
ROM_BASE = 0x08000000
RESOURCE_TABLE = 0x000D354C
ATLAS_RESOURCE = 0x000D2490
ATLAS_EXPECTED_DECODED = 6944
NORMAL_MAP = 0x000D311C
ALT_MAP = 0x000D3238
FOCUS_MAPS = (0x000D3450, 0x000D3474, 0x000D3498, 0x000D34BC, 0x000D34E0)
EXTRA_MAP = 0x000D3504
CANCEL_FOCUS_MAP = 0x000D3528

GRAPHICS_ALLOC = 0x01250000
GRAPHICS_ADDRESS = ROM_BASE + GRAPHICS_ALLOC

# Measured from the clean atlas: normal Japanese labels use bright index 11
# for the face and dark-brown index 5 for the surrounding shadow/contour.  v1
# accidentally reversed these two roles.
NORMAL_INK = 11
NORMAL_CONTOUR = 5
FOCUS_INK = 12
FOCUS_CONTOUR = 4

ALT_TURN_INK = 10
ALT_TURN_CONTOUR = 5

# These cells are the measured blank rounded-row backgrounds.  The same pixel
# indices are interpreted through the palette bank stored in each tilemap cell.
NORMAL_BACKGROUND = [
    [0x019, 0x01A, 0x01A, 0x01A, 0x01A, 0x01A, 0x01A, 0x01F],
    [0x020, 0x021, 0x021, 0x021, 0x021, 0x021, 0x021, 0x026],
]
FOCUS_BACKGROUND = [
    [0x08C, 0x08D, 0x08D, 0x08D, 0x08D, 0x08D, 0x08D, 0x092],
    [0x093, 0x094, 0x094, 0x094, 0x094, 0x094, 0x094, 0x099],
]

COMMANDS = [
    {
        "source": "ターン終了",
        "ko": "턴 종료",
        "normal": [
            [0x008, 0x009, 0x00A, 0x00B, 0x00C, 0x00D, 0x00E, 0x00F],
            [0x011, 0x012, 0x013, 0x014, 0x015, 0x016, 0x017, 0x018],
        ],
        "focus": [
            [0x07C, 0x07D, 0x07E, 0x07F, 0x080, 0x081, 0x082, 0x083],
            [0x084, 0x085, 0x086, 0x087, 0x088, 0x089, 0x08A, 0x08B],
        ],
    },
    {
        "source": "中断",
        "ko": "중단",
        "normal": [
            [0x019, 0x01A, 0x01B, 0x01C, 0x01D, 0x01E, 0x01A, 0x01F],
            [0x020, 0x021, 0x022, 0x023, 0x024, 0x025, 0x021, 0x026],
        ],
        "focus": [
            [0x08C, 0x08D, 0x08E, 0x08F, 0x090, 0x091, 0x08D, 0x092],
            [0x093, 0x094, 0x095, 0x096, 0x097, 0x098, 0x094, 0x099],
        ],
    },
    {
        "source": "状況",
        "ko": "상황",
        "normal": [
            [0x019, 0x01A, 0x027, 0x028, 0x029, 0x02A, 0x01A, 0x01F],
            [0x020, 0x021, 0x02B, 0x02C, 0x02D, 0x02E, 0x021, 0x026],
        ],
        "focus": [
            [0x08C, 0x08D, 0x09A, 0x09B, 0x09C, 0x09D, 0x08D, 0x092],
            [0x093, 0x094, 0x09E, 0x09F, 0x0A0, 0x0A1, 0x094, 0x099],
        ],
    },
    {
        "source": "部隊一覧",
        "ko": "부대목록",
        "normal": [
            [0x02F, 0x030, 0x031, 0x032, 0x033, 0x034, 0x035, 0x036],
            [0x037, 0x038, 0x039, 0x03A, 0x03B, 0x03C, 0x03D, 0x03E],
        ],
        # The original lower-row cell 4 reuses 0x086 from ターン終了.  Korean
        # content differs there, so resource[7] remaps only that cell to an
        # appended tile.  0x0C9 is NOT free: resource[10] uses 0x0C9..0x0D8
        # for the focused キャンセル graphic.
        "focus": [
            [0x0A2, 0x0A3, 0x0A4, 0x0A5, 0x0A6, 0x0A7, 0x0A8, 0x0A9],
            [0x0AA, 0x0AB, 0x0AC, 0x0AD, 0x0D9, 0x0AE, 0x0AF, 0x0B0],
        ],
    },
    {
        "source": "設定",
        "ko": "설정",
        "normal": [
            [0x019, 0x01A, 0x03F, 0x040, 0x041, 0x042, 0x01A, 0x01F],
            [0x020, 0x021, 0x043, 0x044, 0x045, 0x046, 0x021, 0x026],
        ],
        "focus": [
            [0x08C, 0x08D, 0x0B1, 0x0B2, 0x0B3, 0x0B4, 0x08D, 0x092],
            [0x093, 0x094, 0x0B5, 0x0B6, 0x0B7, 0x0B8, 0x094, 0x099],
        ],
    },
]

# Turn-end confirmation graphics.  resource[3] contains the alternate blue
# ターン終了 strip and both normal choices.  resource[9] and resource[10]
# are the two independent focus overlays.
ALT_TURN_TILES = [
    [0x04D, 0x04E, 0x04F, 0x050, 0x051, 0x052, 0x053, 0x054],
    [0x05C, 0x05D, 0x05E, 0x05F, 0x060, 0x061, 0x062, 0x063],
]
END_NORMAL_TILES = [
    [0x0DA, 0x056, 0x057, 0x058, 0x059, 0x05A, 0x05B, 0x0DB],
    [0x0DC, 0x065, 0x066, 0x067, 0x068, 0x069, 0x06A, 0x0DD],
]
CANCEL_NORMAL_TILES = [
    [0x06B, 0x06C, 0x06D, 0x06E, 0x06F, 0x070, 0x071, 0x072],
    [0x073, 0x074, 0x075, 0x076, 0x077, 0x078, 0x079, 0x07A],
]
END_FOCUS_TILES = [
    [0x0B9, 0x0BA, 0x0BB, 0x0BC, 0x0BD, 0x0BE, 0x0BF, 0x0C0],
    [0x0C1, 0x0C2, 0x0C3, 0x0C4, 0x0C5, 0x0C6, 0x0C7, 0x0C8],
]
CANCEL_FOCUS_TILES = [
    [0x0C9, 0x0CA, 0x0CB, 0x0CC, 0x0CD, 0x0CE, 0x0CF, 0x0D0],
    [0x0D1, 0x0D2, 0x0D3, 0x0D4, 0x0D5, 0x0D6, 0x0D7, 0x0D8],
]


def gate(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def lzss_decompress(payload: bytes) -> bytes:
    ring = bytearray(4096)
    ring_pos = 4078
    output = bytearray()
    source = 0
    flags = 0
    while source < len(payload):
        flags >>= 1
        if (flags & 0x100) == 0:
            flags = payload[source] | 0xFF00
            source += 1
        if flags & 1:
            gate(source < len(payload), "literal overruns compressed menu atlas")
            value = payload[source]
            source += 1
            output.append(value)
            ring[ring_pos] = value
            ring_pos = (ring_pos + 1) & 0xFFF
        else:
            gate(source + 1 < len(payload), "back-reference overruns compressed menu atlas")
            lo = payload[source]
            hi = payload[source + 1]
            source += 2
            offset = lo | ((hi & 0xF0) << 4)
            length = (hi & 0x0F) + 3
            for index in range(length):
                value = ring[(offset + index) & 0xFFF]
                output.append(value)
                ring[ring_pos] = value
                ring_pos = (ring_pos + 1) & 0xFFF
    return bytes(output)


def literal_only_compress(decoded: bytes) -> bytes:
    body = bytearray()
    for start in range(0, len(decoded), 8):
        chunk = decoded[start : start + 8]
        body.append((1 << len(chunk)) - 1)
        body.extend(chunk)
    gate(len(body) <= 0xFFFF, "rebuilt menu atlas exceeds decoder length field")
    return struct.pack("<I", 0x80000000 | len(body)) + body


def decode_tile(atlas: bytes | bytearray, tile_id: int) -> list[list[int]]:
    start = tile_id * 32
    gate(start + 32 <= len(atlas), f"tile 0x{tile_id:03X} outside menu atlas")
    output = [[0] * 8 for _ in range(8)]
    for y in range(8):
        for x in range(8):
            value = atlas[start + y * 4 + x // 2]
            output[y][x] = (value >> (4 * (x & 1))) & 0x0F
    return output


def encode_tile(tile: list[list[int]]) -> bytes:
    output = bytearray(32)
    for y in range(8):
        for x in range(8):
            output[y * 4 + x // 2] |= (tile[y][x] & 0x0F) << (4 * (x & 1))
    return bytes(output)


def stitch(atlas: bytes | bytearray, tile_rows: list[list[int]]) -> list[list[int]]:
    output = [[0] * 64 for _ in range(16)]
    for ty, row in enumerate(tile_rows):
        for tx, tile_id in enumerate(row):
            tile = decode_tile(atlas, tile_id)
            for y in range(8):
                output[ty * 8 + y][tx * 8 : tx * 8 + 8] = tile[y]
    return output


def build_alt_turn_background(atlas: bytes | bytearray) -> list[list[int]]:
    """Remove the alternate ターン終了 glyph while retaining its blue frame."""
    pixels = stitch(atlas, ALT_TURN_TILES)
    # In this strip indices 10/5 are the light face/dark contour.  The native
    # background is a simple rounded field: scanlines 1/14 use index 6 and the
    # inner scanlines use index 7.  Frame indices 11/6/7 remain byte-exact.
    for y, row in enumerate(pixels):
        replacement = 6 if y in {1, 14} else 7
        for x, value in enumerate(row):
            if value in {ALT_TURN_INK, ALT_TURN_CONTOUR}:
                row[x] = replacement
    gate(
        {value for row in pixels for value in row} <= {6, 7, 11},
        "alternate turn-end background reconstruction drift",
    )
    return pixels


def render_label(
    text: str,
    font: fontpair.BdfFont,
    glyph_mode: str,
    background: list[list[int]],
    ink: int,
    contour: int,
) -> tuple[list[list[int]], int, int]:
    gate(len(background) == 16 and all(len(row) == 64 for row in background), "invalid background")
    pixels = [row[:] for row in background]
    if glyph_mode == "12x12":
        cell_width, cell_height = 12, 12
        renderer = fontpair.render_12x12_basic
    else:
        gate(False, f"unsupported menu glyph mode: {glyph_mode}")
    parts: list[tuple[Image.Image | None, int]] = []
    for char in text:
        if char == " ":
            parts.append((None, 4))
        else:
            parts.append((renderer(char, font), cell_width))
    text_width = sum(width for _, width in parts)
    gate(text_width <= 60, f"label does not fit 64px row: {text}")
    x_cursor = (64 - text_width) // 2
    y_origin = (16 - cell_height) // 2
    mask = [[False] * 64 for _ in range(16)]
    for glyph, width in parts:
        if glyph is not None:
            for y in range(cell_height):
                for x in range(width):
                    if glyph.getpixel((x, y)):
                        mask[y_origin + y][x_cursor + x] = True
        x_cursor += width

    outline = [[False] * 64 for _ in range(16)]
    for y in range(16):
        for x in range(64):
            if not mask[y][x]:
                continue
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    ox, oy = x + dx, y + dy
                    if (
                        (dx or dy)
                        and 0 <= ox < 64
                        and 0 <= oy < 16
                        and not mask[oy][ox]
                    ):
                        outline[oy][ox] = True
    for y in range(16):
        for x in range(64):
            if outline[y][x]:
                pixels[y][x] = contour
            if mask[y][x]:
                pixels[y][x] = ink
    return (
        pixels,
        sum(sum(row) for row in mask),
        sum(sum(row) for row in outline),
    )


def split_tiles(pixels: list[list[int]], tile_rows: list[list[int]]) -> dict[int, bytes]:
    output: dict[int, bytes] = {}
    for ty, row in enumerate(tile_rows):
        for tx, tile_id in enumerate(row):
            tile = [
                source[tx * 8 : tx * 8 + 8]
                for source in pixels[ty * 8 : ty * 8 + 8]
            ]
            payload = encode_tile(tile)
            previous = output.get(tile_id)
            gate(previous is None or previous == payload, f"same label assigns conflicting tile 0x{tile_id:03X}")
            output[tile_id] = payload
    return output


def apply_payloads(atlas: bytearray, payloads: dict[int, bytes]) -> list[dict[str, object]]:
    reports = []
    for tile_id, payload in sorted(payloads.items()):
        start = tile_id * 32
        before = bytes(atlas[start : start + 32])
        atlas[start : start + 32] = payload
        reports.append(
            {
                "tile_id": f"0x{tile_id:03X}",
                "changed_bytes": sum(a != b for a, b in zip(before, payload)),
                "before_sha256": sha256(before),
                "after_sha256": sha256(payload),
            }
        )
    return reports


def build_preview(rows: list[dict[str, object]], out: Path) -> None:
    scale = 4
    margin = 12
    row_height = 16 * scale + 12
    image = Image.new(
        "RGB",
        (64 * scale * 2 + margin * 3, row_height * len(rows) + 34),
        "#20252b",
    )
    draw = ImageDraw.Draw(image)
    draw.text((margin, 8), "NORMAL", fill="#ffffff")
    draw.text((margin * 2 + 64 * scale, 8), "FOCUS", fill="#ffffff")

    normal_palette = {
        4: "#182444", 5: "#6c3900", 8: "#ffe650", 9: "#ffc52f",
        10: "#ffe34b", 11: "#fff18a", 12: "#ffffff",
    }
    focus_palette = {
        4: "#102452", 5: "#24406d", 6: "#168de5", 7: "#5ac9f5",
        8: "#a7eef5", 9: "#baf5f9",
        10: "#d0fbfc", 11: "#e3ffff", 12: "#ffffff",
    }

    def paint(pixels: list[list[int]], x0: int, y0: int, palette: dict[int, str]) -> None:
        for y, source in enumerate(pixels):
            for x, value in enumerate(source):
                colour = palette.get(value, "#808080")
                draw.rectangle(
                    (x0 + x * scale, y0 + y * scale, x0 + (x + 1) * scale - 1, y0 + (y + 1) * scale - 1),
                    fill=colour,
                )

    for index, row in enumerate(rows):
        y = 30 + index * row_height
        normal_row_palette = (
            focus_palette if row.get("normal_palette_mode") == "focus" else normal_palette
        )
        focus_row_palette = (
            normal_palette if row.get("focus_palette_mode") == "normal" else focus_palette
        )
        paint(row["normal_pixels"], margin, y, normal_row_palette)  # type: ignore[arg-type]
        paint(row["focus_pixels"], margin * 2 + 64 * scale, y, focus_row_palette)  # type: ignore[arg-type]
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out)


def map_dimensions(data: bytes | bytearray, offset: int) -> tuple[int, int]:
    return data[offset], data[offset + 1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--main", type=Path, default=MAIN_ROM)
    parser.add_argument("--base-manifest", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--preview", type=Path, default=DEFAULT_PREVIEW)
    parser.add_argument("--font-zip", type=Path, default=FONT_ZIP)
    args = parser.parse_args()

    jp = JP_ROM.read_bytes()
    gate(sha256(jp) == EXPECTED_JP_SHA256, "clean Japanese ROM hash mismatch")
    main_rom = args.main.read_bytes()
    gate(len(main_rom) == 32 * 1024 * 1024, "base main ROM must be 32 MiB")
    base_manifest_meta = None
    if args.base_manifest is not None:
        base_manifest = json.loads(args.base_manifest.read_text(encoding="utf-8"))
        base_output = base_manifest.get("output") or {}
        base_verification = base_manifest.get("verification") or {}
        gate(base_verification.get("result") == "PASS", "base candidate verification is not PASS")
        gate(int(base_output.get("size", -1)) == len(main_rom), "base candidate size differs from manifest")
        gate(str(base_output.get("sha256", "")).lower() == sha256(main_rom), "base candidate hash differs from manifest")
        base_manifest_meta = {
            "path": str(args.base_manifest.resolve().relative_to(ROOT.resolve())),
            "kind": base_manifest.get("kind"),
            "sha256": sha256(args.base_manifest.read_bytes()),
            "verification": base_verification,
        }
    gate(map_dimensions(jp, NORMAL_MAP) == (10, 14), "normal menu map dimensions drift")
    gate(map_dimensions(jp, ALT_MAP) == (19, 14), "alternate menu map dimensions drift")
    gate(all(map_dimensions(jp, offset) == (8, 2) for offset in FOCUS_MAPS), "focus map dimensions drift")
    gate(map_dimensions(jp, EXTRA_MAP) == (8, 2), "end-choice focus map dimensions drift")
    gate(map_dimensions(jp, CANCEL_FOCUS_MAP) == (8, 2), "cancel focus map dimensions drift")

    header = struct.unpack_from("<I", jp, ATLAS_RESOURCE)[0]
    gate(header & 0x80000000, "menu atlas is not custom-LZSS compressed")
    compressed_length = header & 0xFFFF
    decoded = lzss_decompress(jp[ATLAS_RESOURCE + 4 : ATLAS_RESOURCE + 4 + compressed_length])
    gate(len(decoded) == ATLAS_EXPECTED_DECODED, f"decoded menu atlas size drift: {len(decoded)}")
    gate(len(decoded) // 32 == 217, "menu atlas tile count drift")
    atlas = bytearray(decoded)

    normal_background = stitch(decoded, NORMAL_BACKGROUND)
    focus_background = stitch(decoded, FOCUS_BACKGROUND)
    alt_turn_background = build_alt_turn_background(decoded)
    gate({value for row in normal_background for value in row} <= {9, 10, 11}, "normal background palette drift")
    gate({value for row in focus_background for value in row} <= {8, 9, 10, 11}, "focus background palette drift")

    with ZipFile(args.font_zip) as archive:
        font12 = fontpair.load_bdf(archive, "Galmuri11.bdf")

    assigned: dict[int, bytes] = {}
    label_reports = []
    preview_rows = []
    for command in COMMANDS:
        normal_pixels, normal_ink, normal_outline = render_label(
            command["ko"], font12, "12x12", normal_background, NORMAL_INK, NORMAL_CONTOUR
        )
        focus_pixels, focus_ink, focus_outline = render_label(
            command["ko"], font12, "12x12", focus_background, FOCUS_INK, FOCUS_CONTOUR
        )
        command_payloads = {}
        command_payloads.update(split_tiles(normal_pixels, command["normal"]))
        command_payloads.update(split_tiles(focus_pixels, command["focus"]))
        for tile_id, payload in command_payloads.items():
            previous = assigned.get(tile_id)
            gate(previous is None or previous == payload, f"cross-label tile conflict at 0x{tile_id:03X}")
            assigned[tile_id] = payload
        label_reports.append(
            {
                "source": command["source"],
                "ko": command["ko"],
                "normal": {"glyph_mode": "12x12", "ink_pixels": normal_ink, "outline_pixels": normal_outline},
                "focus": {"glyph_mode": "12x12", "ink_pixels": focus_ink, "outline_pixels": focus_outline},
                "normal_tile_ids": [[f"0x{x:03X}" for x in row] for row in command["normal"]],
                "focus_tile_ids": [[f"0x{x:03X}" for x in row] for row in command["focus"]],
            }
        )
        preview_rows.append({"normal_pixels": normal_pixels, "focus_pixels": focus_pixels})

    # Translate every fixed graphic used after selecting ターン終了.
    alt_turn_pixels, alt_turn_ink, alt_turn_outline = render_label(
        "턴 종료", font12, "12x12", alt_turn_background, ALT_TURN_INK, ALT_TURN_CONTOUR
    )
    secondary_payloads = split_tiles(alt_turn_pixels, ALT_TURN_TILES)
    secondary_reports = [
        {
            "role": "alternate_turn_end",
            "source": "ターン終了",
            "ko": "턴 종료",
            "state": "selected_parent_different_background",
            "ink_pixels": alt_turn_ink,
            "outline_pixels": alt_turn_outline,
            "tile_ids": [[f"0x{x:03X}" for x in row] for row in ALT_TURN_TILES],
        }
    ]
    preview_rows.append({
        "normal_pixels": alt_turn_pixels,
        "focus_pixels": alt_turn_pixels,
        "normal_palette_mode": "focus",
    })

    confirmation_specs = (
        ("終了する", "종료한다", END_NORMAL_TILES, END_FOCUS_TILES),
        ("キャンセル", "캔슬", CANCEL_NORMAL_TILES, CANCEL_FOCUS_TILES),
    )
    for source, ko, normal_tiles, focus_tiles in confirmation_specs:
        normal_pixels, normal_ink, normal_outline = render_label(
            ko, font12, "12x12", normal_background, NORMAL_INK, NORMAL_CONTOUR
        )
        focus_pixels, focus_ink, focus_outline = render_label(
            ko, font12, "12x12", focus_background, FOCUS_INK, FOCUS_CONTOUR
        )
        for tile_id, payload in split_tiles(normal_pixels, normal_tiles).items():
            previous = secondary_payloads.get(tile_id)
            gate(previous is None or previous == payload, f"secondary normal conflict at 0x{tile_id:03X}")
            secondary_payloads[tile_id] = payload
        for tile_id, payload in split_tiles(focus_pixels, focus_tiles).items():
            previous = secondary_payloads.get(tile_id)
            gate(previous is None or previous == payload, f"secondary focus conflict at 0x{tile_id:03X}")
            secondary_payloads[tile_id] = payload
        secondary_reports.append(
            {
                "role": "confirmation_choice",
                "source": source,
                "ko": ko,
                "normal": {"ink_pixels": normal_ink, "outline_pixels": normal_outline},
                "focus": {"ink_pixels": focus_ink, "outline_pixels": focus_outline},
                "normal_tile_ids": [[f"0x{x:03X}" for x in row] for row in normal_tiles],
                "focus_tile_ids": [[f"0x{x:03X}" for x in row] for row in focus_tiles],
            }
        )
        preview_rows.append({"normal_pixels": normal_pixels, "focus_pixels": focus_pixels})

    for tile_id, payload in secondary_payloads.items():
        previous = assigned.get(tile_id)
        gate(previous is None or previous == payload, f"main/secondary tile conflict at 0x{tile_id:03X}")
        assigned[tile_id] = payload

    # Original atlas ends at tile 0x0D8.  Append 0x0D9..0x0DD for the unit-list
    # collision fix and the four normal 終了する edge cells.
    rebuilt_tile_count = 0x0DE
    atlas.extend(bytes(rebuilt_tile_count * 32 - len(atlas)))
    changed_tiles = apply_payloads(atlas, assigned)
    rebuilt_resource = literal_only_compress(bytes(atlas))
    gate(lzss_decompress(rebuilt_resource[4:]) == bytes(atlas), "rebuilt menu atlas round-trip mismatch")

    candidate = bytearray(main_rom)
    original_pointer = struct.unpack_from("<I", candidate, RESOURCE_TABLE)[0]
    gate(original_pointer in {ROM_BASE + ATLAS_RESOURCE, GRAPHICS_ADDRESS}, f"menu atlas pointer drift: 0x{original_pointer:08X}")
    allocation_before = bytes(
        candidate[GRAPHICS_ALLOC : GRAPHICS_ALLOC + len(rebuilt_resource)]
    )
    gate(
        allocation_before in {bytes(len(rebuilt_resource)), bytes(rebuilt_resource)},
        "menu graphics allocation is occupied",
    )
    candidate[GRAPHICS_ALLOC : GRAPHICS_ALLOC + len(rebuilt_resource)] = rebuilt_resource
    struct.pack_into("<I", candidate, RESOURCE_TABLE, GRAPHICS_ADDRESS)

    # resource[7], lower row, x=4: replace shared 0x086 with appended 0x0D9.
    remap_offset = FOCUS_MAPS[3] + 4 + (8 + 4) * 2
    original_cell = struct.unpack_from("<H", candidate, remap_offset)[0]
    gate((original_cell & 0x03FF) in {0x086, 0x0D9}, f"unit-list focus remap source drift: 0x{original_cell:04X}")
    remapped_cell = (original_cell & 0xFC00) | 0x0D9
    struct.pack_into("<H", candidate, remap_offset, remapped_cell)

    # resource[3] normally reuses four global rounded-frame edge tiles for
    # 終了する.  A 12x12 four-syllable label reaches those cells, so clone them
    # to appended tiles rather than corrupting every other normal row.
    edge_remap_specs = (
        (1, 10, 0x019, 0x0DA),
        (1, 17, 0x01F, 0x0DB),
        (2, 10, 0x020, 0x0DC),
        (2, 17, 0x026, 0x0DD),
    )
    edge_remaps = []
    for y, x, old_tile, new_tile in edge_remap_specs:
        offset = ALT_MAP + 4 + (y * 19 + x) * 2
        before = struct.unpack_from("<H", candidate, offset)[0]
        gate((before & 0x03FF) in {old_tile, new_tile}, f"confirmation edge remap drift at 0x{offset:08X}")
        after = (before & 0xFC00) | new_tile
        struct.pack_into("<H", candidate, offset, after)
        edge_remaps.append({
            "file_offset": f"0x{offset:08X}",
            "before": f"0x{before:04X}",
            "after": f"0x{after:04X}",
        })

    gate(len(candidate) == len(main_rom), "test ROM size drift")
    allowed = set(range(RESOURCE_TABLE, RESOURCE_TABLE + 4)) | {remap_offset, remap_offset + 1}
    for item in edge_remaps:
        offset = int(item["file_offset"], 16)
        allowed.update({offset, offset + 1})
    unexpected = [
        offset
        for offset in range(0x01000000)
        if candidate[offset] != main_rom[offset] and offset not in allowed
    ]
    gate(not unexpected, f"unexpected changes in original ROM half: {unexpected[:8]}")
    gate(
        candidate[0x01000000:GRAPHICS_ALLOC] == main_rom[0x01000000:GRAPHICS_ALLOC],
        "base append data before menu allocation changed",
    )
    gate(
        candidate[GRAPHICS_ALLOC + len(rebuilt_resource) :] == main_rom[GRAPHICS_ALLOC + len(rebuilt_resource) :],
        "base append data after menu allocation changed",
    )
    gate(candidate[EXTRA_MAP : EXTRA_MAP + 36] == main_rom[EXTRA_MAP : EXTRA_MAP + 36], "resource[9] changed")
    gate(candidate[CANCEL_FOCUS_MAP : CANCEL_FOCUS_MAP + 36] == main_rom[CANCEL_FOCUS_MAP : CANCEL_FOCUS_MAP + 36], "resource[10] changed")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(candidate)
    build_preview(preview_rows, args.preview)

    manifest = {
        "schema_version": 1,
        "kind": "ggen_advance_map_menu_ui_ko_poc_v4",
        "result": "PASS",
        "source_main": {"path": str(args.main.resolve().relative_to(ROOT.resolve())), "size": len(main_rom), "sha256": sha256(main_rom)},
        "source_main_manifest": base_manifest_meta,
        "output": {"path": str(args.out.resolve().relative_to(ROOT.resolve())), "size": len(candidate), "sha256": sha256(candidate)},
        "atlas": {
            "original_file_offset": f"0x{ATLAS_RESOURCE:08X}",
            "original_compressed_length": compressed_length,
            "decoded_size": len(decoded),
            "decoded_tile_count": len(decoded) // 32,
            "rebuilt_decoded_size": len(atlas),
            "rebuilt_tile_count": len(atlas) // 32,
            "relocated_file_offset": f"0x{GRAPHICS_ALLOC:08X}",
            "relocated_address": f"0x{GRAPHICS_ADDRESS:08X}",
            "rebuilt_compressed_length": len(rebuilt_resource) - 4,
            "decoded_sha256_before": sha256(decoded),
            "decoded_sha256_after": sha256(atlas),
            "round_trip_verified": True,
        },
        "rendering": {
            "normal_font": "Galmuri11.bdf native 12x12 (same size and bitmap as focus)",
            "focus_font": "Galmuri11.bdf native 12x12",
            "normal_palette_indices": {"ink": NORMAL_INK, "contour": NORMAL_CONTOUR},
            "focus_palette_indices": {"ink": FOCUS_INK, "contour": FOCUS_CONTOUR},
            "outline": "8-neighbour 1px contour",
            "normal_correction": "native 12x12 without scaling; bright index 11 face + dark index 5 contour",
            "palette_data_modified": False,
        },
        "labels": label_reports,
        "turn_end_confirmation": secondary_reports,
        "changed_tiles": changed_tiles,
        "tilemap_remaps": {
            "unit_list_focus": {
                "resource_index": 7,
                "file_offset": f"0x{remap_offset:08X}",
                "before": f"0x{original_cell:04X}",
                "after": f"0x{remapped_cell:04X}",
                "reason": "部隊一覧 focus shared tile 0x086 conflicts with ターン終了; remapped to appended 0x0D9",
            },
            "end_choice_normal_edges": edge_remaps,
        },
        "preserved": {
            "resource_dimensions": True,
            "palette_data": True,
            "alternate_resource_3_dimensions": True,
            "resource_9_tilemap": True,
            "resource_10_tilemap": True,
        },
        "preview": str(args.preview.resolve().relative_to(ROOT.resolve())),
        "verification": {
            "result": "PASS",
            "compression_round_trip": True,
            "original_half_allowed_change_bytes": len(allowed),
            "original_half_unexpected_change_bytes": 0,
            "main_focus_states_built": 5,
            "main_normal_labels_built": 5,
            "confirmation_focus_states_built": 2,
            "confirmation_normal_states_built": 2,
            "alternate_turn_end_built": True,
            "resource_10_cancel_focus_collision_fixed": True,
            "base_candidate_verified_against_manifest": base_manifest_meta is not None,
            "base_candidate_bytes_preserved_outside_menu_patch": True,
            "shared_tile_conflicts_remaining": 0,
        },
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "result": "PASS",
                "out": str(args.out),
                "sha256": sha256(candidate),
                "manifest": str(args.manifest),
                "preview": str(args.preview),
                "normal_labels": 7,
                "focus_overlays": 7,
                "alternate_turn_end": 1,
                "changed_tiles": len(changed_tiles),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
