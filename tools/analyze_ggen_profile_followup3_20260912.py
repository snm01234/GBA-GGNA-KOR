"""Count leftover 8x16 profile bodies, pending names, and literal reserved tags."""
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
from analyze_ggen_advance_ui_matrix_expansion import FIXED16_MATRIX, FIXED40_MATRIX, FIXED40_SECONDARY
from ggen_advance_project_paths import MAIN_TIP_ROM, ORIGINAL_ROM, TRANSLATION_MERGED_JSON
from ggen_advance_text_codec import (
    DICT_8X16_BASE,
    DICT_8X16_END,
    DICT_12X12_BASE,
    DICT_12X12_END,
    ROM_BASE,
    expand_to_slots,
    load_dictionary,
    read_tokens,
)

CHAR_REC = 0x001ABF6C
CHAR_STRIDE = 0x10
OUT = ROOT / "outputs" / "20260912_allclear_profile_followup3"


def u32(data, off):
    return struct.unpack_from("<I", data, off)[0]


def hangul_map(rom, mode):
    if mode == 8:
        relocated, stride, count, packer, font = (
            glyph.FONT8_RELOCATED,
            fontops.FONT_8X16_STRIDE,
            fontops.FONT_8X16_COUNT,
            glyph.packed_8x16,
            glyph.load_galmuri8(),
        )
    else:
        relocated, stride, count, packer, font = (
            glyph.FONT12_RELOCATED,
            fontops.FONT_12X12_STRIDE,
            fontops.FONT_12X12_COUNT,
            glyph.packed_12x12,
            glyph.load_galmuri12(),
        )
    by = {}
    for slot in range(count):
        by.setdefault(glyph.slot_raw(rom, relocated, slot, stride), []).append(slot)
    out = {}
    for code in range(ord("가"), ord("힣") + 1):
        ch = chr(code)
        try:
            packed = packer(ch, font)
        except Exception:
            continue
        hits = by.get(packed, [])
        if len(hits) == 1:
            out[hits[0]] = ch
    return out


