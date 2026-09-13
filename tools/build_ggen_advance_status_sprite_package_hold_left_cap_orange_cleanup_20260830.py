#!/usr/bin/env python3
"""Replace the dark inner pixels of the C5A5DC hold cap with orange."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import build_ggen_advance_status_sprite_package_hold_left_cap_20260830 as prior


ROOT = Path(__file__).resolve().parent.parent
MAIN_TIP = ROOT / "SD Gundam GGeneration Advance (Korean).gba"
MAIN_MANIFEST = ROOT / "integrated" / "main_tip" / "ggen_advance_main_tip_manifest.json"
OUT_DIR = ROOT / "outputs" / "20260830_ggen_advance_status_badges"
DEFAULT_OUT = OUT_DIR / "ggen_advance_status_sprite_package_hold_left_cap_orange_candidate_20260830.gba"
DEFAULT_MANIFEST = ROOT / "analysis" / "ggen_advance_status_sprite_package_hold_left_cap_orange_20260830.json"
DEFAULT_PREVIEW = OUT_DIR / "ggen_advance_status_sprite_package_hold_left_cap_orange_preview_20260830.png"

EXPECTED_MAIN_SHA256 = "05ca6b22e153856e614020d22b5399151b5a2fc286bdf128aec58c670a3e1f0f"
DARK_CAP_INDICES = {4, 5}
ORANGE_INDEX = 7
EXPECTED_BEFORE = prior.EXPECTED_AFTER


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def build_after(rows: tuple[str, ...]) -> tuple[tuple[str, ...], list[list[int]]]:
    result: list[str] = []
    changed_pixels: list[list[int]] = []
    for y, row in enumerate(rows):
        values = [int(ch, 16) for ch in row]
        # The rounded cap occupies x=6..7.  Only its inner x=7 column contains
        # the unwanted dark HP-derived pixels; the Korean cell begins at x=8.
        if values[7] in DARK_CAP_INDICES:
            values[7] = ORANGE_INDEX
            changed_pixels.append([7, y])
        result.append("".join(f"{value:X}" for value in values))
    return tuple(result), changed_pixels


EXPECTED_AFTER, EXPECTED_CHANGED_PIXELS = build_after(EXPECTED_BEFORE)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=MAIN_TIP)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--preview", type=Path, default=DEFAULT_PREVIEW)
    args = parser.parse_args()

    source = args.input.read_bytes()
    prior.gate(len(source) == 32 * 1024 * 1024, "input must be a 32 MiB ROM")
    prior.gate(sha256(source) == EXPECTED_MAIN_SHA256, f"Main TIP hash drift: {sha256(source)}")
    approved = json.loads(MAIN_MANIFEST.read_text(encoding="utf-8"))
    prior.gate(approved.get("status") == "approved_main_tip", "Main TIP is not approved")
    prior.gate(approved.get("sha256") == EXPECTED_MAIN_SHA256, "Main TIP manifest hash drift")

    before = prior.rows_for(source)
    prior.gate(before == EXPECTED_BEFORE, f"live cap canvas drift: {before}")
    after, changed_pixels = build_after(before)
    prior.gate(after == EXPECTED_AFTER, "orange cleanup output drift")
    prior.gate(changed_pixels == EXPECTED_CHANGED_PIXELS, "dark cap pixel set drift")
    prior.gate(len(changed_pixels) == 13, f"expected 13 dark cap pixels, got {len(changed_pixels)}")

    candidate = bytearray(source)
    prior.put_left_tile(candidate, after)
    prior.gate(prior.rows_for(candidate) == after, "patched canvas did not round-trip")
    prior.gate(tuple(row[8:] for row in after) == tuple(row[8:] for row in before), "Korean glyph cell changed")
    prior.gate(all(after[y][:7] == before[y][:7] for y in range(16)), "pixels outside inner cap column changed")

    changed = [i for i, (old, new) in enumerate(zip(source, candidate)) if old != new]
    prior.gate(changed, "orange cleanup made no byte changes")
    prior.gate(all(prior.LEFT_TOP <= i < prior.LEFT_TOP + prior.TILE_BYTES or
                   prior.LEFT_BOTTOM <= i < prior.LEFT_BOTTOM + prior.TILE_BYTES for i in changed),
               "orange cleanup escaped adjacent cap tiles")

    output = bytes(candidate)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(output)
    prior.make_preview(before, after, args.preview)
    manifest = {
        "schema_version": 1,
        "kind": "ggen_advance_status_sprite_package_hold_left_cap_orange_20260830",
        "result": "PASS",
        "source": {"path": str(args.input.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256(source)},
        "output": {"path": str(args.out.relative_to(ROOT)).replace("\\", "/"), "size": len(output),
                   "sha256": sha256(output), "preview": str(args.preview.relative_to(ROOT)).replace("\\", "/")},
        "patch": {"target": "C5A5DC hold badge inner left-cap column",
                  "method": "replace dark/gray palette indices 4 and 5 with adjacent orange index 7",
                  "changed_pixels": changed_pixels, "changed_bytes": len(changed),
                  "changed_ranges": prior.changed_ranges(changed)},
        "verification": {"result": "PASS", "parent_main_tip_hash_verified": True,
                         "all_dark_inner_cap_pixels_replaced": True, "orange_index": ORANGE_INDEX,
                         "korean_glyph_cell_preserved": True, "outer_cap_column_preserved": True,
                         "changes_restricted_to_two_adjacent_tiles": True, "palette_modified": False},
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "out": str(args.out), "sha256": sha256(output),
                      "manifest": str(args.manifest), "preview": str(args.preview),
                      "changed_pixels": len(changed_pixels), "changed_bytes": len(changed)},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
