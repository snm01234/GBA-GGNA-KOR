#!/usr/bin/env python3
"""Image-first catalog of develop-menu 48x16 / 64x16 Japanese buttons.

Reads the original ROM packages, stitches every button canvas, writes a
labeled JP atlas, and records an explicit (package, animation, objects) ->
Korean map.  Labels were assigned by reading the rendered Japanese tiles,
not by even/odd or yellow-vs-blue leftover heuristics.

Live ss1/ss2 only bind which packages are on-screen.  Word identity comes
from the stitched images themselves.
"""
from __future__ import annotations

import hashlib
import json
import struct
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from PIL import Image

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_develop_menu_buttons_state_20260901 as analysis
import analyze_ggen_advance_settings_suspend_ui as sprite
from ggen_advance_project_paths import ADVANCE_ROOT, ORIGINAL_ROM, advance_relative

ROM_BASE = 0x08000000
OUT_DIR = ADVANCE_ROOT / "outputs" / "20260901_ggen_advance_develop_menu_buttons_image"
ATLAS = OUT_DIR / "ggen_advance_develop_menu_buttons_jp_atlas_20260901.png"
CATALOG = ADVANCE_ROOT / "analysis" / "ggen_advance_develop_menu_buttons_image_catalog_20260901.json"

PACKAGES = (
    {"name": "develop", "address": 0x08C5D5F0},
    {"name": "dismantle_popup", "address": 0x08C5FD14},
    {"name": "supply", "address": 0x08C4654C},
    {"name": "remodel_popup", "address": 0x08C64140},
)

