#!/usr/bin/env python3
"""Compare Aina ss1 last glyph vs Aifee 15-cell ellipsis line."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import analyze_ggen_advance_jp_ko_ss1_n_tile_owned_count_20260903 as plaque
import analyze_ggen_advance_owned_count_ec0c_trace_runtime_20260904 as runtime
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
from ggen_advance_painted_glyph_identity import load_galmuri12, packed_12x12
from ggen_advance_project_paths import MAIN_TIP_ROM
from patch_ggen_advance_apsaras_zentetsu_20260908 import find_lookups
from patch_ggen_advance_dialogue_idcmd_fit_20260909 import read_tokens
from patch_ggen_advance_intermission_text_consumers_20260904 import payload_at
from patch_ggen_advance_map_script_inline_poc import ROM_BASE, raw_hex_bytes

OUT = ROOT / "outputs" / "20260910_aina_overflow_honorific"
BACKUP = (
    ROOT
    / "integrated"
    / "main_tip"
    / "backups"
    / "20260910T105844Z_user_requested_aina_overflow_honorific_20260910"
    / "SD Gundam GGeneration Advance (Korean).gba"
)
AINA = "GGA-MAPSCRIPT-00F7F729"
AIFEE = "GGA-MAPSCRIPT-00F51F73"


def ink_bbox(packed: bytes) -> dict[str, int]:
    cols = [False] * 12
    bits: list[int] = []
    for byte in packed:
        for bit in range(8):
            bits.append((byte >> (7 - bit)) & 1)
    bits = bits[:144]
    for y in range(12):
        for x in range(12):
            if bits[y * 12 + x]:
                cols[x] = True
    xs = [i for i, on in enumerate(cols) if on]
    return {
        "ink_x0": xs[0] if xs else -1,
        "ink_x1": xs[-1] if xs else -1,
        "ink_width": (xs[-1] - xs[0] + 1) if xs else 0,
        "right_empty_px": (11 - xs[-1]) if xs else 12,
        "advance": 12,
    }


def decode_row(rom: bytes, row: dict) -> dict:
    segs = list(row.get("segments") or [])
    cursor = int(str(row["target_file_offset"]), 16)
    out = []
    for index, (segment, text) in enumerate(zip(segs, row.get("translation_segments") or [])):
        original = raw_hex_bytes(str(segment.get("raw_hex") or ""))
        orig_addr = ROM_BASE + cursor
        orig_end = orig_addr + len(original) - 1
        lookups = find_lookups(rom, orig_addr, orig_end)
        neu = lookups[0][1]
        payload = payload_at(rom, neu)
        tokens = read_tokens(payload)
        out.append(
            {
                "index": index,
                "text": text,
                "text_len": len(text),
                "token_count": len(tokens),
                "payload": f"0x{neu:08X}",
                "tokens_match_chars": len(tokens) == len(text),
                "last_char": text[-1] if text else "",
            }
        )
        cursor += len(original)
    return {"record_id": row["record_id"], "lines": out}


def crop_region(img: Image.Image, box, scale: int = 8) -> Image.Image:
    x0, y0, x1, y1 = box
    crop = img.crop((x0, y0, x1, y1))
    return crop.resize((crop.width * scale, crop.height * scale), Image.Resampling.NEAREST)


def cell_ink(img: Image.Image, x0: int, x1: int, y0: int, y1: int) -> int:
    pix = img.load()
    n = 0
    for yy in range(y0, y1):
        for xx in range(x0, min(img.width, x1)):
            r, g, b = pix[xx, yy][:3]
            if r < 140 and g < 120:
                n += 1
    return n


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    aina_old = json.loads(
        (ROOT / "analysis" / "ggen_advance_translation_merged_20260909_creuset_names.json").read_text(encoding="utf-8")
    )
    current_merged = json.loads(
        (ROOT / "integrated" / "translation" / "ggen_advance_translation_merged.json").read_text(encoding="utf-8")
    )
    aina_row = next(r for r in aina_old["records"] if r["record_id"] == AINA)
    aifee_row = next(r for r in current_merged["records"] if r["record_id"] == AIFEE)
    backup = BACKUP.read_bytes()
    current = MAIN_TIP_ROM.read_bytes()
    font12 = load_galmuri12()
    glyphs = {char: ink_bbox(packed_12x12(char, font12)) for char in ("다", "니", "습", "…", "만", "지", "!")}

    aina_dec = decode_row(backup, aina_row)
    aifee_dec = decode_row(current, aifee_row)

    st, _ = statefmt.parse_png_state(ROOT / "SD Gundam GGeneration Advance (Korean).ss1")
    bg = plaque.composite_state(st)
    obj = runtime.render_obj(st)
    both = runtime.composite(st)
    pix = bg.load()
    y = 146
    dark = [x for x in range(48, 236) if pix[x, y][0] < 130 and pix[x, y][1] < 110]
    origin = dark[0] if dark else 52
    y0, y1 = 140, 156
    cells = [(origin + n * 12, origin + (n + 1) * 12) for n in range(15)]
    for name, img in (("bg", bg), ("obj", obj), ("both", both)):
        crop_region(img, (origin + 12 * 12 - 4, y0, min(240, origin + 15 * 12 + 10), y1)).save(OUT / f"ss1_last3_{name}.png")
        crop_region(img, (*cells[14], y0, y1)[:2] + (cells[14][1], y1) if False else (cells[14][0], y0, min(240, cells[14][1] + 6), y1)).save(
            OUT / f"ss1_cell15_{name}.png"
        )

    report = {
        "aina_old_line2": aina_row["translation_segments"][1],
        "aina_len": len(aina_row["translation_segments"][1]),
        "aifee_line2": aifee_row["translation_segments"][1],
        "aifee_len": len(aifee_row["translation_segments"][1]),
        "aina_last": aina_row["translation_segments"][1][-1],
        "aifee_last": aifee_row["translation_segments"][1][-1],
        "aina_decode_backup": aina_dec,
        "aifee_decode_current": aifee_dec,
        "glyph_ink": glyphs,
        "ss1_bg_origin_x": origin,
        "ss1_cells": [
            {
                "n": n + 1,
                "x": cells[n],
                "bg_ink": cell_ink(bg, cells[n][0], cells[n][1], y0, y1),
                "obj_ink": cell_ink(obj, cells[n][0], cells[n][1], y0, y1),
                "both_ink": cell_ink(both, cells[n][0], cells[n][1], y0, y1),
            }
            for n in range(12, 15)
        ],
        "jp_aina_line2_len": len("兵を犠牲にしようとしています"),
        "jp_aifee_line2_len": len("潰すつもりでなければいいが…"),
    }
    (OUT / "last_glyph_compare.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
