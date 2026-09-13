#!/usr/bin/env python3
"""Scan kind-0 sprite resources for fixed 所有数-shaped artwork.

This is a read-only ownership discovery pass.  It enumerates structurally valid
kind-0/tag-6 sprite resources in the Japanese ROM, reconstructs each parseable
metasprite animation, and scores every palette index/placement against the ROM's
own verified native 12x12 所/有/数 glyph bitmaps.  High shape score is evidence
only; consumers are proven separately before any patch is built.
"""
from __future__ import annotations

import hashlib
import json
import struct
import sys
from pathlib import Path
from typing import Any

from collections import Counter

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_develop_menu_buttons_state_20260901 as dev
import analyze_ggen_advance_settings_suspend_ui as sprite
import analyze_ggen_advance_jp_ko_ss1_n_tile_owned_count_20260903 as owned
from ggen_advance_project_paths import ADVANCE_ROOT, ORIGINAL_ROM, advance_relative

ROM_BASE = 0x08000000
EXPECTED_JP_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"
OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_owned_count_graphics_scan_20260904.json"


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def valid_resources(data: bytes) -> list[dict[str, int]]:
    rows: list[dict[str, int]] = []
    for off in range(0, len(data) - 0x20, 4):
        if data[off:off + 4] != b"\0\0\0\0":
            continue
        tag, graphics_rel, palette_rel, count = struct.unpack_from("<4I", data, off + 4)
        if tag != 6 or not (1 <= count <= 64):
            continue
        if not (0x18 + count * 4 <= graphics_rel < palette_rel <= 0x20000):
            continue
        if (palette_rel - graphics_rel) % 32:
            continue
        rels = struct.unpack_from(f"<{count}I", data, off + 0x14)
        starts = [0x14 + int(value) for value in rels]
        if not all(0x14 + count * 4 <= value < graphics_rel for value in starts):
            continue
        if any(starts[i] >= starts[i + 1] for i in range(count - 1)):
            continue
        rows.append({
            "offset": off,
            "address": ROM_BASE + off,
            "animation_count": count,
            "graphics_rel": graphics_rel,
            "palette_rel": palette_rel,
            "source_tiles": (palette_rel - graphics_rel) // 32,
        })
    return rows


def native_word_mask(data: bytes) -> set[tuple[int, int]]:
    out: set[tuple[int, int]] = set()
    for index, ch in enumerate("所有数"):
        pts = owned.glyph12_mask(data, owned.KANJI_SLOTS[ch])
        out.update((index * 12 + x, y) for x, y in pts)
    return out


def stitch_all(graphics: bytes, parsed: dict[str, Any], ids: list[int]) -> list[list[int]]:
    return dev.stitch(graphics, parsed, ids, list(range(len(parsed["objects"]))))


def best_score(canvas: list[list[int]], target: set[tuple[int, int]]) -> dict[str, Any] | None:
    height = len(canvas)
    width = len(canvas[0]) if height else 0
    th, tw = 12, 36
    if height < th or width < tw or height > 128 or width > 320:
        return None
    target_count = len(target)
    best = {"score": 0.0, "palette_index": -1, "x": -1, "y": -1, "observed_pixels": 0, "intersection": 0}
    by_palette: dict[int, list[tuple[int, int]]] = {value: [] for value in range(1, 16)}
    for y, row in enumerate(canvas):
        for x, value in enumerate(row):
            if 1 <= value <= 15:
                by_palette[value].append((x, y))
    for pal, points in by_palette.items():
        # A three-glyph face should be a minority of the canvas rather than a
        # huge background fill.  Keep a generous range for antialiased styles.
        if len(points) < 8 or len(points) > max(600, target_count * 5):
            continue
        point_set = set(points)
        offsets: Counter[tuple[int, int]] = Counter()
        for ox, oy in points:
            for tx, ty in target:
                x0, y0 = ox - tx, oy - ty
                if 0 <= x0 <= width - tw and 0 <= y0 <= height - th:
                    offsets[(x0, y0)] += 1
        for (x0, y0), inter in offsets.most_common(48):
            if inter < 8:
                break
            observed = sum(1 for x, y in points if x0 <= x < x0 + tw and y0 <= y < y0 + th)
            score = (2.0 * inter) / (observed + target_count)
            if score > float(best["score"]):
                best = {"score": score, "palette_index": pal, "x": x0, "y": y0, "observed_pixels": observed, "intersection": inter}
    return best


def main() -> int:
    data = ORIGINAL_ROM.read_bytes()
    gate(len(data) == 16 * 1024 * 1024, "JP ROM size drift")
    gate(sha256(data) == EXPECTED_JP_SHA256, "JP ROM hash drift")
    target = native_word_mask(data)
    resources = valid_resources(data)
    results: list[dict[str, Any]] = []
    parse_failures = 0
    animations_scanned = 0
    for row in resources:
        address = int(row["address"])
        off = int(row["offset"])
        graphics = data[off + int(row["graphics_rel"]):off + int(row["palette_rel"])]
        try:
            _gr, records = sprite.animation_records(data, address)
        except SystemExit:
            parse_failures += int(row["animation_count"])
            continue
        for animation in range(int(row["animation_count"])):
            try:
                parsed, ids = dev.parse_animation(records, animation)
                if not ids or max(ids) >= int(row["source_tiles"]):
                    raise ValueError("source id outside graphics")
                canvas = stitch_all(graphics, parsed, ids)
            except (SystemExit, ValueError, IndexError, struct.error):
                parse_failures += 1
                continue
            animations_scanned += 1
            score = best_score(canvas, target)
            if score is None or float(score["score"]) < 0.42:
                continue
            results.append({
                "resource_address": f"0x{address:08X}",
                "resource_file_offset": f"0x{off:08X}",
                "animation": animation,
                "animation_count": int(row["animation_count"]),
                "source_tiles": int(row["source_tiles"]),
                "canvas_size": [len(canvas[0]), len(canvas)],
                "object_count": len(parsed["objects"]),
                "source_ids": ids,
                **score,
            })
    results.sort(key=lambda item: float(item["score"]), reverse=True)
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_owned_count_graphics_scan_20260904",
        "result": "PASS",
        "source": {"path": advance_relative(ORIGINAL_ROM), "sha256": sha256(data)},
        "target": {"text": "所有数", "glyph_slots": {ch: f"0x{owned.KANJI_SLOTS[ch]:04X}" for ch in "所有数"}, "mask_pixels": len(target)},
        "resource_count": len(resources),
        "animations_scanned": animations_scanned,
        "parse_failures": parse_failures,
        "candidate_count": len(results),
        "candidates": results[:160],
        "policy": "shape score is shortlist evidence only; runtime/static consumer ownership must be established before patching",
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps({"result": "PASS", "out": advance_relative(OUT), "resources": len(resources), "animations_scanned": animations_scanned, "parse_failures": parse_failures, "top": results[:30]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