# Read from the JP atlas: each row is one stitched button.  Korean is the
# on-screen replacement for that exact Japanese picture.
# The shared yellow 64px graphic (signature aa1414b178b5c034) is キャンセル,
# not 強化実行.  強化実行 yellow is 037ffbbc8e9c463c.
# 改造実行 + キャンセル live on sibling package 0x08C64140 (test-ROM ss1 anim 1).
# 改造実行 yellow is 4dde66578e449ad2.
BUTTONS: tuple[dict[str, Any], ...] = (
    {"package": "develop", "anim": 0, "kind": "48", "objects": (0, 1), "jp": "改造", "ko": "개조"},
    {"package": "develop", "anim": 1, "kind": "48", "objects": (0, 1), "jp": "強化", "ko": "강화"},
    {"package": "develop", "anim": 2, "kind": "48", "objects": (0, 1), "jp": "改造", "ko": "개조"},
    {"package": "develop", "anim": 3, "kind": "48", "objects": (0, 1), "jp": "強化", "ko": "강화"},
    {"package": "develop", "anim": 4, "kind": "64", "objects": (8, 9), "jp": "キャンセル", "ko": "캔슬"},
    {"package": "develop", "anim": 4, "kind": "64", "objects": (10, 11), "jp": "強化実行", "ko": "강화실행"},
    {"package": "develop", "anim": 5, "kind": "64", "objects": (8, 9), "jp": "キャンセル", "ko": "캔슬"},
    {"package": "develop", "anim": 5, "kind": "64", "objects": (10, 11), "jp": "強化実行", "ko": "강화실행"},
    {"package": "dismantle_popup", "anim": 0, "kind": "48", "objects": (0, 1), "jp": "改造", "ko": "개조"},
    {"package": "dismantle_popup", "anim": 1, "kind": "48", "objects": (0, 1), "jp": "強化", "ko": "강화"},
    {"package": "dismantle_popup", "anim": 2, "kind": "48", "objects": (0, 1), "jp": "改造", "ko": "개조"},
    {"package": "dismantle_popup", "anim": 3, "kind": "48", "objects": (0, 1), "jp": "強化", "ko": "강화"},
    {"package": "dismantle_popup", "anim": 4, "kind": "64", "objects": (6, 7), "jp": "分解実行", "ko": "분해실행"},
    {"package": "dismantle_popup", "anim": 4, "kind": "64", "objects": (8, 9), "jp": "キャンセル", "ko": "캔슬"},
    {"package": "dismantle_popup", "anim": 5, "kind": "64", "objects": (8, 9), "jp": "分解実行", "ko": "분해실행"},
    {"package": "dismantle_popup", "anim": 5, "kind": "64", "objects": (10, 11), "jp": "キャンセル", "ko": "캔슬"},
    {"package": "supply", "anim": 0, "kind": "48", "objects": (0, 1), "jp": "補給", "ko": "보급"},
    {"package": "supply", "anim": 1, "kind": "48", "objects": (0, 1), "jp": "処分", "ko": "처분"},
    {"package": "supply", "anim": 2, "kind": "48", "objects": (0, 1), "jp": "補給", "ko": "보급"},
    {"package": "supply", "anim": 3, "kind": "48", "objects": (0, 1), "jp": "処分", "ko": "처분"},
    {"package": "supply", "anim": 4, "kind": "64", "objects": (8, 9), "jp": "補給実行", "ko": "보급실행"},
    {"package": "supply", "anim": 4, "kind": "64", "objects": (10, 11), "jp": "キャンセル", "ko": "캔슬"},
    {"package": "supply", "anim": 5, "kind": "64", "objects": (8, 9), "jp": "キャンセル", "ko": "캔슬"},
    {"package": "supply", "anim": 5, "kind": "64", "objects": (10, 11), "jp": "補給実行", "ko": "보급실행"},
    {"package": "supply", "anim": 6, "kind": "64", "objects": (8, 9), "jp": "キャンセル", "ko": "캔슬"},
    {"package": "supply", "anim": 6, "kind": "64", "objects": (10, 11), "jp": "処分実行", "ko": "처분실행"},
    {"package": "supply", "anim": 7, "kind": "64", "objects": (8, 9), "jp": "キャンセル", "ko": "캔슬"},
    {"package": "supply", "anim": 7, "kind": "64", "objects": (10, 11), "jp": "処分実行", "ko": "처분실행"},
    {"package": "remodel_popup", "anim": 0, "kind": "64", "objects": (3, 4), "jp": "改造実行", "ko": "개조실행"},
    {"package": "remodel_popup", "anim": 0, "kind": "64", "objects": (5, 6), "jp": "キャンセル", "ko": "캔슬"},
    {"package": "remodel_popup", "anim": 1, "kind": "64", "objects": (8, 9), "jp": "キャンセル", "ko": "캔슬"},
    {"package": "remodel_popup", "anim": 1, "kind": "64", "objects": (10, 11), "jp": "改造実行", "ko": "개조실행"},
)


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def detect_style(canvas: list[list[int]]) -> str:
    interior: list[int] = []
    height, width = len(canvas), len(canvas[0])
    for y in range(2, height - 2):
        for x in range(8, width - 8):
            interior.append(canvas[y][x])
    counts = Counter(interior)
    score_yellow = counts.get(0xA, 0) + counts.get(0x5, 0)
    score_blue = counts.get(0xC, 0) + counts.get(0x1, 0)
    return "normal_yellow" if score_yellow >= score_blue else "focus_blue"


def style_indices(style: str) -> tuple[int, int]:
    if style == "normal_yellow":
        return 0xA, 0x5
    return 0xC, 0x1


def face_signature(canvas: list[list[int]], face: int) -> str:
    bits = bytearray()
    acc = 0
    n = 0
    for row in canvas:
        for pixel in row:
            acc = (acc << 1) | (1 if pixel == face else 0)
            n += 1
            if n == 8:
                bits.append(acc)
                acc = 0
                n = 0
    if n:
        bits.append(acc << (8 - n))
    return hashlib.sha256(bits).hexdigest()[:16]


