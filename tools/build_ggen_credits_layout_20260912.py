"""Rebudget native ending-script tile allocations and centers for Korean text."""
import re,json,struct,hashlib,sys
from pathlib import Path
from collections import Counter
import verify_ggen_credits_arm_20260912 as arm
import analyze_table_1c92e8 as table
import ggen_advance_text_codec as codec
import ggen_advance_painted_glyph_identity as glyph
import build_ggen_advance_unified_rom_poc as unified
from merge_ggen_advance_translation_overlays import digest,translation_payload_digest
from PIL import Image,ImageDraw
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs/20260912_credits_followup';BASE=0x8000000
sha=lambda x:hashlib.sha256(x).hexdigest()
PATTERN=re.compile(rb'\x08(..)\x17\xec\x08(..)\x08(..)\x08(..)\x08(..)\x17\xe1',re.S)
STATE_PAGES={1:59,2:65,3:69,5:45,6:47,7:51,8:55}

def native_composite(st):
 import analyze_ggen_advance_jp_ko_ss1_n_tile_owned_count_20260903 as bg
 import analyze_ggen_advance_owned_count_ec0c_trace_runtime_20260904 as obj
 import analyze_ggen_advance_intermission_cycle_states_20260830 as info
 dc=int.from_bytes(st[0x400:0x402],'little');layers=[]
 for i in range(4):
  if dc&(0x100<<i):layers.append((info.bg_info(st,i)['priority'],i,bg.render_bg_native(st,i)))
 im=Image.new('RGBA',(240,160),(*info.rgb555(int.from_bytes(st[0x800:0x802],'little')),255))
 for _,_,l in sorted(layers,key=lambda a:(a[0],a[1]),reverse=True):im.alpha_composite(l)
 if dc&0x1000:im.alpha_composite(obj.render_obj(st))
 return im.convert('RGB')

