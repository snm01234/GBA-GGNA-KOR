"""Dump live names/series/profile lines for followup4 issues."""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import analyze_ggen_advance_pending_decode as decode
import build_ggen_advance_ko_poc as fontops
import ggen_advance_painted_glyph_identity as glyph
from analyze_ggen_advance_ui_matrix_expansion import FIXED16_MATRIX, FIXED40_SECONDARY
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

    print("=== CHAR +0 / +12 interesting ===")
    needles = ("NT", "라이조", "カッシュ", "カジマ", "카지마", "リリー", "릴리", "アムロ", "아무로")
    for i in range(FIXED16_MATRIX["count"]):
        base = CHAR_REC + i * CHAR_STRIDE
        t0, _ = dec(ko, u32(ko, base), d8, m8)
        t12, _ = dec(ko, u32(ko, base + 12), d8, m8)
        j0, _ = dec(jp, u32(jp, base), d8j, jp8)
        blob = t0 + t12 + j0
        if any(n in blob for n in needles) or t12.endswith("11") or t12.endswith("22") or t12.endswith("33"):
            print(i, "jp0", j0, "| ko0", t0, "| ko12", t12)

    print("=== series 21 ===")
    print(dec(ko, u32(ko, 0x1B4D3C), d8, m8)[0])

    print("=== amuro7 sel0-5 ===")
    base = FIXED16_MATRIX["base_file"] + 7 * FIXED16_MATRIX["stride"]
    for sel in range(8):
        t = dec(ko, u32(ko, base + sel * 4), d12, m12)[0]
        if t:
            print(sel, len(t), t)

    print("=== secondary unit names of interest ===")
    keys = ("07E8", "0126", "00EC", "턴에이", "ν", "∀", "백식", "빌고", "비르고", "하이곡", "하이고", "루주", "루즈", "비건", "헤비", "V건담", "V대시", "아가마", "말레렌", "마를렌")
    hits = []
    for i in range(FIXED40_SECONDARY["count"]):
        owner = FIXED40_SECONDARY["base_file"] + i * FIXED40_SECONDARY["stride"] + FIXED40_SECONDARY["field_offset"]
        text, slots = dec(ko, u32(ko, owner), d8, m8)
        jp_t, _ = dec(jp, u32(jp, owner), d8j, jp8)
        if any(k in text or k in jp_t for k in keys):
            hits.append((i, hex(owner), text, jp_t, [hex(s) for s in slots if s in (0x07E8, 0x0126, 0x00EC, 0x07DC, 0x0143, 0x06FC, 0x07FB, 0x07F8, 0x07FE)]))
    for row in hits:
        print(row)

    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    print("=== sheet counts ===")
    for needle in ("하이곡", "라이조 캐시", "유 카지마", "네일 아가마", "말레렌", "루주", "빌고", "기렌 자비", "파이로럿", "턴에이 건담"):
        n = sum(1 for r in merged["records"] if needle in str(r.get("translation_ko") or ""))
        print(needle, n)


if __name__ == "__main__":
    main()