def gba_rgb(value: int) -> tuple[int, int, int]:
    return ((value & 31) * 8, ((value >> 5) & 31) * 8, ((value >> 10) & 31) * 8)


def canvas_image(canvas: list[list[int]], palettes: bytes, bank: int, scale: int = 5) -> Image.Image:
    height, width = len(canvas), len(canvas[0])
    img = Image.new("RGB", (width, height))
    px = img.load()
    colors = [gba_rgb(struct.unpack_from("<H", palettes, (bank * 16 + i) * 2)[0]) for i in range(16)]
    for y in range(height):
        for x in range(width):
            px[x, y] = colors[canvas[y][x]]
    return img.resize((width * scale, height * scale), Image.NEAREST)


def pair_object_indices(parsed: dict[str, Any]) -> list[tuple[int, int]]:
    objects = parsed["objects"]
    pairs: list[tuple[int, int]] = []
    used: set[int] = set()
    for index in range(len(objects) - 1):
        if index in used or index + 1 in used:
            continue
        left, right = objects[index], objects[index + 1]
        if left["size_px"] == [32, 16] and right["size_px"] == [32, 16] and left["y"] == right["y"] and right["x"] == left["x"] + 32:
            pairs.append((index, index + 1))
            used.add(index)
            used.add(index + 1)
    return pairs


def parse_anim(records: list[tuple[int, bytes]], index: int) -> tuple[dict[str, Any], list[int], int]:
    start, record = records[index]
    marker = analysis.find_marker(record)
    gate(marker is not None, f"animation {index} marker missing")
    sliced = record[marker:]
    parsed = sprite.parse_animation_oam(sliced)
    total = sum(int(obj["tile_count"]) for obj in parsed["objects"])
    blob = b"".join(item[1] for item in records[index:])[marker:]
    gate(parsed["entries_end"] + total * 2 <= len(blob), f"animation {index} lookup truncated")
    ids = list(struct.unpack_from(f"<{total}H", blob, parsed["entries_end"]))
    lookup_file = start + marker + int(parsed["entries_end"])
    return parsed, ids, lookup_file


def enumerate_buttons(jp: bytes) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    by_key = {(row["package"], row["anim"], tuple(row["objects"])): row for row in BUTTONS}
    for spec in PACKAGES:
        header = analysis.parse_resource_header(jp, spec["address"])
        _graphics_rel, records = sprite.animation_records(jp, spec["address"])
        for anim in range(header["animation_count"]):
            parsed, ids, lookup_file = parse_anim(records, anim)
            objects = parsed["objects"]
            targets: list[tuple[str, tuple[int, ...], int]] = []
            if (
                anim <= 3
                and len(objects) == 2
                and objects[0]["size_px"] == [32, 16]
                and objects[1]["size_px"][1] == 16
            ):
                targets.append(("48", (0, 1), 48))
            if len(objects) == 12:
                for pair in pair_object_indices(parsed):
                    targets.append(("64", pair, 64))
            for kind, indices, width in targets:
                key = (spec["name"], anim, tuple(indices))
                gate(key in by_key, f"unstated button {key}")
                meta = by_key[key]
                canvas = analysis.stitch(header["graphics"], parsed, ids, list(indices))
                gate(len(canvas) == 16 and len(canvas[0]) == width, f"{key} size drift")
                style = detect_style(canvas)
                face, contour = style_indices(style)
                by_object: list[list[int]] = []
                cursor = 0
                for obj in objects:
                    count = int(obj["tile_count"])
                    by_object.append(ids[cursor:cursor + count])
                    cursor += count
                source_ids = [sid for i in indices for sid in by_object[i]]
                rows.append({
                    **meta,
                    "style": style,
                    "face": face,
                    "contour": contour,
                    "width": width,
                    "source_ids": source_ids,
                    "lookup_file": lookup_file,
                    "lookup_object_bases": [sum(int(objects[j]["tile_count"]) for j in range(i)) for i in indices],
                    "canvas": canvas,
                    "palettes": header["palettes"],
                    "signature": face_signature(canvas, face),
                    "bank": 0 if style == "normal_yellow" else 1,
                })
    gate(len(rows) == len(BUTTONS), "button coverage drift")
    return rows


