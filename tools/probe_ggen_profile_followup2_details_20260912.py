"""Probe series lookup, 음 glyph, and ss3 empty-group tiles."""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import analyze_ggen_advance_pending_decode as decode
import analyze_ggen_advance_unit_list_sprite_state_20260830 as sf
import build_ggen_advance_ko_poc as fontops
import ggen_advance_painted_glyph_identity as glyph
from ggen_advance_project_paths import MAIN_TIP_ROM, ORIGINAL_ROM, TRANSLATION_MERGED_JSON
from ggen_advance_text_codec import (
    DICT_8X16_BASE,
    DICT_8X16_END,
    ROM_BASE,
    expand_to_slots,
    load_dictionary,
    read_tokens,
)

def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]

def decode8(rom, ptr, d, m):
    if not (ROM_BASE <= ptr < ROM_BASE + len(rom)):
        return ""
    tokens, raw = read_tokens(rom, ptr - ROM_BASE)
    slots = expand_to_slots(tokens, d)
    return "".join(m.get(s, f"<{s:04X}>") for s in slots), slots, raw

def hangul8(rom, font):
    packer = glyph.packed_8x16
    by = {}
    for slot in range(fontops.FONT_8X16_COUNT):
        by.setdefault(glyph.slot_raw(rom, glyph.FONT8_RELOCATED, slot, fontops.FONT_8X16_STRIDE), []).append(slot)
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
    return out, by

def main():
    sys.stdout.reconfigure(encoding="utf-8")
    jp = ORIGINAL_ROM.read_bytes()
    ko = MAIN_TIP_ROM.read_bytes()
    font8 = glyph.load_galmuri8()
    h8, by_glyph = hangul8(ko, font8)
    print("hangul8 count", len(h8), "음" in h8.values(), [hex(s) for s,c in h8.items() if c=="음"], [hex(s) for s,c in h8.items() if c=="없"])
    wanted = glyph.packed_8x16("음", font8)
    print("음 hits", [hex(s) for s in by_glyph.get(wanted, [])])
    wanted2 = glyph.packed_8x16("없", font8)
    print("없 hits", [hex(s) for s in by_glyph.get(wanted2, [])])
    jp_map8 = decode.merge_maps([decode.DEFAULT_MAP8], apply_kana=False)
    m8 = dict(jp_map8); m8.update(h8)
    d8 = load_dictionary(ko, DICT_8X16_BASE, DICT_8X16_END)
    d8j = load_dictionary(jp, DICT_8X16_BASE, DICT_8X16_END)
    text, slots, raw = decode8(ko, 0x091148CF, d8, m8)
    print("empty live", text, [hex(s) for s in slots], raw.hex())
    # ss3 tiles around the empty message
    st,_=sf.parse_png_state(ROOT/"SD Gundam GGeneration Advance (Korean)_allclear.ss3")
    import analyze_ggen_advance_intermission_cycle_states_20260830 as bg
    info=bg.bg_info(st,0)
    print("bg0", info)
    rows=[]
    for y in range(20):
        line=[]
        for x in range(30):
            e=bg.map_entry(st[0x1000:0x19000], info["screen_base"], info["size"], x, y)
            line.append(hex(e))
        rows.append(line)
    # print y=5..12 x=14..28
    for y in range(4, 14):
        print(y, rows[y][14:29])

    merged=json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    pending=[]
    for row in merged["records"]:
        if row.get("semantic_category")!="series_title":
            continue
        off=int(row["target_file_offset"],16)
        owners=row.get("owner_ids") or []
        own=int(str(owners[0]).split("-")[-1],16) if owners else None
        live_ptr=u32(ko, own) if own is not None else ROM_BASE+off
        live, live_slots, _=decode8(ko, live_ptr, d8, m8)
        jp_t,_,_=decode8(jp, ROM_BASE+off, d8j, jp_map8)
        hangul=sum(1 for c in live if "가"<=c<="힣")
        jp_kana=sum(1 for c in live if "ぁ"<=c<="ヶ" or "一"<=c<="龠")
        if hangul==0 or jp_kana:
            pending.append({"id":row["record_id"],"status":row.get("translation_status"),"sheet":row.get("translation_ko"),"jp":jp_t,"live":live,"owner":hex(own) if own is not None else None,"src":row.get("source_text")})
    print("series still jp-like", len(pending))
    for p in pending:
        print(p)

if __name__=="__main__":
    main()
