"""Synchronize ten audited stage titles into the current 8x16 text table."""
import json
import shutil
import struct
from collections import Counter
from pathlib import Path
from PIL import Image, ImageDraw
import patch_ggen_special_title_20260907 as base
import ggen_advance_painted_glyph_identity as glyph
import build_ggen_advance_unified_rom_poc as unified
from ggen_advance_text_codec import read_tokens, load_dictionary, expand_to_slots, DICT_8X16_BASE, DICT_8X16_END

ROOT = base.ROOT
OUT = ROOT/'outputs/20260907_remaining_ten_titles'
CAVE = 0x12BF100
END = 0x12BF800

def stream_at(rom, pointer):
    # A zero low byte inside F000 is a dictionary index, not a terminator.
    return read_tokens(rom, pointer-0x08000000)[1]

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    current = base.MAIN_TIP_ROM.read_bytes()
    original = base.ORIGINAL_ROM.read_bytes()
    gate = base.gate
    gate(base.sha256(current) == json.loads(base.MAIN_TIP_MANIFEST.read_text(encoding='utf-8'))['sha256'], 'main drift')
    sheet_bytes = base.TRANSLATION_MERGED_JSON.read_bytes()
    merged = json.loads(sheet_bytes)
    by_id = {r['record_id']:r for r in merged['records']}
    audit = json.loads((ROOT/'outputs/20260907_ggen_stage_title_audit/audit.json').read_text(encoding='utf-8'))
    jobs = [r for r in audit['missing'] if r['session'] != 'special']
    gate(len(jobs) == 10, 'expected ten titles')
    for job in jobs:
        row = by_id[job['record']]
        owner = int(job['owner'],16)
        gate(row['translation_status'] == 'pending', 'title no longer pending: '+job['record'])
        gate(base.prev.owner_offsets(row) == (owner,), 'owner drift')
        gate(stream_at(current,base.u32(current,owner)) == bytes.fromhex(row['raw_hex']), 'payload already changed')
        gate(bool(job['entry_graphic_translation']), 'missing Korean title')
    gate(not any(current[CAVE:END]), 'cave occupied')
    candidate = bytearray(current)
    font = glyph.load_galmuri8()
    wanted = set(''.join(j['entry_graphic_translation'] for j in jobs))-{' '}
    slots = {}
    allowed = set()
    painted = []
    live8,_ = unified.collect_live_slots(original,merged['records'])
    occupied = set()
    for c in sorted(wanted):
        slot = base.prev.try_recover(glyph.recover_unique_8x16_slots,candidate,font,c)
        if slot is None:
            slot = base.prev.choose_free_8x16(candidate,original,live8,occupied)
            start = glyph.paint_8x16(candidate,slot,c,font)
            allowed.update(range(start,start+32))
            live8.add(slot)
            painted.append({'char':c,'slot':hex(slot)})
        slots[c] = slot
        occupied.add(slot)
    dictionary = load_dictionary(original,DICT_8X16_BASE,DICT_8X16_END)
    canvas = Image.new('L',(240, len(jobs)*56))
    draw = ImageDraw.Draw(canvas)
    cursor = CAVE
    report_jobs = []
    base.prev.BATCH_ID = 'remaining-ten-stage-titles-20260907'
    for n,job in enumerate(jobs):
        row = by_id[job['record']]
        ko = job['entry_graphic_translation']
        owner = int(job['owner'],16)
        payload = base.prev.encode_text(ko,slots,{})
        cursor = base.prev.align16(cursor)
        gate(cursor+len(payload)<=END,'cave overflow')
        candidate[cursor:cursor+len(payload)] = payload
        struct.pack_into('<I',candidate,owner,0x08000000+cursor)
        allowed.update(range(cursor,cursor+len(payload)))
        allowed.update(range(owner,owner+4))
        glyph.verify_payload_painted(candidate,payload,ko,font)
        gate(stream_at(candidate,base.u32(candidate,owner)) == payload,'pointer roundtrip')
        tokens,_ = read_tokens(original,int(row['target_file_offset'],16))
        source_slots = expand_to_slots(tokens,dictionary)
        y=n*56
        draw.text((0,y), job['session'],fill=150)
        for i,s in enumerate(source_slots):
            start=base.fontops.FONT_8X16_BASE+s*32
            canvas.paste(base.fontops.unpack_8x16(original[start:start+32]),(8+i*8,y+12))
        for i,c in enumerate(ko):
            if c==' ': continue
            start=glyph.FONT8_RELOCATED+slots[c]*32
            canvas.paste(base.fontops.unpack_8x16(candidate[start:start+32]),(8+i*8,y+32))
        base.prev.mark_row(row,job['japanese_title'],ko,'기존 스테이지 진입 이미지 번역과 텍스트 제목 동기화. 실제 8x16 글리프 역대조 인코딩.')
        row['translation_source']='curated_project_data'
        row['qa_status']='static_payload_and_glyph_verified'
        base.prev.update_payload_hash(row)
        report_jobs.append({'record':row['record_id'],'session':job['session'],'japanese':job['japanese_title'],'korean':ko,'owner':hex(owner),'pointer':hex(0x08000000+cursor),'payload':payload.hex(' ')})
        cursor+=len(payload)
    changed={i for i,(a,b) in enumerate(zip(current,candidate)) if a!=b}
    gate(changed<=allowed,'unexpected edits')
    # Verify all 28 original title payloads have now been replaced; this is not a full runtime audit.
    original_remaining=[]
    for title in audit['titles']:
        row=by_id[title['record']]
        owner=int(title['owner'],16)
        if stream_at(candidate,base.u32(candidate,owner))==bytes.fromhex(row['raw_hex']):
            original_remaining.append(row['record_id'])
    gate(not original_remaining,'original titles remain')
    canvas.resize((720,len(jobs)*168),Image.Resampling.NEAREST).save(OUT/'before_after.png')
    output=OUT/'ggen_remaining_ten_titles_ko_20260907.gba'
    output.write_bytes(candidate)
    (OUT/'translation_before.json').write_bytes(sheet_bytes)
    shutil.copy2(base.TRANSLATION_MANIFEST,OUT/'translation_manifest_before.json')
    identity=merged.setdefault('identity',{})
    parent=identity.get('translation_overlay_identity_sha256','')
    identity['parent_translation_overlay_identity_sha256']=parent
    identity['translation_overlay_identity_sha256']=base.digest({'parent':parent,'batch':base.prev.BATCH_ID,'jobs':report_jobs})
    merged.setdefault('summary',{})['merged_translation_status_counts']=dict(Counter(r.get('translation_status','') for r in merged['records']))
    merged['summary']['translation_overlay_identity_sha256']=identity['translation_overlay_identity_sha256']
    snapshot=OUT/'translation_after.json'
    data=json.dumps(merged,ensure_ascii=False,indent=2)+'\n'
    gate(base.MAIN_TIP_ROM.read_bytes()==current,'main changed during build')
    gate(base.TRANSLATION_MERGED_JSON.read_bytes()==sheet_bytes,'sheet changed during build')
    snapshot.write_text(data,encoding='utf-8')
    base.TRANSLATION_MERGED_JSON.write_text(data,encoding='utf-8')
    base.prev.update_translation_manifest(merged,snapshot)
    report={'result':'PASS','titles':report_jobs,'painted_glyphs':painted,'parent':{'sha256':base.sha256(current)},'output':{'path':base.advance_relative(output),'size':len(candidate),'sha256':base.sha256(candidate)},'verification':{'result':'PASS','title_count':10,'all_payloads_and_8x16_glyphs_verified':True,'only_target_owners_payloads_and_new_glyphs_changed':True,'audited_original_title_payloads_remaining':0,'audited_title_count':28,'runtime_emulator':'not run; static verification only'}}
    (OUT/'manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    main()
