#!/usr/bin/env python3
"""Locate the 40x16 回避 forecast badge and related graphic cells.

The source proof is the native 240x160 forecast capture already preserved in
``analysis/_tmp_forecast_base.png``.  The badge occupies five by two screen
tiles at (32,112).  Individual screen tiles are compared against every tile in
the game's custom-LZSS graphic streams by palette-independent NMI; this also
works when a resource uses a non-sequential map.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

from PIL import Image

import analyze_ggen_advance_action_graphics_scan_20260830 as scan
from ggen_advance_project_paths import ADVANCE_ROOT, MAIN_TIP_MANIFEST, MAIN_TIP_ROM


JP_ROM = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Japan).gba"
CAPTURE = ADVANCE_ROOT / "analysis/_tmp_forecast_base.png"
OUT = ADVANCE_ROOT / "legacy/analysis/ggen_advance_battle_forecast_evade_graphics_20260831.json"
RECT = (32, 112, 40, 16)
EXPECTED_JP_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def quantized_tile(image: Image.Image) -> list[int]:
    q = image.convert("RGB").quantize(
        colors=16, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE
    )
    return [int(value) for value in q.getdata()]


def custom_streams(rom: bytes) -> tuple[list[dict], int]:
    rows = []
    tested = 0
    for off in range(0, len(rom) - 8, 4):
        header = struct.unpack_from("<I", rom, off)[0]
        if (header & 0xFFFF0000) != 0x80000000:
            continue
        body_len = header & 0xFFFF
        if body_len < 16 or off + 4 + body_len > len(rom):
            continue
        tested += 1
        try:
            decoded = scan.lzss_decompress(rom[off + 4 : off + 4 + body_len])
        except (ValueError, IndexError):
            continue
        if len(decoded) < 32 or len(decoded) % 32 or len(decoded) // 32 > 4096:
            continue
        rows.append({"offset": off, "body_len": body_len, "decoded": decoded})
    return rows, tested


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--jp", type=Path, default=JP_ROM)
    ap.add_argument("--main", type=Path, default=MAIN_TIP_ROM)
    ap.add_argument("--capture", type=Path, default=CAPTURE)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    jp = args.jp.read_bytes()
    main_rom = args.main.read_bytes()
    manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(jp) == EXPECTED_JP_SHA256, "Japanese ROM identity drift")
    gate(len(main_rom) == 32 * 1024 * 1024, "main TIP is not 32 MiB")
    gate(sha256(main_rom) == manifest["sha256"], "main TIP/manifest hash mismatch")

    screen = Image.open(args.capture).convert("RGB")
    gate(screen.size == (240, 160), f"capture is not native GBA size: {screen.size}")
    x0, y0, width, height = RECT
    crop = screen.crop((x0, y0, x0 + width, y0 + height))
    targets = []
    for ty in range(height // 8):
        for tx in range(width // 8):
            targets.append(quantized_tile(crop.crop((tx * 8, ty * 8, tx * 8 + 8, ty * 8 + 8))))

    streams, tested = custom_streams(jp)
    per_resource = []
    for stream in streams:
        decoded = stream["decoded"]
        tiles = [scan.decode_tile(decoded, tile) for tile in range(len(decoded) // 32)]
        target_rows = []
        for screen_tile, target in enumerate(targets):
            ranked = sorted(
                ((scan.nmi(tile, target), tile_id) for tile_id, tile in enumerate(tiles)),
                reverse=True,
            )[:4]
            target_rows.append(
                {
                    "screen_tile": screen_tile,
                    "best": [
                        {"tile_id": tile_id, "nmi": round(score, 9)}
                        for score, tile_id in ranked
                    ],
                }
            )
        score = sum(row["best"][0]["nmi"] for row in target_rows) / len(target_rows)
        minimum = min(row["best"][0]["nmi"] for row in target_rows)
        per_resource.append(
            {
                "resource_file_offset": f"0x{stream['offset']:08X}",
                "compressed_body_length": stream["body_len"],
                "decoded_size": len(decoded),
                "decoded_tiles": len(tiles),
                "mean_best_tile_nmi": round(score, 9),
                "minimum_best_tile_nmi": round(minimum, 9),
                "screen_tiles": target_rows,
            }
        )
    per_resource.sort(key=lambda row: (row["mean_best_tile_nmi"], row["minimum_best_tile_nmi"]), reverse=True)

    preview = args.out.with_name(args.out.stem + "_crop.png")
    preview.parent.mkdir(parents=True, exist_ok=True)
    crop.resize((width * 10, height * 10), Image.Resampling.NEAREST).save(preview)
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_battle_forecast_evade_graphics_static_analysis",
        "result": "INCONCLUSIVE_SCREENSHOT_RANKING",
        "main_tip": {"path": args.main.name, "sha256": sha256(main_rom), "manifest_exact": True},
        "source": {"path": args.jp.name, "sha256": sha256(jp)},
        "capture": {"path": str(args.capture.relative_to(ADVANCE_ROOT)), "rect": list(RECT), "tiles": [5, 2]},
        "custom_lzss": {"tested_headers": tested, "accepted_streams": len(streams)},
        "resource_ranking": per_resource[:12],
        "preview": str(preview.relative_to(ADVANCE_ROOT)),
        "superseded_by": "legacy/analysis/ggen_advance_battle_forecast_evade_ko_20260831.json",
        "note": "Screen-color similarity does not establish ownership. The BtlCmd label-pointer/command-pointer table is the source-of-truth proof.",
    }
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "INCONCLUSIVE_SCREENSHOT_RANKING",
        "out": str(args.out),
        "best_resources": [
            (row["resource_file_offset"], row["mean_best_tile_nmi"], row["minimum_best_tile_nmi"])
            for row in per_resource[:5]
        ],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
