"""Resolve the last-session title from original glyphs and patch its text owner."""
import json
import shutil
import struct
from collections import Counter
from pathlib import Path

from PIL import Image
import patch_ggen_advance_pending_readable_batch_20260907 as prev
import build_ggen_advance_ko_poc as fontops
import ggen_advance_painted_glyph_identity as glyph
from ggen_advance_text_codec import read_tokens, load_dictionary, expand_to_slots, DICT_8X16_BASE, DICT_8X16_END
from ggen_advance_project_paths import MAIN_TIP_ROM, MAIN_TIP_MANIFEST, ORIGINAL_ROM, TRANSLATION_MERGED_JSON, TRANSLATION_MANIFEST, advance_relative
from patch_ggen_advance_intermission_text_consumers_20260904 import payload_at, sha256, u32, gate
from merge_ggen_advance_translation_overlays import digest

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs/20260907_special_title'
JP = '妄執、果てる時'
KO = '망집이 끝날 때'
RID = 'GGA-TEXT-0018D259'
OWNER = 0xFCE374
CAVE = 0x12BF000

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    original = ORIGINAL_ROM.read_bytes()
    current = MAIN_TIP_ROM.read_bytes()
    gate(sha256(current) == json.loads(MAIN_TIP_MANIFEST.read_text(encoding='utf-8'))['sha256'], 'main drift')
    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding='utf-8'))
    row = next(r for r in merged['records'] if r['record_id'] == RID)
    raw = bytes.fromhex(row['raw_hex'])
    gate(raw == bytes.fromhex('E6 03 E5 49 96 E0 B5 F0 12 AE 00'), 'source drift')
    gate(row['translation_status'] == 'pending' or row.get('overlay_batch_id') == 'special-title-decoded-20260907', 'record already changed')
    gate(row['owner_ids'] == ['OWNER-U32-00FCE374'], 'owner drift')
    gate(payload_at(current, u32(current, OWNER)) == raw, 'active payload drift')
    tokens, _ = read_tokens(original, 0x18D259)
    dictionary = load_dictionary(original, DICT_8X16_BASE, DICT_8X16_END)
    slots = expand_to_slots(tokens, dictionary)
    gate(slots == [0x6E3,0x629,0x96,0x195,0x33,0x4B,0xAE], 'source slots drift')
    font = glyph.load_galmuri8()
    # Recover actual active 8x16 font cells; the broad semantic category is misleading.
    ko_slots = glyph.recover_unique_8x16_slots(current, font, set(KO) - {' '})
    payload = prev.encode_text(KO, ko_slots, {})
    gate(not any(current[CAVE:CAVE+0x100]), 'cave occupied')
    candidate = bytearray(current)
    candidate[CAVE:CAVE+len(payload)] = payload
    struct.pack_into('<I', candidate, OWNER, 0x08000000+CAVE)
    glyph.verify_payload_painted(candidate, payload, KO, font)
    gate(payload_at(candidate, u32(candidate, OWNER)) == payload, 'pointer roundtrip')
    allowed = set(range(OWNER,OWNER+4)) | set(range(CAVE,CAVE+len(payload)))
    changed = {i for i,(a,b) in enumerate(zip(current,candidate)) if a != b}
    gate(changed <= allowed, 'unexpected byte edits')
    # Preview the exact original and active Korean 8x16 cells, not a substitute font.
    canvas = Image.new('L', (240,64))
    for i,s in enumerate(slots):
        start = fontops.FONT_8X16_BASE+s*32
        canvas.paste(fontops.unpack_8x16(original[start:start+32]), (8+i*8,8))
    for i,c in enumerate(KO):
        if c == ' ': continue
        start = glyph.FONT8_RELOCATED+ko_slots[c]*32
        canvas.paste(fontops.unpack_8x16(candidate[start:start+32]), (8+i*8,36))
    canvas.resize((960,256), Image.Resampling.NEAREST).save(OUT/'before_after.png')
    output = OUT/'ggen_special_title_ko_20260907.gba'
    output.write_bytes(candidate)
    if not (OUT/'translation_before.json').exists():
        shutil.copy2(TRANSLATION_MERGED_JSON, OUT/'translation_before.json')
        shutil.copy2(TRANSLATION_MANIFEST, OUT/'translation_manifest_before.json')
    prev.BATCH_ID = 'special-title-decoded-20260907'
    prev.mark_row(row, JP, KO, '원본 ROM 8x16 글리프와 LAST 세션 목록 교차 확인. 제공 목록에는 누락. owner FCE374. 포괄적인 semantic_category와 달리 이 세션 제목은 8x16.')
    row['translation_source'] = 'rom_glyph_analysis'
    row['qa_status'] = 'static_payload_and_glyph_verified'
    prev.update_payload_hash(row)
    identity = merged.setdefault('identity',{})
    parent = identity.get('translation_overlay_identity_sha256','')
    identity['parent_translation_overlay_identity_sha256'] = parent
    identity['translation_overlay_identity_sha256'] = digest({'parent':parent,'batch':prev.BATCH_ID,'record':RID,'jp':JP,'ko':KO})
    counts = dict(Counter(r.get('translation_status','') for r in merged['records']))
    merged.setdefault('summary',{})['merged_translation_status_counts'] = counts
    merged['summary']['translation_overlay_identity_sha256'] = identity['translation_overlay_identity_sha256']
    snapshot = OUT/'translation_after.json'
    data = json.dumps(merged,ensure_ascii=False,indent=2)+'\n'
    snapshot.write_text(data,encoding='utf-8')
    TRANSLATION_MERGED_JSON.write_text(data,encoding='utf-8')
    prev.update_translation_manifest(merged,snapshot)
    report = {'record':RID,'session':'LAST','japanese':JP,'korean':KO,'source_slots':dict(zip(map(hex,slots),JP)),
      'owner':hex(OWNER),'previous_pointer':hex(u32(current,OWNER)),'new_pointer':hex(u32(candidate,OWNER)),
      'payload':payload.hex(' '),'korean_slots':{c:hex(s) for c,s in ko_slots.items()},
      'parent':{'sha256':sha256(current)},
      'output':{'path':advance_relative(output),'size':len(candidate),'sha256':sha256(candidate)},
      'verification':{'result':'PASS','only_owner_and_payload_changed':True,'active_8x16_glyphs_verified':True,'new_glyphs':0,'runtime_emulator':'not run; static verification only'},
      'document':'docs/GGENERATION_ADVANCE_ALL_SESSION_LIST.md',
      'corroboration':'https://www.newwise.com/guide_8/gba_10/2005-01/3A32BBB0-B2D5-1925-43B8-B8936A88031F.htm'}
    (OUT/'manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    main()
