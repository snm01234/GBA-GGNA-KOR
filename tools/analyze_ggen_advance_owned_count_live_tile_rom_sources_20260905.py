#!/usr/bin/env python3
"""Reverse-search live 所有数 glyph-bearing BG2 tiles in the Japanese ROM."""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_jp_ko_ss1_n_tile_owned_count_20260903 as owned
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
from ggen_advance_project_paths import ADVANCE_ROOT, ORIGINAL_ROM, advance_relative

JP_STATE = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Japan).ss1"
OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_owned_count_live_tile_rom_sources_20260905.json"
TEXT_TILES = [221, 222, 223, 224, 225, 228, 229, 230, 231, 232]
ROM_BASE = 0x08000000


def find_all(data: bytes, needle: bytes) -> list[int]:
    out = []
    pos = 0
    while True:
        pos = data.find(needle, pos)
        if pos < 0:
            return out
        out.append(pos)
        pos += 1


def main() -> int:
    rom = ORIGINAL_ROM.read_bytes()
    state, _ = statefmt.parse_png_state(JP_STATE)
    rows = []
    all_hits = defaultdict(list)
    payloads = {}
    for tile in TEXT_TILES:
        raw = owned.bg_tile_bytes(state, 2, tile)
        payloads[tile] = raw
        hits = find_all(rom, raw)
        for off in hits:
            all_hits[off].append(tile)
        rows.append({
            "live_tile": tile,
            "hit_count": len(hits),
            "rom_hits": [f"0x{ROM_BASE + off:08X}" for off in hits[:256]],
            "file_offsets": [f"0x{off:08X}" for off in hits[:256]],
        })

    # Search two 5-tile row payloads both tightly packed and with common plausible 32-byte gaps.
    row_top = b"".join(payloads[t] for t in TEXT_TILES[:5])
    row_bottom = b"".join(payloads[t] for t in TEXT_TILES[5:])
    seq_top = find_all(rom, row_top)
    seq_bottom = find_all(rom, row_bottom)

    # Cluster individual hits by 0x400-byte windows to expose resource/source neighborhoods.
    clusters = defaultdict(list)
    for off, tiles in all_hits.items():
        clusters[off // 0x400].append((off, tiles))
    cluster_rows = []
    for key, items in clusters.items():
        unique_tiles = sorted({t for _off, ts in items for t in ts})
        cluster_rows.append({
            "window_start": f"0x{key * 0x400:08X}",
            "window_address": f"0x{ROM_BASE + key * 0x400:08X}",
            "unique_text_tiles": unique_tiles,
            "unique_text_tile_count": len(unique_tiles),
            "hits": [
                {"offset": f"0x{off:08X}", "address": f"0x{ROM_BASE + off:08X}", "tiles": ts}
                for off, ts in sorted(items)
            ],
        })
    cluster_rows.sort(key=lambda row: row["unique_text_tile_count"], reverse=True)

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_owned_count_live_tile_rom_sources_20260905",
        "result": "PASS",
        "source": {"rom": advance_relative(ORIGINAL_ROM), "state": advance_relative(JP_STATE)},
        "text_live_tiles": TEXT_TILES,
        "per_tile": rows,
        "packed_row_top_hits": [f"0x{ROM_BASE + off:08X}" for off in seq_top],
        "packed_row_bottom_hits": [f"0x{ROM_BASE + off:08X}" for off in seq_bottom],
        "clusters": cluster_rows[:100],
        "conclusion": (
            "A high-coverage ROM cluster identifies the direct source candidate."
            if cluster_rows and cluster_rows[0]["unique_text_tile_count"] >= 6 else
            "No high-coverage byte-exact raw ROM source; producer likely composes glyph tiles at runtime."
        ),
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "out": advance_relative(OUT),
        "per_tile_hit_counts": {str(row["live_tile"]): row["hit_count"] for row in rows},
        "packed_top": report["packed_row_top_hits"],
        "packed_bottom": report["packed_row_bottom_hits"],
        "top_clusters": cluster_rows[:20],
        "conclusion": report["conclusion"],
    }, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
