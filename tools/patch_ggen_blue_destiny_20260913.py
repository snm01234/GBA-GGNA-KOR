"""Unify all five Blue Destiny I name owners on the current main TIP."""
import json, struct
from pathlib import Path
from PIL import Image
import patch_ggen_situation_map_names_20260913 as p
import verify_ggen_ss1_ss9_20260913 as v
import ggen_advance_painted_glyph_identity as glyph

ROOT=p.ROOT; OUT=ROOT/'outputs/20260913_blue_destiny'
def main():
 OUT.mkdir(exist_ok=True)
 parent=(ROOT/'SD Gundam GGeneration Advance (Korean).gba').read_bytes()
 assert p.a.sha(parent)=='37e1ef1b66f34ebf27ede05c1cc26122a884345073037a3709bfa6e4a6503c26'
 source=(ROOT/'integrated/translation/ggen_advance_translation_merged.json').read_bytes();merged=json.loads(source)
 rows=[r for r in merged['records'] if r.get('translation_ko')=='BD I'];assert len(rows)==5
 verified=p.u.load_verified_charmap(p.u.CHARMAP_8X16_PATH)
 hang={ch:s for s,ch in p.f2.hangul_slot_map(parent,mode=8).items()}
 mapping=p.f2.slot_to_char_map(verified,hang,{})
 dictionary=p.c.load_dictionary(parent,p.c.DICT_8X16_BASE,p.c.DICT_8X16_END)
 text='블루 데스티니 I';raw=p.f4.encode_mixed(text,hang,verified,{})
 cand=bytearray(parent);start=0x13d8000;cursor=start;assert not any(parent[start:start+0x100])
 allowed=set();jobs=[]
 for r in rows:
  assert not p.u.uses_12x12(r)
  for owner in p.owner_offsets(r):
   old=p.f2.u32(parent,owner);before=p.f2.decode_text(parent,old,dictionary,mapping)
   assert before in ('BD I','<07FB>BD I','<07F8>BD I','<07FC>BD I'),(hex(owner),before)
   after=before.replace('BD I',text);encoded=p.f4.encode_mixed(after,hang,verified,{})
   cand[cursor:cursor+len(encoded)]=encoded;allowed.update(range(cursor,cursor+len(encoded)))
   struct.pack_into('<I',cand,owner,0x8000000+cursor);allowed.update(range(owner,owner+4))
   assert p.f2.decode_text(cand,p.f2.u32(cand,owner),dictionary,mapping)==after
   jobs.append(dict(owner=hex(owner),old_pointer=hex(old),new_pointer=hex(0x8000000+cursor),before=before,after=after,record_id=r['record_id']))
   cursor=(cursor+len(encoded)+3)&~3
  r.update(translation_ko=after,translation_status='translated',translation_source='user_requested_name_consistency',review_status='reviewed',reviewed_at='2026-09-13',qa_status='owner_and_physical_glyph_verified',pointer_recalc_required=True,overlay_batch_id='blue-destiny-i-20260913',translator_notes='Expand BD I consistently with Blue Destiny II and III; preserve current leading icon slots.')
  p.update_payload_hash(r)
 slots=[p.c.normalized_slot(t) for t in p.c.read_tokens(raw,0)[0]];font=glyph.load_galmuri8()
 assert len(slots)==len(text)
 for ch,s in zip(text,slots):
  if '가'<=ch<='힣':assert cand[glyph.FONT8_RELOCATED+s*32:glyph.FONT8_RELOCATED+(s+1)*32]==glyph.packed_8x16(ch,font)
 mask=v.mask(cand,int(jobs[-1]['new_pointer'],16),8);assert mask.width==len(text)*8==72
 preview=Image.new('RGB',mask.size,'white');preview.paste('black',(0,0,mask.width,mask.height),mask);preview.resize((640,128),Image.Resampling.NEAREST).save(OUT/'name_after.png')
 changed={i for i,(a,b) in enumerate(zip(parent,cand)) if a!=b};assert changed<=allowed
 ident=merged['identity'];old=ident['translation_overlay_identity_sha256'];new=p.digest({'parent':old,'batch':'blue-destiny-i-20260913','records':[r['record_id'] for r in rows]})
 ident.update(parent_translation_overlay_identity_sha256=old,translation_overlay_identity_sha256=new);merged['summary']['translation_overlay_identity_sha256']=new
 snapshot=ROOT/'analysis/ggen_advance_translation_merged_20260913_blue_destiny.json';snapshot.write_text(json.dumps(merged,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 out=OUT/'ggen_blue_destiny_20260913.gba';out.write_bytes(cand);(OUT/'parent.gba').write_bytes(parent);(OUT/'parent_translation.json').write_bytes(source)
 report=dict(parent_sha256=p.a.sha(parent),output=dict(path=out.relative_to(ROOT).as_posix(),size=len(cand),sha256=p.a.sha(cand)),jobs=jobs,changed_records=[r['record_id'] for r in rows],changed_bytes=len(changed),savestate_sha256={str(i):p.a.sha((ROOT/f'SD Gundam GGeneration Advance (Korean).ss{i}').read_bytes()) for i in (1,2)},verification=dict(result='PASS',all_five_owner_roundtrips=True,physical_glyphs=True,width_pixels=72,unrelated_bytes_preserved=True,runtime='Actual ROM font raster; supplied states do not show BD I; no live emulator verification'))
 (OUT/'manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print('PASS: five owners, 72px, physical glyphs; '+p.a.sha(cand))
if __name__=='__main__':main()

