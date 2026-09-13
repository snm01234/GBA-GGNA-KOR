"""Break down matrix aliases and selector-0 live encoding."""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from ggen_advance_project_paths import TRANSLATION_MERGED_JSON
from analyze_ggen_advance_ui_matrix_expansion import FIXED16_MATRIX, FIXED40_MATRIX
from analyze_ggen_allclear_profile_desc_20260912 import JP_ROM, KO_ROM, decode_stream, hangul_slot_map, u32
import analyze_ggen_advance_pending_decode as decode
import ggen_advance_painted_glyph_identity as glyph
from ggen_advance_text_codec import DICT_12X12_BASE, DICT_12X12_END, load_dictionary

OUT = ROOT / "outputs" / "20260912_allclear_profile_desc"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    by_sel = defaultdict(lambda: Counter())
    alias_of = defaultdict(list)
    aisha0 = None
    unit0s = []
    for row in merged["records"]:
        family = row.get("ui_family") or (row.get("source_families") or [None])[0]
        if family not in ("fixed16_option_matrix", "fixed40_option_matrix"):
            continue
        selector = row.get("selector")
        by_sel[f"{family}:sel{selector}"][row.get("translation_status")] += 1
        if row.get("translation_status") == "alias":
            alias_of[f"{family}:sel{selector}"].append({"index": row.get("record_index"), "alias_of": row.get("alias_of"), "target": row.get("target_file_offset")})
        if family == "fixed16_option_matrix" and row.get("record_index") == 0:
            if aisha0 is None or selector == 0:
                if selector == 0:
                    aisha0 = {k: row.get(k) for k in ("record_id", "translation_status", "translation_ko", "alias_of", "source_text", "target_file_offset", "selector", "owner_ids")}
        if family == "fixed40_option_matrix" and selector == 0 and len(unit0s) < 6:
            unit0s.append({k: row.get(k) for k in ("record_id", "record_index", "translation_status", "translation_ko", "alias_of", "source_text", "target_file_offset")})
    print("status by selector:")
    print(json.dumps({k: dict(v) for k, v in sorted(by_sel.items())}, ensure_ascii=False, indent=2))
    print("alias counts by selector:")
    print(json.dumps({k: len(v) for k, v in sorted(alias_of.items())}, ensure_ascii=False, indent=2))
    print("aisha sel0 sheet:")
    print(json.dumps(aisha0, ensure_ascii=False, indent=2))
    print("unit sel0 sheet samples:")
    print(json.dumps(unit0s, ensure_ascii=False, indent=2))

    jp = JP_ROM.read_bytes()
    ko = KO_ROM.read_bytes()
    jp_map = decode.merge_maps([decode.DEFAULT_MAP12], apply_kana=True)
    hangul = hangul_slot_map(ko, glyph.load_galmuri12())
    ko_map = dict(jp_map); ko_map.update(hangul)
    jp_d = load_dictionary(jp, DICT_12X12_BASE, DICT_12X12_END)
    ko_d = load_dictionary(ko, DICT_12X12_BASE, DICT_12X12_END)
    # Find Argama by searching all unit lines for ブライト or カラバ
    hits = []
    for i in range(FIXED40_MATRIX["count"]):
        base = FIXED40_MATRIX["base_file"] + i * FIXED40_MATRIX["stride"]
        texts = []
        for sel in range(FIXED40_MATRIX["selector_count"]):
            ptr = u32(jp, base + sel * 4)
            t = decode_stream(jp, ptr, jp_d, jp_map)["text"]
            if t:
                texts.append((sel, t))
        blob = "".join(t for _s, t in texts)
        if "ブライト" in blob or "カラバ" in blob or "ネル・アーガマ" in blob or "旗" in blob:
            hits.append({"i": i, "texts": texts})
    print("argama-like units:", json.dumps(hits, ensure_ascii=False, indent=2)[:4000])
    (OUT / "sheet_alias_and_argama.json").write_text(json.dumps({"aisha0": aisha0, "unit0s": unit0s, "hits": hits}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
