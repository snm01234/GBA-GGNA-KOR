#!/usr/bin/env python3
"""Render Korean.ss4/ss6 and audit ID-command description widths."""
from __future__ import annotations

import json
import struct
import sys
from collections import Counter
from pathlib import Path

from PIL import Image

THIS = Path(__file__).resolve().parent
ROOT = THIS.parent
sys.path.insert(0, str(THIS))

import analyze_ggen_advance_jp_ko_ss1_n_tile_owned_count_20260903 as plaque
import analyze_ggen_advance_owned_count_ec0c_trace_runtime_20260904 as runtime
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
from ggen_advance_project_paths import ADVANCE_ROOT, TRANSLATION_MERGED_JSON

OUT = ROOT / "outputs" / "20260909_idcmd_desc_overflow"
PREVIEW = OUT / "previews"


def u16(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def visible_len(text: str) -> int:
    return len(text.replace("\n", ""))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    PREVIEW.mkdir(parents=True, exist_ok=True)

    states = {}
    for n in (4, 6):
        path = ROOT / f"SD Gundam GGeneration Advance (Korean).ss{n}"
        print(f"ss{n} exists={path.exists()} size={path.stat().st_size if path.exists() else 'missing'}")
        if not path.exists():
            continue
        st, _ = statefmt.parse_png_state(path)
        states[n] = st
        io = runtime.io_summary(st)
        print(f"ss{n} io={io}")
        img = runtime.composite(st)
        scaled = img.resize((240 * 4, 160 * 4), Image.Resampling.NEAREST)
        scaled.save(PREVIEW / f"ss{n}_composite.png")
        plaque.scale(plaque.composite_state(st), 4).save(PREVIEW / f"ss{n}_bg.png")
        runtime.render_obj(st).resize((240 * 4, 160 * 4), Image.Resampling.NEAREST).save(PREVIEW / f"ss{n}_obj.png")

    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    rows = [
        row
        for row in merged["records"]
        if row.get("semantic_category") == "id_command_description"
        and row.get("translation_status") == "translated"
    ]
    lengths = []
    for row in rows:
        ko = str(row.get("translation_ko") or "")
        jp = str(row.get("source_text") or "")
        lengths.append(
            {
                "record_id": row["record_id"],
                "jp": jp,
                "ko": ko,
                "jp_len": visible_len(jp),
                "ko_len": visible_len(ko),
                "delta": visible_len(ko) - visible_len(jp),
            }
        )
    lengths.sort(key=lambda item: (-item["ko_len"], -item["delta"], item["record_id"]))
    print("id_command_description count", len(rows))
    print("ko_len histogram", Counter(item["ko_len"] for item in lengths).most_common())
    print("jp_len histogram", Counter(item["jp_len"] for item in lengths).most_common())
    print("longest korean:")
    for item in lengths[:25]:
        print(f"  {item['ko_len']:2d} jp={item['jp_len']:2d} {item['record_id']} {item['ko']!r} <= {item['jp']!r}")
    (OUT / "idcmd_desc_lengths.json").write_text(
        json.dumps({"count": len(rows), "longest": lengths[:80]}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