def main():
 sys.stdout.reconfigure(encoding='utf-8');OUT.mkdir(exist_ok=True)
 parent=(ROOT/'SD Gundam GGeneration Advance (Korean).gba').read_bytes()
 if sha(parent)!='9ef73b4d2105290ae084c22adc7295aee22e56f6cd547bd43c6a9e79701d83b8':parent=(OUT/'parent.gba').read_bytes()
 assert sha(parent)=='9ef73b4d2105290ae084c22adc7295aee22e56f6cd547bd43c6a9e79701d83b8'
 (OUT/'parent.gba').write_bytes(parent)
 jp=(ROOT/'SD Gundam GGeneration Advance (Japan).gba').read_bytes();child=bytearray(parent);allowed=set()
 def write(o,b):child[o:o+len(b)]=b;allowed.update(range(o,o+len(b)))
 source=(ROOT/'integrated/translation/ggen_advance_translation_merged.json').read_bytes()
 if sha(source)!='0fa0fcbcfaf05c3a8d0bf65ec364b0afcc781d7cca7a18ab18ee5f54c0efda32':
  # Reproduction after canonical synchronization uses the exact recorded
  # parent source, never an unrelated dated translation snapshot.
  source=(ROOT/'analysis/ggen_advance_translation_merged_20260912_credits.json').read_bytes()
 assert sha(source)=='0fa0fcbcfaf05c3a8d0bf65ec364b0afcc781d7cca7a18ab18ee5f54c0efda32'
 merged=json.loads(source)
 (OUT/'translation_before.json').write_text(json.dumps(merged,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 prior=json.loads((ROOT/'outputs/20260912_ss123_credits/manifest.json').read_text(encoding='utf-8'))
 groups={g['index']:g for g in prior['groups']};rows={r['record_id']:r for r in merged['records']}
 # Six-line support page must stay below the native blank tile at 0x0520.
 # Keep all names, tightening spacing within each of the two name columns.
 support=groups[70];font=glyph.load_galmuri12();slotmap={}
 for j in support['lines']:
  if '  ' in j['ko']:j['ko']='  '.join(p.replace(' ','') for p in j['ko'].split('  '))
 chars={c for j in support['lines'] for c in j['ko'] if '가'<=c<='힣'}
 for c in chars:slotmap[c]=glyph.recover_unique_12x12_slots(child,font,{c})[c]
 cursor=0x13d1000;assert not any(parent[cursor:cursor+0x1000]);blob=bytearray()
 for j in support['lines']:
  raw,missing=unified.encode_korean_text(j['ko'],slotmap,verified_charmap=unified.load_verified_charmap(unified.CHARMAP_12X12_PATH),strict_punctuation=True);assert not missing
  j['pointer']=BASE+cursor+len(blob);j['encoded_hex']=raw.hex();blob.extend(raw)
  r=rows[j['record_id']];r.update(translation_ko=j['ko'],overlay_batch_id='credits-layout-20260912',translator_notes=r['translator_notes']+' 협력 6줄 화면의 288타일 한도에 맞춰 인명 내부 공백 축소.')
  r['translation_payload_sha256']=translation_payload_digest(dict(r,batch_id=r['overlay_batch_id']))
 blob.append(0);write(cursor,blob);write(support['owner'],struct.pack('<I',BASE+cursor));support['pointer']=BASE+cursor
 pages=[];page=None
 for m in PATTERN.finditer(jp):
  tile,index,color,y,x=[int.from_bytes(m.group(i),'little') for i in range(1,6)]
  if not 35<=index<=105:continue
  assert parent[m.start():m.end()]==m.group(0)
  if tile==0x400:page=[];pages.append(page)
  assert page is not None
  # Native x coordinates were centered using 12 pixels per original token.
  # Preserve each call's center (including the 64/176 two-column scene).
  native_lines,_=table.parse_multiline_blob(jp,table.u32(jp,0x1c92e8+4*index)-BASE)
  old_width=max(l['token_count'] for l in native_lines)*12
  new_width=max(len(l['ko']) for l in groups[index]['lines'])*12
  center2=x*2+old_width;nx=max(0,min(240-new_width,(center2-new_width)//2))
  # Tilemap cells are eight pixels wide. Adjacent columns must not share a
  # boundary tile even when their visible glyph rectangles do not overlap.
  nx=min((240-new_width)//8*8,(nx+4)//8*8)
  assert 0<=nx and nx+new_width<=240
  page.append(dict(offset=m.start(),index=index,old_tile=tile,old_x=x,x=nx,y=y,width=new_width))
 assert len([c for p in pages for c in p])==75
 states={n:arm.parse_png_state(ROOT/f'SD Gundam GGeneration Advance (Korean).ss{n}')[0] for n in STATE_PAGES}
 for n in states:(OUT/f'input.ss{n}').write_bytes((ROOT/f'SD Gundam GGeneration Advance (Korean).ss{n}').read_bytes())
 default=states[1]
 checks=[]
 for page in pages:
  tile=0x400;st=bytearray(default);st[0xf000:0x10000]=struct.pack('<H',0x120)*2048
  rects=[]
  for c in page:
   c['tile']=tile
   st,draws,dma=arm.run(st,bytes(child),[(c['index'],c['x'],c['y'],tile)])
   end=struct.unpack_from('<H',st,0x2b0de)[0];assert end>tile
   c['tile_end']=end
   assert end<=0x520,('native blank tile overlap',c)
   for d,line in zip(draws,groups[c['index']]['lines']):
    assert d['pointer']==line['pointer'];assert c['x']+len(line['ko'])*12<=240
    rect=(c['x']//8*8,d['y']//8*8,((c['x']+len(line['ko'])*12+7)//8)*8,((d['y']+12+7)//8)*8)
    assert rect[3]<=160
    for old in rects:assert rect[2]<=old[0] or old[2]<=rect[0] or rect[3]<=old[1] or old[3]<=rect[1],('text overlap',c,rect,old)
    rects.append(rect)
   write(c['offset']+1,struct.pack('<H',tile));write(c['offset']+15,struct.pack('<H',c['x']));tile=end
  checks.append(dict(first_index=page[0]['index'],tile_end=tile,lines=len(rects)))
 for page in pages:
  for c in page:
   m=PATTERN.match(child,c['offset']);assert m
   values=[int.from_bytes(m.group(i),'little') for i in range(1,6)]
   assert values==[c['tile'],c['index'],0x7fff,c['y'],c['x']]
 path=OUT/'ggen_credits_layout_20260912.gba';path.write_bytes(child)
 comparisons=[];proofs=[]
 for n,first in STATE_PAGES.items():
  page=next(p for p in pages if p[0]['index']==first);st=bytearray(states[n]);st[0xf000:0x10000]=struct.pack('<H',0x120)*2048
  # Replay the exact native scene's calls with old and new script parameters.
  old,_,_=arm.run(st,parent,[(c['index'],c['old_x'],c['y'],c['old_tile']) for c in page])
  # ss3 already contains the overwritten blank tile. Restore its native
  # empty contents for the new-page replay; the corrected allocator never
  # reaches this tile when entering the scene normally.
  # BG0 uses a 32-byte tile here and BG2 shares the same address as a
  # 64-byte 8bpp empty tile. Restore both halves of the shared blank.
  assert states[1][0xb400:0xb440]==bytes(64)
  st[0xb400:0xb440]=bytes(64)
  new,_,_=arm.run(st,bytes(child),[(c['index'],c['x'],c['y'],c['tile']) for c in page])
  # The corrected glyph destination intervals cannot overlap one another.
  assert all(a['tile_end']<=b['tile'] for a,b in zip(page,page[1:]))
  # Captured map equality proves we reconstructed the real scene, including
  # the original allocator collisions, rather than choosing synthetic x/y.
  assert old[0xf000:0xf800]==states[n][0xf000:0xf800],('map reproduction mismatch',n)
  assert old[0x9000:0xb400]==states[n][0x9000:0xb400],('glyph VRAM reproduction mismatch',n)
  used_end=max(c['old_tile'] for c in page)+128
  before=native_composite(old);after=native_composite(new)
  before.resize((960,640),Image.Resampling.NEAREST).save(OUT/f'ss{n}_arm_before.png');after.resize((960,640),Image.Resampling.NEAREST).save(OUT/f'ss{n}_arm_after.png')
  (OUT/f'ss{n}_arm_after.bin').write_bytes(new)
  proofs.append(dict(state=n,first_index=first,original_bg0_map_exact=True,original_glyph_vram_exact=True,draws=page))
  panel=Image.new('RGB',(480,160));panel.paste(before,(0,0));panel.paste(after,(240,0));comparisons.append(panel)
 sheet=Image.new('RGB',(960,len(comparisons)*320))
 for i,im in enumerate(comparisons):sheet.paste(im.resize((960,320),Image.Resampling.NEAREST),(0,i*320))
 sheet.save(OUT/'seven_states_before_after.png')
 changed={i for i,(a,b) in enumerate(zip(parent,child)) if a!=b};assert changed<=allowed
 identity=merged['identity'];identity['parent_translation_overlay_identity_sha256']=identity.get('translation_overlay_identity_sha256');identity['translation_overlay_identity_sha256']=digest(support['lines']);merged['summary']['translation_overlay_identity_sha256']=identity['translation_overlay_identity_sha256']
 snapshot=ROOT/'analysis/ggen_advance_translation_merged_20260912_credits_layout.json';snapshot.write_text(json.dumps(merged,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 report=dict(parent_sha256=sha(parent),output=dict(path=str(path.relative_to(ROOT)),size=len(child),sha256=sha(child)),changed_bytes=len(changed),pages=pages,verification=dict(result='PASS',runtime='Unicorn actual credit renderer with immediate DMA model; exact script arguments, not full game playback',all_pages=checks,seven_states=proofs,all_text_in_screen=True,no_text_rectangle_overlaps=True,no_glyph_tile_overlaps=True,native_blank_tile_preserved=True,original_state_bg0_map_exact=True),translation_snapshot=str(snapshot.relative_to(ROOT)))
 (OUT/'manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps(dict(output=report['output'],pages=len(pages),calls=sum(map(len,pages)),changed_bytes=len(changed)),ensure_ascii=False))
if __name__=='__main__':main()
