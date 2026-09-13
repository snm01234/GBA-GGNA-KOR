"""Correct updated ss1-ss9 terminology, pending save labels and focus chrome.

Patch the current main TIP only; retain existing OBJ resource addresses so cached
resource owners in the user's states remain valid after a menu redraw.
"""
import hashlib,json,pickle,re,struct,sys
from collections import Counter
from pathlib import Path
from PIL import Image
import patch_ggen_profile_followup2_20260912 as f2
import patch_ggen_profile_followup4_20260912 as f4
import build_ggen_advance_unified_rom_poc as unified
import build_ggen_advance_develop_menu_buttons_ko_image_20260901 as btn
import analyze_ggen_advance_develop_menu_buttons_images_20260901 as cat
import ggen_advance_text_codec as codec
from ggen_advance_painted_glyph_identity import load_galmuri12
from patch_ggen_advance_kimi_jane_to_neo_20260904 import owner_offsets,update_payload_hash
from merge_ggen_advance_translation_overlays import digest

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs/20260913_ss1_ss9_followup'
SNAPSHOT=ROOT/'analysis/ggen_advance_translation_merged_20260913_ss1_ss9.json'
BATCH='ss1-ss9-followup-20260913'
EXPECTED='0c84d052199aaab52c26b052859901dfcc07031f1b3523e968b1387bbc1e4191'
def sha(b):return hashlib.sha256(b).hexdigest()
def main():
 sys.stdout.reconfigure(encoding='utf-8')
 parent=(ROOT/'SD Gundam GGeneration Advance (Korean).gba').read_bytes();assert sha(parent)==EXPECTED
 jp=(ROOT/'SD Gundam GGeneration Advance (Japan).gba').read_bytes()
 # Immutable source paired with EXPECTED; later canonical edits must not make
 # a rerun silently omit already-updated rows from this one-shot ROM patch.
 source=(ROOT/'analysis/ggen_advance_translation_merged_20260913_cannon_open.json').read_bytes()
 assert sha(source)=='b35d5c5de4175161efa15c485fbd7632b4e75cfdbeb3bdea3c754b0859fa87e3'
 merged=json.loads(source)
 byid={r['record_id']:r for r in merged['records']}
 maps,hang,ds=pickle.load((OUT/'maps.pkl').open('rb'))
 verified={8:unified.load_verified_charmap(unified.CHARMAP_8X16_PATH),12:unified.load_verified_charmap(unified.CHARMAP_12X12_PATH)}
 recovered={m:{ch:s for s,ch in hang[m].items()} for m in (8,12)}
 cand=bytearray(parent);allowed=set();cursor=0x13d2000;applied=[];updates={}
 assert not any(parent[cursor:0x13d4000])
 def place(owner,text,mode,record_id=None):
  nonlocal cursor
  raw=f4.encode_mixed(text,recovered[mode],verified[mode],{'<':0x134,'>':0x135} if mode==8 else {})
  oldptr=f2.u32(parent,owner);old=f2.decode_text(parent,oldptr,ds[mode],maps[mode])
  cursor=(cursor+3)&~3;assert cursor+len(raw)<0x13d4000
  cand[cursor:cursor+len(raw)]=raw;allowed.update(range(cursor,cursor+len(raw)))
  struct.pack_into('<I',cand,owner,codec.ROM_BASE+cursor);allowed.update(range(owner,owner+4))
  assert f2.decode_text(cand,codec.ROM_BASE+cursor,ds[mode],maps[mode])==text
  applied.append(dict(owner=hex(owner),mode=mode,before=old,after=text,pointer=hex(codec.ROM_BASE+cursor),raw=raw.hex(),record_id=record_id))
  cursor+=len(raw)
 for row in merged['records']:
  old=row.get('translation_ko','');new=old.replace('명경지술','명경지수').replace('발 바르','발 바로').replace('모든 사격 공격을 막는다','모든 사격을 막는다')
  if old==new:continue
  updates[row['record_id']]=new
  for owner in owner_offsets(row):
   actual=f2.decode_text(parent,f2.u32(parent,owner),ds[8],maps[8])
   fixed=actual.replace('명경지술','명경지수').replace('발 바르','발 바로').replace('모든 사격 공격을 막는다','모든 사격을 막는다')
   assert fixed!=actual,(row['record_id'],actual)
   place(owner,fixed,8,row['record_id'])
 owner=0x1b4a38;old=f2.decode_text(parent,f2.u32(parent,owner),ds[12],maps[12]);assert '넬 아르가마' in old
 fixed=old.replace('넬 아르가마','넬 아가마');place(owner,fixed,12)
 for r in merged['records']:
  if owner in owner_offsets(r):updates[r['record_id']]=fixed
 stages=[('GGA-TEXT-0018D31F','掃討作戦実行中','소탕 작전 실행 중',8),
         ('GGA-TEXT-0018D2FD','「直前にクリアしたステージ」','<0136>직전에 클리어한 스테이지<0137>',8),
         ('GGA-TEXT-001BE9EC','ニューヤーク廃墟','뉴야크 폐허',12),
         ('GGA-TEXT-0018D618','ニューヤーク廃墟','뉴야크 폐허',12)]
 for rid,source,ko,mode in stages:
  r=byid[rid]
  for owner in owner_offsets(r):place(owner,ko,mode,rid)
  updates[rid]=ko
  r['translator_notes']=f'Original ROM glyphs visually verified: {source}; mixed 8x16/12x12 table'
 # Rebuild focus execute badges from the actual current cancel chrome.
 font=load_galmuri12();catalog=cat.enumerate_buttons(jp);button_jobs=[];previews=[]
 for spec in cat.PACKAGES:
  start=btn.CLONES[spec['name']];addr=codec.ROM_BASE+start
  h=btn.analysis.parse_resource_header(parent,addr);_,records=btn.sprite.animation_records(parent,addr)
  entries=[r for r in catalog if r['package']==spec['name'] and r['kind']=='64' and r['face']==12]
  cancel=next(r for r in entries if r['ko']=='캔슬');p,ids,_=cat.parse_anim(records,cancel['anim'])
  template=btn.analysis.stitch(h['graphics'],p,ids,list(cancel['objects']))
  clean=[[template[y][8] if v in (1,12) else v for v in line] for y,line in enumerate(template)]
  assert all(clean[y][x]==10 for y in range(2,14) for x in range(5,59))
  graphics=bytearray(h['graphics']);clone=bytearray(parent[start:start+h['graphics_rel']]);changes=[]
  for row in entries:
   if row['ko']=='캔슬':continue
   p,ids,lookup=cat.parse_anim(records,row['anim']);objects=p['objects'];source=btn.analysis.stitch(h['graphics'],p,ids,list(row['objects']))
   mask,tw=btn.paintops.make_text_mask(row['ko'],font,64,16,cell_width=12)
   rebuilt=[line[:] for line in clean];btn.paint_mask_cardinal(rebuilt,mask,ink=12,contour=1)
   gx=min(objects[i]['x'] for i in row['objects']);gy=min(objects[i]['y'] for i in row['objects'])
   c=0;objids=[]
   for o in objects:objids.append(ids[c:c+o['tile_count']]);c+=o['tile_count']
   pieces=[]
   for local,idx in enumerate(row['objects']):
    o=objects[idx];wt=o['size_px'][0]//8;ht=o['size_px'][1]//8;old=bytearray();new=bytearray()
    for ty in range(ht):
     for tx in range(wt):
      n=ty*wt+tx;payload=btn.tile_payload(rebuilt,o,gx,gy,tx,ty);tid=len(graphics)//32;graphics.extend(payload)
      struct.pack_into('<H',clone,lookup-start+(row['lookup_object_bases'][local]+n)*2,tid)
      old.extend(h['graphics'][objids[idx][n]*32:(objids[idx][n]+1)*32]);new.extend(payload)
    pieces.append(dict(old=bytes(old).hex(),new=bytes(new).hex()))
   job=dict(package=spec['name'],animation=row['anim'],ko=row['ko'],pieces=pieces)
   changes.append(job);button_jobs.append(job);previews.append((source,rebuilt,h['palettes'],row['bank']))
  newpal=h['graphics_rel']+len(graphics);struct.pack_into('<I',clone,12,newpal);clone.extend(graphics);clone.extend(h['palettes'])
  assert len(clone)<0x8000
  assert not any(parent[start+h['resource_bytes']:start+len(clone)])
  cand[start:start+len(clone)]=clone;allowed.update(range(start,start+len(clone)))
  # Decode each changed lookup through the real package parser, not just painter output.
  nh=btn.analysis.parse_resource_header(cand,addr);_,nr=btn.sprite.animation_records(cand,addr)
  for job in changes:
   row=next(r for r in entries if r['anim']==job['animation'] and r['ko']==job['ko']);p,ids,_=cat.parse_anim(nr,row['anim'])
   canvas=btn.analysis.stitch(nh['graphics'],p,ids,list(row['objects']))
   mask,_=btn.paintops.make_text_mask(row['ko'],font,64,16,cell_width=12);expected=[r[:] for r in clean];btn.paint_mask_cardinal(expected,mask,ink=12,contour=1)
   assert canvas==expected
 for rid,ko in updates.items():
  r=byid[rid];r.update(translation_ko=ko,translation_status='translated',translation_source='user_requested_correction',review_status='reviewed',reviewed_at='2026-09-13',qa_status='physical_glyph_and_owner_verified',overlay_batch_id=BATCH,pointer_recalc_required=True)
  update_payload_hash(r)
 identity=merged['identity'];previous=identity['translation_overlay_identity_sha256'];newid=digest({'parent':previous,'batch':BATCH,'updates':updates})
 identity.update(parent_translation_overlay_identity_sha256=previous,translation_overlay_identity_sha256=newid)
 merged['summary'].update(translation_overlay_identity_sha256=newid,merged_translation_status_counts=dict(Counter(r['translation_status'] for r in merged['records'])))
 merged[BATCH]={'changed_records':sorted(updates)};SNAPSHOT.write_text(json.dumps(merged,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 changed={i for i,(a,b) in enumerate(zip(parent,cand)) if a!=b};assert changed<=allowed
 (OUT/'parent.gba').write_bytes(parent);output=OUT/'ggen_ss1_ss9_fixed_20260913.gba';output.write_bytes(cand)
 preview=Image.new('RGB',(512,len(previews)*64))
 for i,(a,b,p,bank) in enumerate(previews):
  preview.paste(cat.canvas_image(a,p,bank,4),(0,i*64));preview.paste(cat.canvas_image(b,p,bank,4),(256,i*64))
 preview.save(OUT/'buttons_compare.png')
 report=dict(batch=BATCH,parent_sha256=sha(parent),output=dict(path=output.relative_to(ROOT).as_posix(),size=len(cand),sha256=sha(cand)),texts=applied,buttons=button_jobs,changed_records=sorted(updates),changed_bytes=len(changed),verification=dict(result='PENDING',owner_roundtrips=True,button_resource_roundtrips=True,unrelated_bytes_preserved=True))
 (OUT/'manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(len(applied),'text owners;',len(button_jobs),'focus buttons;',len(updates),'records')
if __name__=='__main__':main()
