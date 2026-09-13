"""Translate all situation map-name owners and consistent desert-name siblings."""
import json,struct,re
from collections import Counter
from pathlib import Path
import patch_ggen_profile_followup2_20260912 as f2
import patch_ggen_profile_followup4_20260912 as f4
import build_ggen_advance_unified_rom_poc as u
import ggen_advance_text_codec as c
from patch_ggen_advance_kimi_jane_to_neo_20260904 import owner_offsets,update_payload_hash
from merge_ggen_advance_translation_overlays import digest
import build_ggen_allclear_profiles_ko_20260912 as a
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs/20260913_situation_map'
EXPECTED='d015d7ad7297e816e83c71770ac6cc0a4809d9c4dcd657d33a8e394888c1dbd7'
TABLE=0xd55888;BATCH='situation-map-names-20260913'
FIXES={1:'위성 궤도상',3:'태평양 연안부',4:'중앙아시아 사막지대',11:'L1우주역',13:'달 항로',16:'솔로몬 주변 우주역',18:'달 궤도상',22:'중앙아시아 사막지대',24:'폐 콜로니 우주역',26:'위성 궤도상',28:'사막지대',29:'대서양군 기지',30:'뉴야크 폐허',31:'지구 궤도 데브리대',33:'달 궤도 항로'}
def main():
 OUT.mkdir(parents=True,exist_ok=True);parent=(ROOT/'SD Gundam GGeneration Advance (Korean).gba').read_bytes();assert a.sha(parent)==EXPECTED
 source=(ROOT/'integrated/translation/ggen_advance_translation_merged.json').read_bytes();merged=json.loads(source);(OUT/'parent_translation.json').write_bytes(source)
 byowner={o:r for r in merged['records'] for o in owner_offsets(r)};byid={r['record_id']:r for r in merged['records']}
 maps={};hang={};ds={};verified={}
 for mode,path,start,end in [(8,u.CHARMAP_8X16_PATH,c.DICT_8X16_BASE,c.DICT_8X16_END),(12,u.CHARMAP_12X12_PATH,c.DICT_12X12_BASE,c.DICT_12X12_END)]:
  verified[mode]=u.load_verified_charmap(path);hang[mode]={ch:s for s,ch in f2.hangul_slot_map(parent,mode=mode).items()};maps[mode]=f2.slot_to_char_map(verified[mode],hang[mode],{});ds[mode]=c.load_dictionary(parent,start,end)
 cand=bytearray(parent);allowed=set();cursor=0x13d6000;assert not any(parent[cursor:0x13d8000]);jobs=[];updates={};painted=[]
 jp=(ROOT/'SD Gundam GGeneration Advance (Japan).gba').read_bytes();live8,_=u.collect_live_slots(jp,merged['records'])
 required={ch for text in FIXES.values() for ch in text if '가'<=ch<='힣'}
 hang[8].update(f2.recover_hangul(cand,jp,required,mode=8,live=live8,occupied=set(hang[8].values()),allowed=allowed,painted=painted))
 maps[8]=f2.slot_to_char_map(verified[8],hang[8],{})
 def place(owner,text,mode):
  nonlocal cursor
  before=f2.decode_text(parent,f2.u32(parent,owner),ds[mode],maps[mode]);raw=f4.encode_mixed(text,hang[mode],verified[mode],{})
  cursor=(cursor+3)&~3;assert cursor+len(raw)<0x13d8000
  cand[cursor:cursor+len(raw)]=raw;allowed.update(range(cursor,cursor+len(raw)));struct.pack_into('<I',cand,owner,0x8000000+cursor);allowed.update(range(owner,owner+4))
  assert f2.decode_text(cand,0x8000000+cursor,ds[mode],maps[mode])==text
  jobs.append(dict(owner=hex(owner),before=before,after=text,mode=mode,new_pointer=hex(0x8000000+cursor),raw=raw.hex(),record_id=byowner[owner]['record_id']));updates[byowner[owner]['record_id']]=text;cursor+=len(raw)
 for i,text in FIXES.items():place(TABLE+i*32+16,text,8)
 # Same Japanese desert label, earlier misread on the 12x12 location paths.
 for rid in ['GGA-TEXT-0018D4FC','GGA-TEXT-0018D5D5','GGA-TEXT-0018D603','GGA-TEXT-001BE9D7']:
  row=byid[rid];text=row['translation_ko'].replace('사선지대','사막지대');assert text!=row['translation_ko']
  for owner in owner_offsets(row):place(owner,text,12)
 names=[]
 for i in range(64):
  owner=TABLE+i*32+16;text=f2.decode_text(cand,f2.u32(cand,owner),ds[8],maps[8]);assert not re.search(r'[\u3040-\u30ff\u4e00-\u9fff]|<[0-9A-F]{4}>',text),(i,text)
  assert len(text)*8<=128,(i,text);names.append(text)
 assert not f2.u32(parent,TABLE+64*32+4)
 for rid,text in updates.items():
  row=byid[rid];row.update(translation_ko=text,translation_status='translated',translation_source='original_rom_glyph_review',review_status='reviewed',reviewed_at='2026-09-13',qa_status='owner_and_physical_glyph_verified',overlay_batch_id=BATCH,pointer_recalc_required=True)
  row['translator_notes']='Situation map-name +0x10 consumer 0801C634/0801C63E; original Japanese bitmap verified; desert siblings corrected.';update_payload_hash(row)
 identity=merged['identity'];oldid=identity['translation_overlay_identity_sha256'];newid=digest({'parent':oldid,'batch':BATCH,'updates':updates});identity.update(parent_translation_overlay_identity_sha256=oldid,translation_overlay_identity_sha256=newid)
 merged['summary'].update(translation_overlay_identity_sha256=newid,merged_translation_status_counts=dict(Counter(r['translation_status'] for r in merged['records'])));merged[BATCH]={'changed_records':sorted(updates)}
 snapshot=ROOT/'analysis/ggen_advance_translation_merged_20260913_situation_map.json';snapshot.write_text(json.dumps(merged,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 changed={i for i,(x,y) in enumerate(zip(parent,cand)) if x!=y};assert changed<=allowed
 out=OUT/'ggen_situation_map_names_20260913.gba';out.write_bytes(cand);(OUT/'parent.gba').write_bytes(parent)
 report=dict(parent_sha256=EXPECTED,parent_translation_sha256=a.sha(source),output=dict(path=out.relative_to(ROOT).as_posix(),size=len(cand),sha256=a.sha(cand)),jobs=jobs,painted=painted,changed_records=sorted(updates),all_64_names=names,changed_bytes=len(changed),verification=dict(result='PENDING',owner_roundtrips=True,all_64_names_no_japanese=True,all_situation_names_fit_128px=True,unrelated_bytes_preserved=True))
 (OUT/'manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(len(jobs),'owners',len(updates),'records',a.sha(cand))
if __name__=='__main__':main()
