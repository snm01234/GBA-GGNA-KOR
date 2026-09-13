"""Verify physical glyphs and reconstruct captured VRAM using ROM-owned data.

These are deterministic graphics-memory reconstructions, not mGBA captures.
"""
import json,struct
import re
from pathlib import Path
from PIL import Image,ImageChops
import patch_ggen_ss1_ss9_20260912 as patch
import patch_ggen_profile_followup2_20260912 as f2
import ggen_advance_text_codec as codec
import build_ggen_advance_ko_poc as fo
import ggen_advance_painted_glyph_identity as glyph
import analyze_ggen_advance_unit_list_sprite_state_20260830 as sf
import analyze_ggen_advance_intermission_cycle_states_20260830 as bg
import render_ggen_ss_tiles_20260905 as renderer
ROOT=patch.ROOT;OUT=patch.OUT
def mask(rom,ptr,mode):
 d=codec.load_dictionary(rom,codec.DICT_8X16_BASE if mode==8 else codec.DICT_12X12_BASE,codec.DICT_8X16_END if mode==8 else codec.DICT_12X12_END)
 slots=codec.expand_to_slots(codec.read_tokens(rom,ptr-0x8000000)[0],d)
 im=Image.new('L',(len(slots)*mode,16));base=glyph.FONT8_RELOCATED if mode==8 else glyph.FONT12_RELOCATED;stride=32 if mode==8 else 18
 for i,s in enumerate(slots):
  raw=rom[base+s*stride:base+(s+1)*stride];m=fo.unpack_8x16(raw) if mode==8 else fo.unpack_12x12(raw);im.paste(m,(i*mode,0))
 return im