def main() -> int:
    jp = ORIGINAL_ROM.read_bytes()
    gate(sha256(jp) == analysis.EXPECTED_JP_SHA256, "JP ROM hash drift")
    rows = enumerate_buttons(jp)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    scale = 5
    thumb_w, thumb_h = 64 * scale, 16 * scale
    atlas = Image.new("RGB", (thumb_w + 8, len(rows) * thumb_h + 8), (16, 16, 16))
    catalog_rows = []
    for index, row in enumerate(rows):
        img = canvas_image(row["canvas"], row["palettes"], row["bank"], scale)
        atlas.paste(img, (4, index * thumb_h + 4))
        catalog_rows.append({
            "index": index,
            "package": row["package"],
            "anim": row["anim"],
            "kind": row["kind"],
            "objects": list(row["objects"]),
            "jp": row["jp"],
            "ko": row["ko"],
            "style": row["style"],
            "face": row["face"],
            "contour": row["contour"],
            "width": row["width"],
            "source_ids": row["source_ids"],
            "signature": row["signature"],
        })
    atlas.save(ATLAS)
    yellow = [row for row in catalog_rows if row["style"] == "normal_yellow"]
    blue = [row for row in catalog_rows if row["style"] == "focus_blue"]
    gate(any(row["jp"] == "改造" and row["style"] == "normal_yellow" for row in catalog_rows), "yellow 改造 missing")
    gate(any(row["jp"] == "改造" and row["style"] == "focus_blue" for row in catalog_rows), "blue 改造 missing")
    gate(any(row["jp"] == "強化" and row["style"] == "normal_yellow" for row in catalog_rows), "yellow 強化 missing")
    gate(any(row["jp"] == "強化" and row["style"] == "focus_blue" for row in catalog_rows), "blue 強化 missing")
    gate(any(row["jp"] == "キャンセル" for row in catalog_rows), "キャンセル missing")
    yellow_cancel = [row for row in catalog_rows if row["signature"] == "aa1414b178b5c034"]
    yellow_execute = [row for row in catalog_rows if row["signature"] == "037ffbbc8e9c463c"]
    kaizo_execute = [row for row in catalog_rows if row["signature"] == "4dde66578e449ad2"]
    gate(yellow_cancel and all(row["jp"] == "キャンセル" and row["ko"] == "캔슬" for row in yellow_cancel), "shared yellow 64px is not キャンセル")
    gate(yellow_execute and all(row["jp"] == "強化実行" and row["ko"] == "강화실행" for row in yellow_execute), "distinct yellow 64px is not 強化実行")
    gate(kaizo_execute and all(row["jp"] == "改造実行" and row["ko"] == "개조실행" for row in kaizo_execute), "yellow 改造実行 signature drift")
    gate(any(row["jp"] == "改造実行" and row["style"] == "focus_blue" for row in catalog_rows), "blue 改造実行 missing")
    CATALOG.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "kind": "ggen_advance_develop_menu_buttons_image_catalog_20260901",
        "result": "PASS",
        "source_rom": advance_relative(ORIGINAL_ROM),
        "jp_sha256": sha256(jp),
        "atlas": advance_relative(ATLAS),
        "method": "stitch every 48x16 / 64x16 button from original packages; assign Korean by reading the Japanese raster",
        "counts": {"buttons": len(catalog_rows), "normal_yellow": len(yellow), "focus_blue": len(blue)},
        "buttons": catalog_rows,
    }
    CATALOG.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "atlas": str(ATLAS),
        "catalog": str(CATALOG),
        "buttons": len(catalog_rows),
        "labels": sorted({row["ko"] for row in catalog_rows}),
    }, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
