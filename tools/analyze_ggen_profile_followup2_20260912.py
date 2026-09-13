"""Find leftover profile lines, untranslated series titles, and clipped empty-group text."""
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
from analyze_ggen_allclear_profile_desc_20260912 import decode_stream, hangul_slot_map, u32
from analyze_ggen_allclear_profile_desc_followup_20260912 import all_cells, classify
from ggen_advance_project_paths import MAIN_TIP_ROM, ORIGINAL_ROM, TRANSLATION_MERGED_JSON
from ggen_advance_text_codec import (
    DICT_12X12_BASE,
    DICT_12X12_END,
    DICT_8X16_BASE,
    DICT_8X16_END,
    ROM_BASE,
    expand_to_slots,
    load_dictionary,
    read_tokens,
)

OUT = ROOT / "outputs" / "20260912_allclear_profile_followup2"
CHAR_REC = 0x001ABF6C
CHAR_STRIDE = 0x10


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(exist_ok=True)
    jp = ORIGINAL_ROM.read_bytes()
    ko = MAIN_TIP_ROM.read_bytes()
    jp_map12 = decode.merge_maps([decode.DEFAULT_MAP12], apply_kana=True)
    jp_map8 = decode.merge_maps([decode.DEFAULT_MAP8], apply_kana=False)
    hangul12 = hangul_slot_map(ko, glyph.load_galmuri12())
    ko_map12 = dict(jp_map12)
    ko_map12.update(hangul12)
    jp_d12 = load_dictionary(jp, DICT_12X12_BASE, DICT_12X12_END)
    ko_d12 = load_dictionary(ko, DICT_12X12_BASE, DICT_12X12_END)
    jp_d8 = load_dictionary(jp, DICT_8X16_BASE, DICT_8X16_END)
    ko_d8 = load_dictionary(ko, DICT_8X16_BASE, DICT_8X16_END)

    leftover = []
    kept_ko = 0
    for kind, spec in (("char", FIXED16_MATRIX), ("unit", FIXED40_MATRIX)):
        for i in range(spec["count"]):
            jp_cells = all_cells(jp, spec, i, jp_d12, jp_map12)
            ko_cells = all_cells(ko, spec, i, ko_d12, ko_map12)
            for jc, kc in zip(jp_cells, ko_cells):
                if not jc["text"]:
                    continue
                same = jc["ptr"] == kc["ptr"]
                status = classify(kc)
                # Genuine Korean was relocated away from the JP stream.
                if (not same) and status == "ko":
                    kept_ko += 1
                    continue
                leftover.append({
                    "kind": kind,
                    "index": i,
                    "selector": jc["selector"],
                    "owner": jc["owner"],
                    "jp": jc["text"],
                    "ko_live": kc["text"],
                    "same_ptr": same,
                    "status": status,
                    "jp_ptr": jc["ptr"],
                    "ko_ptr": kc["ptr"],
                })
    (OUT / "leftover_matrix.json").write_text(json.dumps({"kept_ko": kept_ko, "n": len(leftover), "rows": leftover}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    amuro = [r for r in leftover if r["kind"] == "char" and r["index"] == 7]
    print("leftover", len(leftover), "kept_ko", kept_ko, "amuro_left", len(amuro))
    print("amuro leftover", json.dumps(amuro, ensure_ascii=False, indent=2))

    # Character record extra pointers (series etc.)
    recs = []
    for i in range(137):
        base = CHAR_REC + i * CHAR_STRIDE
        fields = {off: u32(jp, base + off) for off in (0, 4, 8, 12)}
        recs.append({"i": i, "fields": {hex(k): hex(v) for k, v in fields.items()}})
    kamura = recs[9]
    print("kamura record", json.dumps(kamura, ensure_ascii=False))
    for off, ptr in [(0, u32(jp, CHAR_REC + 9 * CHAR_STRIDE)), (4, u32(jp, CHAR_REC + 9 * CHAR_STRIDE + 4)), (8, u32(jp, CHAR_REC + 9 * CHAR_STRIDE + 8)), (12, u32(jp, CHAR_REC + 9 * CHAR_STRIDE + 12))]:
        if ROM_BASE <= ptr < ROM_BASE + len(jp):
            print(" field", off, "jp8", decode_stream(jp, ptr, jp_d8, jp_map8)["text"], "jp12", decode_stream(jp, ptr, jp_d12, jp_map12)["text"])
            kptr = u32(ko, CHAR_REC + 9 * CHAR_STRIDE + off)
            print("  ko8", decode_stream(ko, kptr, ko_d8, jp_map8)["text"], "ptr", hex(kptr))

    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    series = []
    for row in merged["records"]:
        if row.get("semantic_category") != "series_title":
            continue
        off = int(row["target_file_offset"], 16)
        jp_t = decode_stream(jp, ROM_BASE + off, jp_d8, jp_map8)["text"]
        # live pointer from first owner if present
        owners = row.get("owner_ids") or []
        live = None
        if owners:
            own = int(str(owners[0]).split("-")[-1], 16)
            live = u32(ko, own) if 0 <= own < len(ko) - 3 else None
        live_t = decode_stream(ko, live, ko_d8, jp_map8)["text"] if live else ""
        series.append({
            "record_id": row["record_id"],
            "jp_seed": row.get("source_text"),
            "jp8": jp_t,
            "ko_sheet": row.get("translation_ko") or "",
            "status": row.get("translation_status"),
            "live8": live_t,
            "owner": owners[0] if owners else "",
        })
    still_jp = [s for s in series if s["jp8"] and not any("가" <= c <= "힣" for c in (s["live8"] or s["ko_sheet"]))]
    print("series_title", len(series), "still_jpish", len(still_jp))
    for s in still_jp:
        print(" ", s["record_id"], s["jp8"], "| sheet", s["ko_sheet"], "| live", s["live8"])

    # empty group
    empty_src = 0x1BE7A3
    print("empty jp8", decode_stream(jp, ROM_BASE + empty_src, jp_d8, jp_map8)["text"])
    hits = []
    needle = struct.pack("<I", ROM_BASE + empty_src)
    p = jp.find(needle)
    while p >= 0:
        hits.append(p)
        p = jp.find(needle, p + 1)
    print("empty owners jp", [hex(h) for h in hits])
    for h in hits:
        kptr = u32(ko, h)
        print(" live", hex(h), hex(kptr), decode_stream(ko, kptr, ko_d8, jp_map8)["text"])
    man = json.loads((ROOT / "outputs/20260912_allclear_profiles_ko/manifest.json").read_text(encoding="utf-8"))
    empty_rows = [t for t in man["texts"] if t.get("kind") == "empty_group"]
    print("manifest empty", empty_rows)


if __name__ == "__main__":
    main()
