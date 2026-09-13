#!/usr/bin/env python3
"""Render the ss1-ss3 source submenu OBJ rows for pixel-level inspection."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import analyze_ggen_advance_intermission_submenu_states_20260830 as submenu
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
import build_ggen_advance_intermission_submenu_ko_test_20260830 as builder


def main() -> int:
    states = [statefmt.parse_png_state(path)[0] for path in submenu.STATES]
    rows = []
    for state_number, state in enumerate(states, 1):
        for row_index, text in enumerate(builder.TARGETS[state_number]):
            canvas, _, palette = builder.extract_row(state, row_index)
            rows.append({"state": state_number, "row": row_index, "text": text,
                         "palette": palette, "canvas": canvas})
    out = ROOT / "outputs" / "20260830_ggen_advance_intermission_menu" / "ggen_advance_intermission_submenu_source_preview_20260830.png"
    builder.make_preview(rows, states, out)
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