def dec(rom, ptr, dictionary, slot_to_char):
    if not (ROM_BASE <= ptr < ROM_BASE + len(rom)):
        return "", []
    try:
        tokens, raw = read_tokens(rom, ptr - ROM_BASE)
        slots = expand_to_slots(tokens, dictionary)
    except Exception:
        return "", []
    return "".join(slot_to_char.get(s, f"<{s:04X}>") for s in slots), slots


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    ko = MAIN_TIP_ROM.read_bytes()
    jp = ORIGINAL_ROM.read_bytes()
    jp8 = decode.merge_maps([decode.DEFAULT_MAP8], apply_kana=False)
    jp12 = decode.merge_maps([decode.DEFAULT_MAP12], apply_kana=True)
    h8 = hangul_map(ko, 8)
    h12 = hangul_map(ko, 12)
    m8 = dict(jp8)
    m8.update(h8)
    m12 = dict(jp12)
    m12.update(h12)
    d8 = load_dictionary(ko, DICT_8X16_BASE, DICT_8X16_END)
    d12 = load_dictionary(ko, DICT_12X12_BASE, DICT_12X12_END)
    d8j = load_dictionary(jp, DICT_8X16_BASE, DICT_8X16_END)

    leftover = []
    buckets = Counter()
    for kind, spec in (("char", FIXED16_MATRIX), ("unit", FIXED40_MATRIX)):
        for i in range(spec["count"]):
            base = spec["base_file"] + i * spec["stride"]
            for sel in range(spec["selector_count"]):
                owner = base + sel * 4
                ptr = u32(ko, owner)
                if ptr == 0:
                    continue
                t12, slots = dec(ko, ptr, d12, m12)
                t8, _ = dec(ko, ptr, d8, m8)
                if not t12 and not t8:
                    continue
                hangul12 = sum(1 for c in t12 if "가" <= c <= "힣")
                hangul8 = sum(1 for c in t8 if "가" <= c <= "힣")
                jp_kana12 = sum(1 for c in t12 if "ぁ" <= c <= "ヶ" or "一" <= c <= "龠")
                in_12cave = 0x09118000 <= ptr < 0x09230000
                in_8cave = 0x09000000 <= ptr < 0x09118000
                in_jp = 0x08000000 <= ptr < 0x09000000
                if in_12cave:
                    kind_b = "already_12"
                elif in_8cave and hangul8:
                    kind_b = "need_12_from_8"
                elif in_jp and (jp_kana12 or hangul12 == 0):
                    kind_b = "still_jp"
                elif hangul8 > hangul12:
                    kind_b = "need_12_from_8"
                else:
                    kind_b = "other"
                buckets[kind_b] += 1
                if kind_b in ("need_12_from_8", "still_jp"):
                    leftover.append(
                        {
                            "kind": kind,
                            "index": i,
                            "selector": sel,
                            "owner": hex(owner),
                            "ptr": hex(ptr),
                            "bucket": kind_b,
                            "t12": t12,
                            "t8": t8,
                            "n12": len(t8) if kind_b == "need_12_from_8" else len(t12),
                        }
                    )

    # character primary names
    names = []
    pending_jp = []
    for i in range(FIXED16_MATRIX["count"]):
        owner = CHAR_REC + i * CHAR_STRIDE
        ptr = u32(ko, owner)
        t8, slots = dec(ko, ptr, d8, m8)
        tj, _ = dec(jp, u32(jp, owner), d8j, jp8)
        kana = sum(1 for c in t8 if "ぁ" <= c <= "ヶ" or "ァ" <= c <= "ヶ")
        names.append({"i": i, "owner": hex(owner), "live": t8, "jp": tj, "ptr": hex(ptr)})
        if kana:
            pending_jp.append(names[-1])

    # secondary unit names with reserved tags or hex dumps
    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    tag_rows = []
    for row in merged["records"]:
        ko_text = str(row.get("translation_ko") or "")
        if any(tag in ko_text for tag in ("<07F8>", "<07FB>", "<07FC>", "<07FD>", "<07FE>")):
            owners = [int(x.split("-")[-1], 16) for x in (row.get("owner_ids") or []) if str(x).startswith("OWNER-U32-")]
            live = []
            for own in owners:
                ptr = u32(ko, own)
                text, slots = dec(ko, ptr, d8, m8)
                live.append({"owner": hex(own), "ptr": hex(ptr), "text": text, "has_07fd": 0x07FD in slots})
            tag_rows.append(
                {
                    "id": row["record_id"],
                    "cat": row.get("semantic_category"),
                    "family": (row.get("source_families") or [None])[0],
                    "sheet": ko_text,
                    "src": row.get("source_text"),
                    "live": live,
                }
            )

    # live secondary table dump around Gaza C
    secondary = []
    for i in range(FIXED40_SECONDARY["count"]):
        owner = FIXED40_SECONDARY["base_file"] + i * FIXED40_SECONDARY["stride"] + FIXED40_SECONDARY["field_offset"]
        ptr = u32(ko, owner)
        text, slots = dec(ko, ptr, d8, m8)
        if "07FD" in text or "07FE" in text or "(" in text and "가자" in text:
            secondary.append({"i": i, "owner": hex(owner), "ptr": hex(ptr), "text": text, "slots": [hex(s) for s in slots]})

    report = {
        "buckets": dict(buckets),
        "leftover_n": len(leftover),
        "leftover_over18": sum(1 for row in leftover if row["n12"] > 18),
        "pending_names": pending_jp,
        "tag_rows_n": len(tag_rows),
        "tag_rows": tag_rows,
        "secondary_hexdump": secondary[:30],
        "kira35": names[35] if len(names) > 35 else None,
        "mirai103_leftover": [row for row in leftover if row["kind"] == "char" and row["index"] == 103],
        "kira35_leftover": [row for row in leftover if row["kind"] == "char" and row["index"] == 35],
    }
    (OUT / "analysis.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "leftover_matrix.json").write_text(json.dumps(leftover, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "buckets": dict(buckets),
                "leftover_n": len(leftover),
                "over18": report["leftover_over18"],
                "pending_names": pending_jp,
                "tag_rows_n": len(tag_rows),
                "tag_live_samples": [row["live"] for row in tag_rows[:8]],
                "secondary_n": len(secondary),
                "secondary": secondary[:12],
                "kira35": names[35],
                "kira35_lines": report["kira35_leftover"],
                "mirai_lines": report["mirai103_leftover"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
