"""Decode character/unit profile description matrices from allclear states."""
from __future__ import annotations

import json
import struct
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import analyze_ggen_advance_pending_decode as decode
import analyze_ggen_advance_unit_list_sprite_state_20260830 as sf
import build_ggen_advance_ko_poc as fontops
import ggen_advance_painted_glyph_identity as glyph
from analyze_ggen_advance_ui_matrix_expansion import FIXED16_MATRIX, FIXED40_MATRIX
from ggen_advance_text_codec import (
    DICT_12X12_BASE,
    DICT_12X12_END,
    ROM_BASE,
    expand_to_slots,
    load_dictionary,
    read_tokens,
)

OUT = ROOT / "outputs" / "20260912_allclear_profile_desc"
JP_ROM = ROOT / "SD Gundam GGeneration Advance (Japan).gba"
KO_ROM = ROOT / "SD Gundam GGeneration Advance (Korean).gba"
ALLCLEAR = ROOT / "SD Gundam GGeneration Advance (Korean)_allclear.gba"

CHAR_REC = 0x001ABF6C
CHAR_STRIDE = 0x10
UNIT_REC = 0x001AFB5C
UNIT_STRIDE = 0x28


def u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def decode_stream(rom: bytes, ptr: int, dictionary, slot_to_char: dict[int, str]) -> dict:
    if not (ROM_BASE <= ptr < ROM_BASE + len(rom)):
        return {"ptr": hex(ptr), "text": "", "slots": [], "raw_hex": "", "hangul": 0, "jp_kana": 0, "unresolved": []}
    off = ptr - ROM_BASE
    try:
        tokens, raw = read_tokens(rom, off)
        slots = expand_to_slots(tokens, dictionary)
    except (ValueError, IndexError) as exc:
        return {"ptr": hex(ptr), "off": hex(off), "text": f"<parse:{exc}>", "slots": [], "raw_hex": "", "hangul": 0, "jp_kana": 0, "unresolved": []}
    text = "".join(slot_to_char.get(s, f"<{s:04X}>") for s in slots)
    hangul = sum(1 for s in slots if "가" <= slot_to_char.get(s, "") <= "힣")
    jp_kana = sum(1 for s in slots if slot_to_char.get(s, "") and "ぁ" <= slot_to_char.get(s, "") <= "ヶ")
    return {
        "ptr": hex(ptr),
        "off": hex(off),
        "text": text,
        "n_slots": len(slots),
        "hangul": hangul,
        "jp_kana": jp_kana,
        "raw_hex": raw.hex(),
        "unresolved": [hex(s) for s in slots if s not in slot_to_char],
    }


def hangul_slot_map(rom: bytes, font) -> dict[int, str]:
    packer = glyph.packed_12x12
    by_glyph: dict[bytes, list[int]] = {}
    for slot in range(fontops.FONT_12X12_COUNT):
        raw = glyph.slot_raw(rom, glyph.FONT12_RELOCATED, slot, fontops.FONT_12X12_STRIDE)
        by_glyph.setdefault(raw, []).append(slot)
    out: dict[int, str] = {}
    for code in range(ord("가"), ord("힣") + 1):
        ch = chr(code)
        try:
            packed = packer(ch, font)
        except Exception:
            continue
        hits = by_glyph.get(packed, [])
        if len(hits) == 1:
            out[hits[0]] = ch
    return out


def matrix_row(rom: bytes, spec: dict, index: int, dictionary, slot_to_char):
    base = spec["base_file"] + index * spec["stride"]
    cells = []
    for sel in spec["rendered_selectors"]:
        src = base + sel * 4
        ptr = u32(rom, src)
        cell = decode_stream(rom, ptr, dictionary, slot_to_char)
        cell.update(selector=sel, owner=hex(src))
        cells.append(cell)
    return cells


def name_at(rom: bytes, table: int, stride: int, index: int, field: int, dictionary, slot_to_char) -> str:
    ptr = u32(rom, table + index * stride + field)
    return decode_stream(rom, ptr, dictionary, slot_to_char)["text"]


