#!/usr/bin/env python3
"""Audit 8x16/12x12 glyph identity and 12x12 dialogue cell overflow on main TIP.

Glyph failures this week (ν→꺄, 핀→Ｖ) were the same class: a Hangul token
encoded for one font mode was drawn with the other font's cell.  Dialogue
clipping is a second class: portrait 12x12 boxes are 15 cells with no wrap.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import build_ggen_advance_ko_poc as fontops  # noqa: E402
import build_ggen_advance_unified_rom_poc as unified  # noqa: E402
from ggen_advance_painted_glyph_identity import (  # noqa: E402
    FONT8_RELOCATED,
    FONT12_RELOCATED,
    load_galmuri12,
    load_galmuri8,
    packed_12x12,
    packed_8x16,
    slot_raw,
)
from ggen_advance_project_paths import (  # noqa: E402
    MAIN_TIP_ROM,
    ORIGINAL_ROM,
    TRANSLATION_MERGED_JSON,
    advance_relative,
)
from patch_ggen_advance_map_script_inline_poc import MAX_DIALOGUE_CELLS  # noqa: E402

APPLY = ROOT / "analysis" / "ggen_advance_korean_apply_charmap_20260844.json"
OUT = ROOT / "analysis" / "ggen_advance_glyph_and_dialogue_fit_audit_20260905.json"
CUTIN = ROOT / "integrated" / "translation" / "ggen_advance_battle_cutin_quotes.json"
SPECIAL_12 = {
    0x010A: "Ｖ",
    0x0143: "ν",
    0x07DC: "∀",
    0x07DB: "γ",
}
PORTRAIT_SCOPES = {
    "scenario_main",
    "scenario_map_script",
    "id_command_battle_bark",
    "battle_event_dialogue",
    "battle_cutin_quote",
}


def visible_lines(row: dict[str, Any]) -> list[str]:
    segments = [str(item) for item in (row.get("translation_segments") or [])]
    if segments:
        return [item.replace("\n", "") for item in segments if item.strip()]
    text = str(row.get("translation_ko") or "")
    if not text.strip():
        return []
    return [part.replace("\n", "") for part in text.split("\n") if part.strip()]


def hangul_in(text: str) -> set[str]:
    return {char for char in text if "가" <= char <= "힣"}


def has_portrait(row: dict[str, Any]) -> bool:
    for control in row.get("control_signature") or []:
        if str(control.get("code") or "") in {"0x06", "6"} and int(control.get("argument") or 0):
            return True
    return str(row.get("source_scope") or "") in PORTRAIT_SCOPES


def painted_hangul_map(
    rom: bytes,
    *,
    base: int,
    stride: int,
    count: int,
    expected: dict[bytes, str],
) -> dict[int, str]:
    found: dict[int, str] = {}
    for slot in range(count):
        char = expected.get(slot_raw(rom, base, slot, stride))
        if char:
            found[slot] = char
    return found


def invert_unique(mapping: dict[int, str]) -> dict[str, list[int]]:
    out: dict[str, list[int]] = defaultdict(list)
    for slot, char in mapping.items():
        out[char].append(slot)
    return dict(out)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    rom = MAIN_TIP_ROM.read_bytes()
    japan = ORIGINAL_ROM.read_bytes()
    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    apply_map = json.loads(APPLY.read_text(encoding="utf-8"))
    font12 = load_galmuri12()
    font8 = load_galmuri8()

    apply_rows = [
        row
        for row in apply_map.get("assignments") or []
        if "가" <= str(row.get("char") or "") <= "힣"
    ]
    apply_chars = {str(row["char"]) for row in apply_rows}
    expected12 = {packed_12x12(char, font12): char for char in apply_chars}
    expected8 = {packed_8x16(char, font8): char for char in apply_chars}
    live12 = painted_hangul_map(
        rom, base=FONT12_RELOCATED, stride=fontops.FONT_12X12_STRIDE, count=fontops.FONT_12X12_COUNT, expected=expected12
    )
    live8 = painted_hangul_map(
        rom, base=FONT8_RELOCATED, stride=fontops.FONT_8X16_STRIDE, count=fontops.FONT_8X16_COUNT, expected=expected8
    )
    by_char12 = invert_unique(live12)
    by_char8 = invert_unique(live8)

    only8: list[str] = []
    only12: list[str] = []
    duplicate12: list[dict[str, Any]] = []
    duplicate8: list[dict[str, Any]] = []
    for char in sorted(apply_chars):
        slots12 = by_char12.get(char, [])
        slots8 = by_char8.get(char, [])
        if slots8 and not slots12:
            only8.append(char)
        if slots12 and not slots8:
            only12.append(char)
        if len(slots12) > 1:
            duplicate12.append({"char": char, "slots": [f"0x{slot:04X}" for slot in slots12]})
        if len(slots8) > 1:
            duplicate8.append({"char": char, "slots": [f"0x{slot:04X}" for slot in slots8]})

    specials = []
    for slot, name in SPECIAL_12.items():
        live = slot_raw(rom, FONT12_RELOCATED, slot, fontops.FONT_12X12_STRIDE)
        original = slot_raw(japan, fontops.FONT_12X12_BASE, slot, fontops.FONT_12X12_STRIDE)
        hangul = live12.get(slot)
        specials.append(
            {
                "slot": f"0x{slot:04X}",
                "intended": name,
                "matches_original_jp": live == original,
                "painted_hangul": hangul,
            }
        )

    metadata_drift = []
    for row in apply_rows:
        char = str(row["char"])
        slot = int(str(row["slot"]), 16)
        paint = str(row.get("paint") or "")
        if paint in {"both", "12x12", "split"} and live12.get(slot) not in {char, None}:
            metadata_drift.append(
                {
                    "char": char,
                    "metadata_slot": f"0x{slot:04X}",
                    "paint": paint,
                    "live_12x12": live12.get(slot),
                    "unique_12x12": [f"0x{item:04X}" for item in by_char12.get(char, [])],
                }
            )
        if paint in {"both", "8x16", "split"} and live8.get(slot) not in {char, None}:
            metadata_drift.append(
                {
                    "char": char,
                    "metadata_slot": f"0x{slot:04X}",
                    "paint": paint,
                    "live_8x16": live8.get(slot),
                    "unique_8x16": [f"0x{item:04X}" for item in by_char8.get(char, [])],
                }
            )

    twelve_ko_only8: dict[str, list[str]] = defaultdict(list)
    shared_alias_risk: list[dict[str, Any]] = []
    records = list(merged.get("records") or [])
    by_id = {str(row.get("record_id") or ""): row for row in records}
    for row in records:
        if str(row.get("translation_status") or "") != "translated":
            continue
        if row.get("scope_status") == "alias":
            alias_of = str(row.get("alias_of") or "")
            parent = by_id.get(alias_of)
            if (
                parent
                and unified.uses_12x12(row)
                and not unified.uses_12x12(parent)
                and hangul_in(str(parent.get("translation_ko") or "")) & set(only8)
            ):
                shared_alias_risk.append(
                    {
                        "record_id": row["record_id"],
                        "alias_of": alias_of,
                        "screen_class": row.get("screen_class"),
                        "parent_ko": parent.get("translation_ko"),
                        "eight_only_chars": sorted(hangul_in(str(parent.get("translation_ko") or "")) & set(only8)),
                    }
                )
            continue
        if not unified.uses_12x12(row):
            continue
        missing = sorted(hangul_in(str(row.get("translation_ko") or "")) & set(only8))
        if missing:
            twelve_ko_only8[row["record_id"]] = missing

    overflow: list[dict[str, Any]] = []
    redistributable = 0
    needs_rephrase = 0
    for row in records:
        if str(row.get("translation_status") or "") != "translated":
            continue
        if row.get("scope_status") == "alias":
            continue
        scope = str(row.get("source_scope") or "")
        if scope not in PORTRAIT_SCOPES:
            continue
        if str(row.get("screen_class") or "") in {"production_text", "fixed_ui"}:
            continue
        lines = visible_lines(row)
        if not lines:
            continue
        lengths = [len(line) for line in lines]
        if max(lengths) <= MAX_DIALOGUE_CELLS:
            continue
        portrait = has_portrait(row)
        spare = [MAX_DIALOGUE_CELLS - length for length in lengths]
        can_shift = False
        suggestion = None
        if len(lines) == 2 and (lengths[0] > MAX_DIALOGUE_CELLS) != (lengths[1] > MAX_DIALOGUE_CELLS):
            long_i = 0 if lengths[0] > MAX_DIALOGUE_CELLS else 1
            short_i = 1 - long_i
            words = lines[long_i].split(" ")
            if len(words) >= 2:
                moved = words[-1]
                kept = " ".join(words[:-1])
                trial = f"{moved} {lines[short_i]}" if short_i == 1 else f"{lines[short_i]} {moved}"
                if long_i == 0:
                    trial_lines = [kept, f"{moved} {lines[1]}".strip()]
                else:
                    trial_lines = [f"{lines[0]} {moved}".strip(), kept]
                if all(len(item) <= MAX_DIALOGUE_CELLS for item in trial_lines) and kept:
                    can_shift = True
                    suggestion = trial_lines
                    trial = trial_lines
        status = "redistribute" if can_shift else "rephrase"
        if can_shift:
            redistributable += 1
        else:
            needs_rephrase += 1
        overflow.append(
            {
                "record_id": row["record_id"],
                "source_scope": row.get("source_scope"),
                "screen_class": row.get("screen_class"),
                "portrait_box": portrait,
                "lines": lines,
                "cells": lengths,
                "overflow_by": [max(0, length - MAX_DIALOGUE_CELLS) for length in lengths],
                "spare": spare,
                "fix_class": status,
                "redistribute_to": suggestion,
            }
        )

    cutin_overflow = []
    if CUTIN.is_file():
        cutin = json.loads(CUTIN.read_text(encoding="utf-8"))
        grouped: dict[int, list[str]] = defaultdict(list)
        for row in cutin.get("records") or []:
            grouped[int(row.get("container_index") or -1)].append(str(row.get("translation_ko") or ""))
        for index, lines in grouped.items():
            visible = [line for line in lines if line.strip()]
            lengths = [len(line) for line in visible]
            if lengths and max(lengths) > MAX_DIALOGUE_CELLS:
                cutin_overflow.append(
                    {
                        "container_index": index,
                        "lines": visible,
                        "cells": lengths,
                    }
                )

    overflow.sort(key=lambda item: (-max(item["cells"]), item["record_id"]))
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_glyph_and_dialogue_fit_audit_20260905",
        "rom": advance_relative(MAIN_TIP_ROM),
        "max_dialogue_cells": MAX_DIALOGUE_CELLS,
        "glyph": {
            "apply_hangul_chars": len(apply_chars),
            "live_12x12_hangul_slots": len(live12),
            "live_8x16_hangul_slots": len(live8),
            "hangul_8x16_only": only8,
            "hangul_8x16_only_count": len(only8),
            "hangul_12x12_only_count": len(only12),
            "duplicate_12x12": duplicate12,
            "duplicate_8x16": duplicate8,
            "specials_12x12": specials,
            "apply_charmap_live_drift_count": len(metadata_drift),
            "apply_charmap_live_drift_sample": metadata_drift[:40],
            "translated_12x12_uses_8x16_only_hangul": len(twelve_ko_only8),
            "translated_12x12_uses_8x16_only_sample": [
                {"record_id": record_id, "chars": chars} for record_id, chars in list(twelve_ko_only8.items())[:30]
            ],
            "shared_8x16_payload_12x12_alias_risk": shared_alias_risk,
        },
        "dialogue": {
            "portrait_cell_limit": MAX_DIALOGUE_CELLS,
            "overlong_translated_records": len(overflow),
            "overlong_by_scope": dict(Counter(str(item["source_scope"]) for item in overflow)),
            "redistributable": redistributable,
            "needs_rephrase": needs_rephrase,
            "kamille_gravity": next(
                (item for item in overflow if item["record_id"] == "GGA-SCENARIO-001FC74C"),
                None,
            ),
            "worst": overflow[:40],
            "cutin_overlong_containers": cutin_overflow,
        },
        "policy": {
            "never_share_payload_across_font_modes": True,
            "encode_12x12_only_from_unique_painted_12x12": True,
            "protect_original_specials": ["ν", "∀", "γ", "Ｖ"],
            "portrait_dialogue_cells": MAX_DIALOGUE_CELLS,
            "prefer_redistribute_to_next_line": True,
            "do_not_fit_by_deleting_spaces_only": True,
            "rephrase_when_both_lines_would_overflow": True,
        },
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "result": "PASS",
                "report": advance_relative(OUT),
                "hangul_8x16_only": len(only8),
                "specials_ok": all(item["matches_original_jp"] and not item["painted_hangul"] for item in specials),
                "shared_alias_risk": len(shared_alias_risk),
                "translated_12x12_uses_8x16_only": len(twelve_ko_only8),
                "overlong": len(overflow),
                "redistributable": redistributable,
                "needs_rephrase": needs_rephrase,
                "kamille": report["dialogue"]["kamille_gravity"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
