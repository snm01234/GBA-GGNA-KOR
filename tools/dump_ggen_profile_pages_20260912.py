"""Dump every character/unit profile page (empty selectors keep page breaks)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import analyze_ggen_advance_pending_decode as decode
from analyze_ggen_advance_ui_matrix_expansion import FIXED16_MATRIX, FIXED40_MATRIX
from analyze_ggen_allclear_profile_desc_20260912 import (
    CHAR_REC,
    CHAR_STRIDE,
    JP_ROM,
    KO_ROM,
    OUT,
    UNIT_REC,
    UNIT_STRIDE,
    decode_stream,
    hangul_slot_map,
    u32,
)
from analyze_ggen_allclear_profile_desc_followup_20260912 import all_cells, classify
import ggen_advance_painted_glyph_identity as glyph
from ggen_advance_text_codec import (
    DICT_12X12_BASE,
    DICT_12X12_END,
    DICT_8X16_BASE,
    DICT_8X16_END,
    load_dictionary,
)

ROM_BASE = 0x08000000


def pages_from_cells(cells):
    pages = []
    current = []
    for cell in cells:
        if cell.get("text"):
            current.append(cell)
        elif current:
            pages.append(current)
            current = []
    if current:
        pages.append(current)
    return pages


def name8(rom, table, stride, index, field, dictionary, slot_to_char):
    ptr = u32(rom, table + index * stride + field)
    return decode_stream(rom, ptr, dictionary, slot_to_char)["text"]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    jp = JP_ROM.read_bytes()
    ko = KO_ROM.read_bytes()
    jp_map12 = decode.merge_maps([decode.DEFAULT_MAP12], apply_kana=True)
    jp_map8 = decode.merge_maps([decode.DEFAULT_MAP8], apply_kana=False)
    hangul = hangul_slot_map(ko, glyph.load_galmuri12())
    ko_map12 = dict(jp_map12)
    ko_map12.update(hangul)
    jp_d12 = load_dictionary(jp, DICT_12X12_BASE, DICT_12X12_END)
    ko_d12 = load_dictionary(ko, DICT_12X12_BASE, DICT_12X12_END)
    jp_d8 = load_dictionary(jp, DICT_8X16_BASE, DICT_8X16_END)
    records = []
    need = {"sel0": 0, "scroll": 0, "ok": 0, "empty_profiles": 0}
    for kind, spec, table, stride, count in (
        ("char", FIXED16_MATRIX, CHAR_REC, CHAR_STRIDE, FIXED16_MATRIX["count"]),
        ("unit", FIXED40_MATRIX, UNIT_REC, UNIT_STRIDE, FIXED40_MATRIX["count"]),
    ):
        rendered = set(spec["rendered_selectors"])
        for i in range(count):
            jp_cells = all_cells(jp, spec, i, jp_d12, jp_map12)
            ko_cells = all_cells(ko, spec, i, ko_d12, ko_map12)
            name = name8(jp, table, stride, i, 0, jp_d8, jp_map8)
            pages = []
            for page in pages_from_cells(jp_cells):
                lines = []
                for cell in page:
                    ko_c = next(c for c in ko_cells if c["selector"] == cell["selector"])
                    status = classify(ko_c)
                    role = "sel0" if cell["selector"] == 0 else ("body" if cell["selector"] in rendered else "scroll")
                    if role == "sel0" and status != "ko":
                        need["sel0"] += 1
                    elif role == "scroll" and status != "ko":
                        need["scroll"] += 1
                    elif status == "ko":
                        need["ok"] += 1
                    lines.append({
                        "selector": cell["selector"],
                        "owner": cell["owner"],
                        "jp_ptr": cell["ptr"],
                        "ko_ptr": ko_c["ptr"],
                        "jp": cell["text"],
                        "ko_live": ko_c["text"],
                        "status": status,
                        "role": role,
                    })
                pages.append(lines)
            if not pages:
                need["empty_profiles"] += 1
            records.append({"kind": kind, "index": i, "name_jp": name, "pages": pages})
    payload = {"need": need, "n": len(records), "records": records}
    (OUT / "profile_pages_jp.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # compact work list for translation
    work = []
    for rec in records:
        for p_i, page in enumerate(rec["pages"]):
            if any(line["status"] != "ko" for line in page):
                work.append({
                    "kind": rec["kind"],
                    "index": rec["index"],
                    "name_jp": rec["name_jp"],
                    "page": p_i,
                    "jp": "".join(line["jp"] for line in page),
                    "lines": [{"selector": l["selector"], "owner": l["owner"], "jp": l["jp"], "role": l["role"], "status": l["status"]} for l in page],
                })
    (OUT / "profile_pages_need_ko.json").write_text(json.dumps({"n": len(work), "pages": work}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"need": need, "work_pages": len(work), "aisha": records[0]["pages"], "argama165": next(r for r in records if r["kind"]=="unit" and r["index"]==165)["pages"]}, ensure_ascii=False, indent=2)[:8000])


if __name__ == "__main__":
    main()
