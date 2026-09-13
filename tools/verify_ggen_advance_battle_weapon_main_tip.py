#!/usr/bin/env python3
"""Verify that the approved main TIP contains the battle forecast mini-label patch.

The weapon forecast rows are composed at runtime from eight fixed 8x16 graphic
resources.  This verifier guards against testing a stale emulator session or
accidentally promoting a later candidate that drops those resource payloads.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from build_ggen_advance_battle_weapon_fixed_graphics_galmuri7_poc import (
    GRAPHIC_BYTES,
    GRAPHIC_REL,
    LABELS,
    PALETTE_REL,
)
import analyze_ggen_advance_battle_forecast_raw_cells as raw_analysis
import build_ggen_advance_battle_forecast_runtime_rows_galmuri7 as forecast
from ggen_advance_project_paths import ADVANCE_ROOT, MAIN_TIP_MANIFEST, MAIN_TIP_ROM

JP_ROM = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Japan).gba"
PATCHED_REFERENCE = (
    ADVANCE_ROOT
    / "outputs"
    / "20260829_ggen_advance_battle_ui"
    / "ggen_advance_battle_weapon_fixed_graphics_galmuri7_shadowfix_candidate_20260830.gba"
)
FORECAST_PATCHED_REFERENCE = (
    ADVANCE_ROOT
    / "outputs"
    / "20260830_ggen_advance_battle_forecast_ui"
    / "ggen_advance_battle_forecast_runtime_rows_galmuri7_candidate_20260830.gba"
)
DEFAULT_OUT = (
    ADVANCE_ROOT
    / "analysis"
    / "ggen_advance_battle_weapon_main_tip_verification_20260830.json"
)


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--main", type=Path, default=MAIN_TIP_ROM)
    parser.add_argument("--manifest", type=Path, default=MAIN_TIP_MANIFEST)
    parser.add_argument("--jp", type=Path, default=JP_ROM)
    parser.add_argument("--reference", type=Path, default=PATCHED_REFERENCE)
    parser.add_argument("--forecast-reference", type=Path, default=FORECAST_PATCHED_REFERENCE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    main_rom = args.main.read_bytes()
    jp_rom = args.jp.read_bytes()
    reference = args.reference.read_bytes()
    forecast_reference = args.forecast_reference.read_bytes()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))

    gate(len(main_rom) == 32 * 1024 * 1024, "main TIP is not 32 MiB")
    gate(len(jp_rom) == 16 * 1024 * 1024, "Japanese ROM is not 16 MiB")
    gate(len(reference) == len(main_rom), "patched reference size differs from main TIP")
    gate(len(forecast_reference) == len(main_rom), "forecast patched reference size differs from main TIP")
    gate(manifest.get("status") == "approved_main_tip", "main TIP manifest is not approved")
    gate(manifest.get("sha256") == sha256(main_rom), "main TIP hash differs from its manifest")

    resources = []
    for translation, spec in LABELS.items():
        offset = int(spec["offset"])
        graphic_start = offset + GRAPHIC_REL
        graphic_end = graphic_start + GRAPHIC_BYTES
        palette_end = offset + 0x74

        main_graphic = main_rom[graphic_start:graphic_end]
        jp_graphic = jp_rom[graphic_start:graphic_end]
        reference_graphic = reference[graphic_start:graphic_end]
        gate(main_graphic == reference_graphic, f"patched payload missing: {spec['source']} -> {translation}")
        gate(main_graphic != jp_graphic, f"Japanese payload still present: {spec['source']}")
        gate(main_rom[offset:graphic_start] == jp_rom[offset:graphic_start], f"resource header changed: {spec['source']}")
        gate(main_rom[offset + PALETTE_REL:palette_end] == jp_rom[offset + PALETTE_REL:palette_end], f"resource palette changed: {spec['source']}")
        resources.append(
            {
                "source": spec["source"],
                "translation": translation,
                "role": spec["role"],
                "graphic_file_offset": f"0x{graphic_start:08X}",
                "payload_sha256": sha256(main_graphic),
                "matches_shadowfix_reference": True,
                "differs_from_japanese": True,
                "header_unchanged": True,
                "palette_unchanged": True,
            }
        )

    runtime_rows = []
    for family, labels in forecast.ROW_CELLS.items():
        for translation, (top, bottom, mode) in labels.items():
            payload = main_rom[top : top + 32] + main_rom[bottom : bottom + 32]
            reference_payload = forecast_reference[top : top + 32] + forecast_reference[bottom : bottom + 32]
            jp_payload = jp_rom[top : top + 32] + jp_rom[bottom : bottom + 32]
            gate(payload == reference_payload, f"runtime forecast row patch missing: {family}/{translation}")
            gate(payload != jp_payload, f"Japanese runtime forecast row remains: {family}/{translation}")
            runtime_rows.append(
                {
                    "family": family,
                    "translation": translation,
                    "mode": mode,
                    "top_file_offset": f"0x{top:08X}",
                    "bottom_file_offset": f"0x{bottom:08X}",
                    "payload_sha256": sha256(payload),
                    "matches_runtime_reference": True,
                    "differs_from_japanese": True,
                }
            )

    raw_resources = []
    for source, translation, top_tile_id, bottom_tile_id, role in raw_analysis.LABELS:
        top = raw_analysis.GRAPHICS_OFFSET + top_tile_id * raw_analysis.TILE_BYTES
        bottom = raw_analysis.GRAPHICS_OFFSET + bottom_tile_id * raw_analysis.TILE_BYTES
        payload = main_rom[top : top + 32] + main_rom[bottom : bottom + 32]
        reference_payload = forecast_reference[top : top + 32] + forecast_reference[bottom : bottom + 32]
        jp_payload = jp_rom[top : top + 32] + jp_rom[bottom : bottom + 32]
        gate(payload == reference_payload, f"raw forecast payload missing: {source} -> {translation}")
        gate(payload != jp_payload, f"Japanese raw forecast payload still present: {source}")
        raw_resources.append(
            {
                "source": source,
                "translation": translation,
                "role": role,
                "top_tile_id": top_tile_id,
                "bottom_tile_id": bottom_tile_id,
                "top_graphic_file_offset": f"0x{top:08X}",
                "bottom_graphic_file_offset": f"0x{bottom:08X}",
                "payload_sha256": sha256(payload),
                "matches_forecast_reference": True,
                "differs_from_japanese": True,
            }
        )

    gate(
        main_rom[raw_analysis.RESOURCE_OFFSET : raw_analysis.GRAPHICS_OFFSET]
        == jp_rom[raw_analysis.RESOURCE_OFFSET : raw_analysis.GRAPHICS_OFFSET],
        "forecast sprite header/frame tables changed",
    )
    gate(
        main_rom[raw_analysis.PALETTE_OFFSET : raw_analysis.PALETTE_OFFSET + 0x60]
        == jp_rom[raw_analysis.PALETTE_OFFSET : raw_analysis.PALETTE_OFFSET + 0x60],
        "forecast sprite palette changed",
    )

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_battle_weapon_main_tip_verification",
        "result": "PASS",
        "main_tip": {
            "path": str(args.main.relative_to(ADVANCE_ROOT)),
            "sha256": sha256(main_rom),
            "manifest_hash_matches": True,
        },
        "runtime_scope": {
            "battle_row_compositor": "0x08039B28",
            "forecast_bg2_base_resource": "0x08A85FB4 via 0x0803860C; draw 0x0803860E -> 0x08001C50",
            "forecast_sprite_resource": "0x08A8C004",
            "labels": "approved fixed descriptors + live BG2 forecast row sources + corrected interleaved raw-cell matrix",
        },
        "fixed_descriptor_resources": resources,
        "forecast_runtime_row_resources": runtime_rows,
        "forecast_raw_cell_resources": raw_resources,
        "verification": {
            "translated_fixed_resources_present": len(resources),
            "translated_runtime_row_cells_present": len(runtime_rows),
            "translated_raw_resources_present": len(raw_resources),
            "all_eight_match_shadowfix_reference": True,
            "all_runtime_rows_match_forecast_reference": True,
            "all_eight_raw_pairs_match_forecast_reference": True,
            "all_eight_differ_from_japanese": True,
            "all_runtime_rows_differ_from_japanese": True,
            "all_eight_raw_pairs_differ_from_japanese": True,
            "all_headers_and_palettes_unchanged": True,
            "forecast_resource_header_frame_tables_and_palette_unchanged": True,
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