def plane(st,layer=0):
 info=bg.bg_info(st,layer);assert not info['color_8bpp'];im=Image.new('L',(240,160));vram=st[0x1000:0x19000]
 for y in range(160):
  for x in range(240):
   xx=x+info['scroll_x'];yy=y+info['scroll_y'];e=bg.map_entry(vram,info['screen_base'],info['size'],xx//8,yy//8);px=xx%8;py=yy%8
   if e&0x400:px=7-px
   if e&0x800:py=7-py
   b=vram[info['char_base']+(e&1023)*32+py*4+px//2];im.putpixel((x,y),(b>>(4*(px%2)))&15)
 return im
def main():
 report=json.loads((OUT/'manifest.json').read_text(encoding='utf-8'));rom=(ROOT/report['output']['path']).read_bytes();parent=(OUT/'parent.gba').read_bytes()
 assert patch.sha(rom)==report['output']['sha256'];assert patch.sha(parent)==report['parent_sha256']
 # Unfocused buttons, cancel and unrelated animations must remain byte-identical.
 catalog=patch.cat.enumerate_buttons((ROOT/'SD Gundam GGeneration Advance (Japan).gba').read_bytes());unchanged=0
 for spec in patch.cat.PACKAGES:
  addr=0x8000000+patch.btn.CLONES[spec['name']]
  oldh=patch.btn.analysis.parse_resource_header(parent,addr);newh=patch.btn.analysis.parse_resource_header(rom,addr)
  _,oldr=patch.btn.sprite.animation_records(parent,addr);_,newr=patch.btn.sprite.animation_records(rom,addr)
  assert oldh['palettes']==newh['palettes']
  for row in catalog:
   if row['package']!=spec['name'] or (row['kind']=='64' and row['face']==12 and row['ko']!='캔슬'):continue
   op,oi,_=patch.cat.parse_anim(oldr,row['anim']);np,ni,_=patch.cat.parse_anim(newr,row['anim'])
   assert patch.btn.analysis.stitch(oldh['graphics'],op,oi,list(row['objects']))==patch.btn.analysis.stitch(newh['graphics'],np,ni,list(row['objects']))
   unchanged+=1
 fonts={8:glyph.load_galmuri8(),12:glyph.load_galmuri12()}
 for j in report['texts']:
  mode=j['mode'];raw=bytes.fromhex(j['raw']);slots=[codec.normalized_slot(t) for t in codec.read_tokens(raw,0)[0]]
  chars=re.findall(r'<[0-9A-Fa-f]{4}>|.',j['after']);assert len(chars)==len(slots)
  base=glyph.FONT8_RELOCATED if mode==8 else glyph.FONT12_RELOCATED;stride=32 if mode==8 else 18;packer=glyph.packed_8x16 if mode==8 else glyph.packed_12x12
  for ch,s in zip(chars,slots):
   if len(ch)==1 and '가'<=ch<='힣':assert rom[base+s*stride:base+(s+1)*stride]==packer(ch,fonts[mode])
 jobs={int(j['owner'],16):j for j in report['texts']};renderer.OUT=OUT;frames=[];proofs=[]
 targets={1:(0x1ac45c,56,8,176),2:(0x1b4a38,8,104,224),3:(0x1b019c,72,8,160),4:(0xfce3c4,112,64,120),9:(0x1c8780,144,128,88)}
 for n in range(1,10):
  path=ROOT/f'SD Gundam GGeneration Advance (Korean).ss{n}';st,_=sf.parse_png_state(path);st=bytearray(st);source_hash=patch.sha(path.read_bytes())
  if n in targets:
   owner,gx,gy,width=targets[n]
   if n==9:
    # Find the P-defender row by matching the captured leading sentence.
    owner=next(o for o,j in jobs.items() if j['before']=='모든 사격 공격을 막는다')
   job=jobs[owner];mode=job['mode'];before=mask(parent,f2.u32(parent,owner),mode);after=mask(rom,f2.u32(rom,owner),mode)
   layer=2 if n==9 else 0;actual=plane(st,layer);binary=actual.point(lambda v:255 if v else 0)
   best=(10**9,None)
   for y in range(max(0,gy-8),min(145,gy+9)):
    for x in range(max(0,gx-8),min(240-width+1,gx+9)):
     w=min(before.width,width);test=before.crop((0,0,w,16));diff=ImageChops.difference(test,binary.crop((x,y,x+w,y+16)));score=sum(diff.histogram()[1:])
     if score<best[0]:best=(score,(x,y))
   print('ss',n,'mask',before.size,'best',best,flush=True)
   assert best[0]==0,(n,best)
   x,y=best[1];assert after.width<=width,(n,after.width,width)
   # Paint only the proven text rectangle into fresh unreferenced tiles.
   info=bg.bg_info(st,layer);assert info['scroll_x']==0 and info['scroll_y']==0
   color=next(v for v in actual.crop((x,y,x+min(width,before.width),y+16)).get_flattened_data() if v)
   palette=bg.map_entry(st[0x1000:0x19000],info['screen_base'],info['size'],x//8,y//8)&0xf000
   newplane=actual.copy();newplane.paste(0,(x,y,x+width,y+16));newplane.paste(color,(x,y,x+after.width,y+16),after)
   used=set()
   for l in range(4):
    inf=bg.bg_info(st,l)
    for ty in range(64 if inf['size'] in (2,3) else 32):
     for tx in range(64 if inf['size'] in (1,3) else 32):
      e=bg.map_entry(st[0x1000:0x19000],inf['screen_base'],inf['size'],tx,ty)
      physical=inf['char_base']+(e&1023)*(64 if inf['color_8bpp'] else 32)
      used.add(physical);used.add(physical+32) if inf['color_8bpp'] else None
   free=iter(i for i in range(0x2e0) if info['char_base']+i*32 not in used)
   for ty in range(y//8,(y+15)//8+1):
    for tx in range(x//8,(x+width-1)//8+1):
     off=0x1000+info['screen_base']+(ty*32+tx)*2;e=struct.unpack_from('<H',st,off)[0];tid=next(free)
     tile=[[newplane.getpixel((tx*8+xx,ty*8+yy)) for xx in range(8)] for yy in range(8)]
     raw=patch.btn.tileops.encode_tile(tile);p=0x1000+info['char_base']+tid*32;st[p:p+32]=raw;struct.pack_into('<H',st,off,palette|tid)
   assert plane(st,layer).crop((x,y,x+width,y+16))==newplane.crop((x,y,x+width,y+16))
   proofs.append(dict(state=n,kind='text',old_mask_exact=True,x=x,y=y,width=width,new_width=after.width,owner=hex(owner)))
  else:
   label={5:'분해실행',6:'강화실행',7:'보급실행',8:'처분실행'}[n];job=next(j for j in report['buttons'] if j['ko']==label)
   for piece in job['pieces']:
    old=bytes.fromhex(piece['old']);new=bytes.fromhex(piece['new']);hits=[];pos=0x11000
    while True:
     pos=st.find(old,pos,0x19000)
     if pos<0:break
     hits.append(pos);pos+=len(old)
    assert len(hits)==1,(n,hits)
    st[hits[0]:hits[0]+len(new)]=new;proofs.append(dict(state=n,kind='button_obj',old_tiles_exact=True,offset=hex(hits[0]),bytes=len(old)))
  frame=renderer.render(st);frame.resize((960,640),Image.Resampling.NEAREST).save(OUT/f'ss{n}_reconstructed.png');frames.append(frame)
  assert patch.sha(path.read_bytes())==source_hash
 sheet=Image.new('RGB',(1440,960))
 for i,im in enumerate(frames):sheet.paste(im.resize((480,320),Image.Resampling.NEAREST),((i%3)*480,(i//3)*320))
 sheet.save(OUT/'ss1_ss9_reconstructed.png')
 report['verification'].update(result='PASS',state_proofs=proofs,savestates_unchanged=True,unchanged_button_variants=unchanged,all_text_physical_glyphs_verified=True,runtime='Not executed in emulator; source glyph masks and OBJ tiles matched captured VRAM, then reconstructed from candidate ROM.')
 (OUT/'manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
if __name__=='__main__':main()
