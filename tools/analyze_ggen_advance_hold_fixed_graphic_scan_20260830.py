#!/usr/bin/env python3
"""Search raw/uncompressed 8x16 graphic payloads for the list-screen `持` shape.

The E0518 status atlas and the D54 clone hypothesis were both measured in-game,
but the left list badge did not change.  This scanner follows the battle
`実/攻/命/弾` lesson: the visible glyph may be sourced from an independent fixed
8x16 graphic payload rather than the atlas tilemap that resembles it.

We derive the dark-outline footprint from clean status resource[12] and scan
all 4-byte-aligned 64-byte windows in the clean ROM as possible vertical 8x16
4bpp payloads.  A candidate is ranked by the best single palette-index mask
against that measured outline.  Exact/near matches are then correlated with
ROM pointers and nearby descriptor-like data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import build_ggen_advance_status_ui_tile_overlay_poc as status  # noqa: E402
from analyze_ggen_advance_fixed_word_semantics_20260830 import parse_map, stitch, u32  # noqa: E402

ROM_BASE = 0x08000000
JP_ROM = ROOT / "SD Gundam GGeneration Advance (Japan).gba"
OUT = ROOT / "analysis" / "ggen_advance_hold_fixed_graphic_scan_20260830.json"
EXPECTED_JP_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"
STATUS_TABLE = 0x000E0518
STATUS_RESOURCE = 12
TARGET_OUTLINE_INDEX = 4
WINDOW_BYTES = 64
ALIGN = 4
TOP = 200
POINTER_REL_CANDIDATES = (0x00, 0x04, 0x08, 0x0C, 0x10, 0x14, 0x18, 0x20)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def active_clean_status(data: bytes) -> bytes:
    ptr = u32(data, STATUS_TABLE)
    gate(ptr == 0x080DC848, f"clean status pointer drift: 0x{ptr:08X}")
    off = ptr - ROM_BASE
    header = u32(data, off)
    gate(header & 0x80000000, "clean status atlas is not compressed")
    clen = header & 0xFFFF
    atlas = status.lzss_decompress(data[off + 4 : off + 4 + clen])
    gate(len(atlas) == status.ATLAS_EXPECTED_DECODED, f"status decoded size drift: {len(atlas)}")
    return atlas


def target_outline(data: bytes, atlas: bytes) -> tuple[list[int], list[list[int]]]:
    obj = parse_map(data, u32(data, STATUS_TABLE + STATUS_RESOURCE * 4))
    gate(obj is not None and (obj["width"], obj["height"]) == (1, 2), "status resource[12] drift")
    pixels = stitch(atlas, obj)
    indices = [y * 8 + x for y, row in enumerate(pixels) for x, value in enumerate(row) if value == TARGET_OUTLINE_INDEX]
    gate(len(indices) == 45, f"measured outline pixel count drift: {len(indices)}")
    return indices, pixels


def decode_payload(raw: bytes) -> list[int]:
    gate(len(raw) == WINDOW_BYTES, "8x16 payload length drift")
    pixels: list[int] = []
    for value in raw:
        pixels.append(value & 0x0F)
        pixels.append((value >> 4) & 0x0F)
    return pixels


def pointer_targets(data: bytes) -> set[int]:
    targets: set[int] = set()
    for offset in range(0, len(data) - 3, 2):
        value = struct.unpack_from("<I", data, offset)[0]
        if ROM_BASE <= value < ROM_BASE + len(data):
            targets.add(value - ROM_BASE)
    return targets


def pointer_hits(data: bytes, file_offset: int) -> list[str]:
    address = ROM_BASE + file_offset
    pattern = struct.pack("<I", address)
    hits: list[str] = []
    start = 0
    while True:
        pos = data.find(pattern, start)
        if pos < 0:
            break
        hits.append(f"0x{ROM_BASE + pos:08X}")
        start = pos + 1
    return hits


def nearby_words(data: bytes, offset: int, radius: int = 0x20) -> str:
    lo = max(0, offset - radius)
    hi = min(len(data), offset + WINDOW_BYTES + radius)
    return data[lo:hi].hex()


def scan(data: bytes, target_indices: list[int]) -> list[dict[str, Any]]:
    # The battle fixed-label resources are referenced by ROM pointers.  Instead
    # of brute-forcing every four-byte window, enumerate every valid ROM pointer
    # target and the small set of common inline-resource payload offsets.  This
    # covers direct graphic pointers and descriptor+0x14 layouts like
    # `実/攻/命/弾` while keeping the scan deterministic and fast.
    bases = pointer_targets(data)
    starts = {
        base + rel
        for base in bases
        for rel in POINTER_REL_CANDIDATES
        if 0 <= base + rel <= len(data) - WINDOW_BYTES
    }
    ranked: list[tuple[float, int, int, int, int]] = []
    for offset in starts:
        pixels = decode_payload(data[offset : offset + WINDOW_BYTES])
        best_value = 0
        best_inter = -1
        for value in range(16):
            inter = sum(1 for index in target_indices if pixels[index] == value)
            if inter > best_inter:
                best_inter = inter
                best_value = value
        if best_inter < 28:
            continue
        obs = pixels.count(best_value)
        score = 2.0 * best_inter / (len(target_indices) + obs) if obs else 0.0
        ranked.append((score, offset, best_value, best_inter, obs))

    ranked.sort(reverse=True)
    unique: list[dict[str, Any]] = []
    seen_offsets: set[int] = set()
    for score, offset, value, inter, obs in ranked:
        if offset in seen_offsets:
            continue
        seen_offsets.add(offset)
        unique.append({
            "score": score,
            "file_offset": f"0x{offset:08X}",
            "gba_address": f"0x{ROM_BASE + offset:08X}",
            "palette_index": value,
            "target_intersection": inter,
            "observed_pixels": obs,
            "pointer_hits_exact_payload_start": pointer_hits(data, offset),
            "pointer_hits_minus_0x14": pointer_hits(data, offset - 0x14) if offset >= 0x14 else [],
            "nearby_hex": nearby_words(data, offset),
        })
        if len(unique) >= TOP:
            break
    return unique


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rom", type=Path, default=JP_ROM)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    data = args.rom.read_bytes()
    gate(sha256(data) == EXPECTED_JP_SHA256, "Japanese ROM hash drift")
    atlas = active_clean_status(data)
    target_indices, target_pixels = target_outline(data, atlas)
    candidates = scan(data, target_indices)

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_hold_fixed_graphic_scan_20260830",
        "result": "PASS",
        "source": {"path": str(args.rom.relative_to(ROOT)), "sha256": sha256(data)},
        "target": {
            "status_resource": STATUS_RESOURCE,
            "outline_palette_index": TARGET_OUTLINE_INDEX,
            "outline_pixels": len(target_indices),
            "outline_flat_indices": target_indices,
            "pixel_rows": ["".join(format(v, "X") for v in row) for row in target_pixels],
        },
        "scan": {
            "window_bytes": WINDOW_BYTES,
            "alignment": ALIGN,
            "pointer_target_count": len(pointer_targets(data)),
            "pointer_relative_payload_offsets": [f"0x{x:X}" for x in POINTER_REL_CANDIDATES],
            "candidate_threshold_target_intersection": 28,
            "rank_metric": "Dice(target status-resource[12] outline, best single palette-index mask in raw 8x16 payload)",
            "top_count": len(candidates),
        },
        "candidates": candidates,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "out": str(args.out),
        "top": [
            {k: row[k] for k in ("score", "file_offset", "gba_address", "palette_index", "target_intersection", "observed_pixels", "pointer_hits_exact_payload_start", "pointer_hits_minus_0x14")}
            for row in candidates[:20]
        ],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