def iwram_rom_ptrs(state: bytes) -> list[int]:
    iwram = state[sf.STATE_IWRAM : sf.STATE_IWRAM + sf.IWRAM_SIZE]
    hits = []
    for off in range(0, len(iwram) - 3, 4):
        v = struct.unpack_from("<I", iwram, off)[0]
        if 0x08000000 <= v < 0x0A000000:
            hits.append(v)
    return hits


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(exist_ok=True)
    jp = JP_ROM.read_bytes()
    ko = KO_ROM.read_bytes()
    allclear_exists = ALLCLEAR.exists()
    ac = ALLCLEAR.read_bytes() if allclear_exists else None
    jp_map = decode.merge_maps([decode.DEFAULT_MAP12], apply_kana=True)
    font12 = glyph.load_galmuri12()
    hangul_map = hangul_slot_map(ko, font12)
    ko_map = dict(jp_map)
    ko_map.update(hangul_map)
    jp_dict = load_dictionary(jp, DICT_12X12_BASE, DICT_12X12_END)
    ko_dict = load_dictionary(ko, DICT_12X12_BASE, DICT_12X12_END)

    # Record +0 names are 8x16; profile bodies are 12x12. Identify samples from bodies.
    char_names = []
    for i in range(FIXED16_MATRIX["count"]):
        cells = matrix_row(jp, FIXED16_MATRIX, i, jp_dict, jp_map)
        char_names.append(cells[0]["text"][:20] if cells else "")
    unit_names = []
    for i in range(FIXED40_MATRIX["count"]):
        cells = matrix_row(jp, FIXED40_MATRIX, i, jp_dict, jp_map)
        unit_names.append(cells[0]["text"][:24] if cells else "")
    aisha_hits = [i for i, n in enumerate(char_names) if n.startswith("アンドリュー・バルトフェルド")]
    argama_hits = [i for i, n in enumerate(unit_names) if "旗艦" in n or n.startswith("エゥーゴの")]
    if not aisha_hits or not argama_hits:
        print(json.dumps({"char0_5": char_names[:8], "unit0_12": unit_names[:16], "aisha_hits": aisha_hits, "argama_hits": argama_hits}, ensure_ascii=False, indent=2))
        raise SystemExit("sample lookup failed")
    aisha_i = aisha_hits[0]
    argama_i = argama_hits[0]

    samples = {
        "aisha_index": aisha_i,
        "aisha_name_jp": char_names[aisha_i],
        "argama_index": argama_i,
        "argama_name_jp": unit_names[argama_i],
        "aisha_jp": matrix_row(jp, FIXED16_MATRIX, aisha_i, jp_dict, jp_map),
        "aisha_ko": matrix_row(ko, FIXED16_MATRIX, aisha_i, ko_dict, ko_map),
        "argama_jp": matrix_row(jp, FIXED40_MATRIX, argama_i, jp_dict, jp_map),
        "argama_ko": matrix_row(ko, FIXED40_MATRIX, argama_i, ko_dict, ko_map),
    }
    if ac is not None:
        ac_dict = load_dictionary(ac, DICT_12X12_BASE, DICT_12X12_END)
        ac_map = dict(jp_map)
        ac_map.update(hangul_slot_map(ac, font12))
        samples["aisha_allclear"] = matrix_row(ac, FIXED16_MATRIX, aisha_i, ac_dict, ac_map)
        samples["argama_allclear"] = matrix_row(ac, FIXED40_MATRIX, argama_i, ac_dict, ac_map)

    def classify_cell(cell: dict) -> str:
        if not cell.get("text"):
            return "empty"
        if cell.get("hangul") and not cell.get("jp_kana") and not cell.get("unresolved"):
            return "ko"
        if cell.get("hangul") and cell.get("jp_kana"):
            return "mixed"
        if cell.get("unresolved"):
            return "unresolved"
        if cell.get("jp_kana") or cell.get("text"):
            return "jp"
        return "other"

    stats = {"char": Counter(), "unit": Counter(), "char_sel0": Counter(), "unit_sel0": Counter(), "char_later": Counter(), "unit_later": Counter()}
    inventory = []
    for kind, spec, count in (("char", FIXED16_MATRIX, FIXED16_MATRIX["count"]), ("unit", FIXED40_MATRIX, FIXED40_MATRIX["count"])):
        names = char_names if kind == "char" else unit_names
        for i in range(count):
            jp_cells = matrix_row(jp, spec, i, jp_dict, jp_map)
            ko_cells = matrix_row(ko, spec, i, ko_dict, ko_map)
            row = {"kind": kind, "index": i, "name_jp": names[i], "cells": []}
            for jp_c, ko_c in zip(jp_cells, ko_cells):
                status = classify_cell(ko_c)
                same_ptr = jp_c["ptr"] == ko_c["ptr"]
                item = {
                    "selector": jp_c["selector"],
                    "owner": jp_c["owner"],
                    "jp": jp_c["text"],
                    "ko": ko_c["text"],
                    "jp_ptr": jp_c["ptr"],
                    "ko_ptr": ko_c["ptr"],
                    "same_ptr": same_ptr,
                    "status": status,
                    "ko_hangul": ko_c["hangul"],
                    "ko_jp_kana": ko_c["jp_kana"],
                }
                row["cells"].append(item)
                stats[kind][status] += 1
                bucket = f"{kind}_sel0" if jp_c["selector"] == 0 else f"{kind}_later"
                stats[bucket][status] += 1
            inventory.append(row)

    states = {}
    for n in range(1, 5):
        path = ROOT / f"SD Gundam GGeneration Advance (Korean)_allclear.ss{n}"
        st, _ = sf.parse_png_state(path)
        ptrs = set(iwram_rom_ptrs(st))
        owners = []
        for spec in (FIXED16_MATRIX, FIXED40_MATRIX):
            for i in range(spec["count"]):
                base = spec["base_file"] + i * spec["stride"]
                for sel in spec["rendered_selectors"]:
                    src = base + sel * 4
                    ptr = u32(ko, src)
                    if ptr in ptrs:
                        owners.append({"owner": hex(src), "ptr": hex(ptr), "family": spec["family"], "index": i, "selector": sel})
        states[f"ss{n}"] = {"matching_matrix_owners": owners, "n_rom_ptrs": len(ptrs)}

    report = {
        "hangul_glyphs_painted_12x12": len(hangul_map),
        "samples": samples,
        "stats": {k: dict(v) for k, v in stats.items()},
        "states": states,
        "allclear_exists": allclear_exists,
        "ko_size": len(ko),
        "jp_size": len(jp),
    }
    (OUT / "profile_desc_analysis.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "profile_desc_inventory.json").write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "hangul_glyphs": len(hangul_map),
        "aisha": aisha_i,
        "argama": argama_i,
        "stats": report["stats"],
        "ss_hits": {k: len(v["matching_matrix_owners"]) for k, v in states.items()},
        "aisha_jp": [c["text"] for c in samples["aisha_jp"]],
        "aisha_ko": [c["text"] for c in samples["aisha_ko"]],
        "argama_jp": [c["text"] for c in samples["argama_jp"]],
        "argama_ko": [c["text"] for c in samples["argama_ko"]],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
