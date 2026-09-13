#!/usr/bin/env python3
"""Measure ss4/ss6 ID-command description box and unique overflow strings."""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

from PIL import Image

THIS = Path(__file__).resolve().parent
ROOT = THIS.parent
sys.path.insert(0, str(THIS))

from ggen_advance_project_paths import TRANSLATION_MERGED_JSON

OUT = ROOT / "outputs" / "20260909_idcmd_desc_overflow"


def visible_len(text: str) -> int:
    return len(text.replace("\n", ""))


def scan_yellow(path: Path) -> dict:
    im = Image.open(path).convert("RGB")
    w, h = im.size
    # composites are 4x
    scale = 4
    # find yellow-ish box pixels
    yellow = []
    for y in range(h):
        for x in range(w):
            r, g, b = im.getpixel((x, y))
            if r > 180 and g > 150 and b < 80:
                yellow.append((x, y))
    if not yellow:
        return {"path": str(path), "yellow": 0}
    xs = [p[0] for p in yellow]
    ys = [p[1] for p in yellow]
    box = {
        "x0": min(xs) // scale,
        "y0": min(ys) // scale,
        "x1": (max(xs) + 1) // scale,
        "y1": (max(ys) + 1) // scale,
    }
    box["width"] = box["x1"] - box["x0"]
    box["height"] = box["y1"] - box["y0"]
    box["cells_12"] = box["width"] // 12
    return {"path": path.name, "native": box, "yellow_px": len(yellow)}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    for n in (4, 6):
        print(scan_yellow(OUT / "previews" / f"ss{n}_composite.png"))
        im = Image.open(OUT / "previews" / f"ss{n}_composite.png")
        # crop bottom text band native-ish
        band = im.crop((0, 128 * 4, 240 * 4, 160 * 4))
        band.save(OUT / "previews" / f"ss{n}_desc_band.png")

    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    uniq = defaultdict(list)
    for row in merged["records"]:
        if row.get("semantic_category") != "id_command_description":
            continue
        if row.get("translation_status") != "translated":
            continue
        ko = str(row.get("translation_ko") or "")
        jp = str(row.get("source_text") or "")
        if visible_len(ko) <= 17:
            continue
        uniq[(jp, ko)].append(row["record_id"])
    items = [
        {
            "jp": jp,
            "ko": ko,
            "jp_len": visible_len(jp),
            "ko_len": visible_len(ko),
            "count": len(ids),
            "sample": ids[0],
        }
        for (jp, ko), ids in uniq.items()
    ]
    items.sort(key=lambda item: (-item["ko_len"], item["jp"]))
    print("unique overflow >17:", len(items), "records", sum(i["count"] for i in items))
    for item in items:
        print(f"{item['ko_len']:2d}/{item['jp_len']:2d} x{item['count']:3d} {item['ko']!r} <= {item['jp']!r}")
    (OUT / "unique_overflow.json").write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
