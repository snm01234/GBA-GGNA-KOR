"""Dump all profile-matrix selectors, including scroll-only cells."""
from __future__ import annotations

import json
import struct
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import analyze_ggen_advance_pending_decode as decode
import build_ggen_advance_ko_poc as fontops
import ggen_advance_painted_glyph_identity as glyph
from analyze_ggen_advance_ui_matrix_expansion import FIXED16_MATRIX, FIXED40_MATRIX
from analyze_ggen_allclear_profile_desc_20260912 import (
    ALLCLEAR,
    JP_ROM,
    KO_ROM,
    OUT,
    decode_stream,
    hangul_slot_map,
    u32,
)
from ggen_advance_text_codec import (
    DICT_12X12_BASE,
    DICT_12X12_END,
    DICT_8X16_BASE,
    DICT_8X16_END,
    expand_to_slots,
    load_dictionary,
)

ROM_BASE = 0x08000000


def all_cells(rom, spec, index, dictionary, slot_to_char):
    base = spec["base_file"] + index * spec["stride"]
    out = []
    for sel in range(spec["selector_count"]):
        src = base + sel * 4
        ptr = u32(rom, src)
        cell = decode_stream(rom, ptr, dictionary, slot_to_char)
        cell.update(selector=sel, owner=hex(src), rendered=sel in spec["rendered_selectors"])
        out.append(cell)
    return out


def classify(cell):
    if not cell.get("text"):
        return "empty"
    if cell.get("hangul") and not cell.get("jp_kana") and not cell.get("unresolved"):
        return "ko"
    if cell.get("hangul") and cell.get("jp_kana"):
        return "mixed"
    if cell.get("unresolved"):
        return "unresolved"
    return "jp"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    jp = JP_ROM.read_bytes()
    ko = KO_ROM.read_bytes()
    jp_map12 = decode.merge_maps([decode.DEFAULT_MAP12], apply_kana=True)
    jp_map8 = decode.merge_maps([decode.DEFAULT_MAP8], apply_kana=False)
    font12 = glyph.load_galmuri12()
    hangul12 = hangul_slot_map(ko, font12)
    ko_map12 = dict(jp_map12)
    ko_map12.update(hangul12)
    jp_d12 = load_dictionary(jp, DICT_12X12_BASE, DICT_12X12_END)
    ko_d12 = load_dictionary(ko, DICT_12X12_BASE, DICT_12X12_END)
    jp_d8 = load_dictionary(jp, DICT_8X16_BASE, DICT_8X16_END)

    aisha_jp = all_cells(jp, FIXED16_MATRIX, 0, jp_d12, jp_map12)
    aisha_ko = all_cells(ko, FIXED16_MATRIX, 0, ko_d12, ko_map12)

    unit_sel0 = []
    for i in range(FIXED40_MATRIX["count"]):
        cells = all_cells(jp, FIXED40_MATRIX, i, jp_d12, jp_map12)
        unit_sel0.append({"i": i, "sel0": cells[0]["text"], "nonempty": [c["text"] for c in cells if c["text"]]})
    argama_hits = [row for row in unit_sel0 if any("旗艦" in t or "巡洋艦" in t or t.startswith("エゥーゴの母") for t in row["nonempty"])]
    if not argama_hits:
        argama_hits = [row for row in unit_sel0 if any("グリプス戦争" in t or "ネル・アーガマ" in t for t in row["nonempty"])]

    extra_stats = {"char": Counter(), "unit": Counter()}
    for kind, spec in (("char", FIXED16_MATRIX), ("unit", FIXED40_MATRIX)):
        rendered = set(spec["rendered_selectors"])
        for i in range(spec["count"]):
            for cell in all_cells(ko, spec, i, ko_d12, ko_map12):
                if cell["selector"] in rendered:
                    continue
                extra_stats[kind][classify(cell)] += 1

    sel0_8x16 = []
    for i in (0,):
        pass
    # Decode unit selector 0 with both fonts for mixed cases.
    mixed_examples = []
    for i in range(FIXED40_MATRIX["count"]):
        src = FIXED40_MATRIX["base_file"] + i * FIXED40_MATRIX["stride"]
        ptr = u32(ko, src)
        c12 = decode_stream(ko, ptr, ko_d12, ko_map12)
        c8 = decode_stream(ko, ptr, jp_d8, jp_map8)
        if c12.get("hangul") and c12.get("jp_kana"):
            mixed_examples.append({"i": i, "as12": c12["text"], "as8": c8["text"]})
            if len(mixed_examples) >= 5:
                break

    report = {
        "aisha_jp": [{k: c[k] for k in ("selector", "owner", "ptr", "text", "hangul", "jp_kana")} for c in aisha_jp],
        "aisha_ko": [{k: c[k] for k in ("selector", "owner", "ptr", "text", "hangul", "jp_kana")} for c in aisha_ko],
        "argama_hits": argama_hits[:8],
        "extra_selector_stats": {k: dict(v) for k, v in extra_stats.items()},
        "unit_sel0_mixed_as_8x16": mixed_examples,
        "unit_sel0_samples": [row["sel0"] for row in unit_sel0[:20]],
    }
    if argama_hits:
        ai = argama_hits[0]["i"]
        report["argama_index"] = ai
        report["argama_jp"] = [{k: c[k] for k in ("selector", "owner", "ptr", "text")} for c in all_cells(jp, FIXED40_MATRIX, ai, jp_d12, jp_map12)]
        report["argama_ko"] = [{k: c[k] for k in ("selector", "owner", "ptr", "text", "hangul", "jp_kana")} for c in all_cells(ko, FIXED40_MATRIX, ai, ko_d12, ko_map12)]
    (OUT / "profile_desc_followup.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "aisha_jp_nonempty": [(c["selector"], c["text"]) for c in aisha_jp if c["text"]],
        "aisha_ko_nonempty": [(c["selector"], c["text"]) for c in aisha_ko if c["text"]],
        "argama_hits": [{"i": r["i"], "sel0": r["sel0"], "n": len(r["nonempty"])} for r in argama_hits[:8]],
        "extra_stats": report["extra_selector_stats"],
        "mixed_examples": mixed_examples[:3],
        "argama_jp_nonempty": [(c["selector"], c["text"]) for c in report.get("argama_jp", []) if c.get("text")],
        "argama_ko_nonempty": [(c["selector"], c["text"]) for c in report.get("argama_ko", []) if c.get("text")],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
