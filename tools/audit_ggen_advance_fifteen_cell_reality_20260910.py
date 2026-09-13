#!/usr/bin/env python3
"""Measure whether 15-cell portrait lines actually clip, and how many."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from ggen_advance_project_paths import TRANSLATION_MERGED_JSON  # noqa: E402

OUT = ROOT / "outputs" / "20260910_aina_overflow_honorific"
DIALOGUE_SCOPES = {"scenario_map_script", "scenario_main", "battle_event_dialogue"}
PUNCT = set("！!？?…、。,．.・—–-～~;；:：)）]』」\"'")


def ko_lines(row: dict[str, Any]) -> list[str]:
    segments = [str(item) for item in (row.get("translation_segments") or []) if str(item)]
    if segments:
        return segments
    return [part for part in str(row.get("translation_ko") or "").split("\n") if part]


def end_class(text: str) -> str:
    if not text:
        return "empty"
    last = text[-1]
    if last in PUNCT:
        return "punct"
    if "가" <= last <= "힣":
        return "hangul"
    if last.isdigit() or last.isascii() and last.isalnum():
        return "alnum"
    return "other"


def measure_ss(path: Path) -> dict[str, Any]:
    img = Image.open(path).convert("RGB")
    pix = img.load()
    w, h = img.size
    # Yellow dialogue fill.
    yellow = [(x, y) for y in range(h) for x in range(w) if pix[x, y][0] > 180 and pix[x, y][1] > 160 and pix[x, y][2] < 90]
    xs = [p[0] for p in yellow]
    ys = [p[1] for p in yellow]
    box = {"x0": min(xs), "x1": max(xs), "y0": min(ys), "y1": max(ys)}
    # Prompt arrow: saturated yellow/orange, small, right side of box, lower half.
    arrows = []
    for y in range(box["y0"] + 20, min(h, box["y1"] + 3)):
        for x in range(box["x1"] - 20, min(w, box["x1"] + 8)):
            r, g, b = pix[x, y][:3]
            if r > 200 and 80 < g < 200 and b < 60:
                arrows.append((x, y))
    arrow = None
    if arrows:
        arrow = {
            "x0": min(p[0] for p in arrows),
            "x1": max(p[0] for p in arrows),
            "y0": min(p[1] for p in arrows),
            "y1": max(p[1] for p in arrows),
        }
    def dark_span(y0: int, y1: int) -> dict[str, int]:
        left, right, count = w, -1, 0
        for y in range(y0, y1):
            for x in range(box["x0"], min(w, box["x1"] + 1)):
                r, g, b = pix[x, y][:3]
                if r < 100 and g < 80 and b < 50:
                    left = min(left, x)
                    right = max(right, x)
                    count += 1
        return {"left": left if right >= 0 else -1, "right": right, "pixels": count}

    # Two text rows inside the yellow box; skip name plate (top ~16px).
    line1 = dark_span(box["y0"] + 16, box["y0"] + 32)
    line2 = dark_span(box["y0"] + 32, box["y1"] - 2)
    # Inner content right: green/brown frame is ~3-4px inside x1.
    inner_right = box["x1"] - 3
    origin = line2["left"] if line2["left"] >= 0 else line1["left"]
    cells = []
    if origin >= 0:
        for n in range(1, 17):
            glyph_left = origin + (n - 1) * 12
            glyph_right = origin + n * 12 - 1
            hit_arrow = False
            if arrow:
                hit_arrow = not (glyph_right < arrow["x0"] or glyph_left > arrow["x1"])
            cells.append(
                {
                    "n": n,
                    "x": [glyph_left, glyph_right],
                    "past_inner": max(0, glyph_right - inner_right),
                    "hits_arrow": hit_arrow,
                }
            )
    return {
        "size": [w, h],
        "box": box,
        "inner_right": inner_right,
        "arrow": arrow,
        "line1": line1,
        "line2": line2,
        "text_origin_x": origin,
        "line2_width_px": (line2["right"] - line2["left"] + 1) if line2["right"] >= 0 else 0,
        "line2_cells_drawn": round((line2["right"] - line2["left"] + 1) / 12, 2) if line2["right"] >= 0 else 0,
        "cells": cells,
    }


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    measured = {str(n): measure_ss(ROOT / f"SD Gundam GGeneration Advance (Korean).ss{n}") for n in range(1, 5)}
    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))

    buckets: Counter[str] = Counter()
    map_last15_hangul = []
    map_last15_punct = []
    map_first15 = []
    other15 = []
    for row in merged["records"]:
        if row.get("source_scope") not in DIALOGUE_SCOPES:
            continue
        if row.get("scope_status") == "alias":
            continue
        if row.get("translation_status") != "translated":
            continue
        lines = ko_lines(row)
        for index, line in enumerate(lines):
            if len(line) != 15:
                continue
            last = index == len(lines) - 1
            scope = str(row.get("source_scope"))
            kind = end_class(line)
            key = f"{scope}|{'last' if last else 'not_last'}|{kind}|lines{len(lines)}"
            buckets[key] += 1
            item = {
                "record_id": row["record_id"],
                "scope": scope,
                "line_index": index,
                "line_count": len(lines),
                "last": last,
                "end": kind,
                "line": line,
                "speaker_id": row.get("speaker_id"),
            }
            if scope == "scenario_map_script" and last and kind == "hangul":
                map_last15_hangul.append(item)
            elif scope == "scenario_map_script" and last and kind == "punct":
                map_last15_punct.append(item)
            elif scope == "scenario_map_script" and not last:
                map_first15.append(item)
            else:
                other15.append(item)

    summary = {
        "pixel": measured,
        "counts": {
            "all_15_dialogue_lines": sum(buckets.values()),
            "map_last_line_15_hangul": len(map_last15_hangul),
            "map_last_line_15_punct": len(map_last15_punct),
            "map_non_last_15": len(map_first15),
            "other_scopes_or_nonlast": len(other15),
        },
        "by_key": dict(sorted(buckets.items(), key=lambda kv: (-kv[1], kv[0]))),
        "map_last15_hangul_sample": map_last15_hangul[:25],
        "map_last15_hangul": map_last15_hangul,
        "map_last15_punct_sample": map_last15_punct[:15],
        "map_first15_sample": map_first15[:15],
    }
    path = OUT / "fifteen_cell_reality.json"
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    slim = {
        "pixel": {k: {kk: vv for kk, vv in v.items() if kk != "cells"} | {"cell15": next((c for c in v["cells"] if c["n"] == 15), None), "cell14": next((c for c in v["cells"] if c["n"] == 14), None)} for k, v in measured.items()},
        "counts": summary["counts"],
        "by_key": summary["by_key"],
        "map_last15_hangul_sample": summary["map_last15_hangul_sample"],
    }
    print(json.dumps(slim, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
