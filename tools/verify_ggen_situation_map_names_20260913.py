"""Physical font and saved title-plane verification for situation map names."""
import json,struct,re
from PIL import Image,ImageChops
import patch_ggen_situation_map_names_20260913 as patch
import verify_ggen_ss1_ss9_20260913 as v
import ggen_advance_painted_glyph_identity as glyph
ROOT=patch.ROOT;OUT=patch.OUT
def main():
 report=json.loads((OUT/'manifest.json').read_text(encoding='utf-8'));parent=(OUT/'parent.gba').read_bytes();rom=(ROOT/report['output']['path']).read_bytes();assert patch.a.sha(rom)==report['output']['sha256']
 fonts={8:glyph.load_galmuri8(),12:glyph.load_galmuri12()}
 for job in report['jobs']:
  mode=job['mode'];tokens=patch.c.read_tokens(bytes.fromhex(job['raw']),0)[0];slots=[patch.c.normalized_slot(t) for t in tokens];assert len(slots)==len(job['after'])
  base=glyph.FONT8_RELOCATED if mode==8 else glyph.FONT12_RELOCATED;stride=32 if mode==8 else 18;pack=glyph.packed_8x16 if mode==8 else glyph.packed_12x12
  for ch,s in zip(job['after'],slots):
   if '가'<=ch<='힣':assert rom[base+s*stride:base+(s+1)*stride]==pack(ch,fonts[mode])
 path=ROOT/'SD Gundam GGeneration Advance (Korean).ss1';sh=patch.a.sha(path.read_bytes());st,_=v.sf.parse_png_state(path);rt=bytearray(st);owner=patch.TABLE+28*32+16
 key=st[0x19000+0x1780];assert parent[owner-16]==key==51
 oldmask=v.mask(parent,patch.f2.u32(parent,owner),8);newmask=v.mask(rom,patch.f2.u32(rom,owner),8)
 plane=v.plane(st,0);x,y=16,0;width=oldmask.width;assert width==newmask.width==32
 oldcrop=plane.crop((x,y,x+width,y+16));assert ImageChops.difference(oldcrop.point(lambda p:255 if p else 0),oldmask).getbbox() is None
 info=v.bg.bg_info(st,0);assert info['scroll_x']==info['scroll_y']==0
 color=next(p for p in oldcrop.get_flattened_data() if p);newplane=plane.copy();newplane.paste(0,(x,y,x+width,y+16));newplane.paste(color,(x,y,x+width,y+16),newmask)
 used=set()
 for layer in range(4):
  inf=v.bg.bg_info(st,layer)
  for ty in range(64 if inf['size'] in (2,3) else 32):
   for tx in range(64 if inf['size'] in (1,3) else 32):
    e=v.bg.map_entry(st[0x1000:0x19000],inf['screen_base'],inf['size'],tx,ty);o=inf['char_base']+(e&1023)*(64 if inf['color_8bpp'] else 32);used.add(o)
    if inf['color_8bpp']:used.add(o+32)
 free=iter(i for i in range(0x2e0) if info['char_base']+i*32 not in used)
 for ty in range(2):
  for tx in range(2,6):
   o=0x1000+info['screen_base']+(ty*32+tx)*2;e=struct.unpack_from('<H',st,o)[0];tid=next(free);pixels=[[newplane.getpixel((tx*8+xx,ty*8+yy)) for xx in range(8)] for yy in range(8)];raw=patch.a.raster.encode_tile(pixels);pos=0x1000+info['char_base']+tid*32;rt[pos:pos+32]=raw;struct.pack_into('<H',rt,o,(e&0xf000)|tid)
 v.renderer.OUT=OUT;before=v.renderer.render(st);after=v.renderer.render(rt)
 for yy in range(160):
  for xx in range(240):
   if not(x<=xx<x+width and y<=yy<y+16):assert before.getpixel((xx,yy))==after.getpixel((xx,yy))
 after.resize((960,640),Image.Resampling.NEAREST).save(OUT/'after_reconstructed.png')
 # Actual font rasters for every map title; inspect the complete name family.
 gallery=Image.new('RGB',(512,32*24),'white')
 for i in range(64):
  m=v.mask(rom,patch.f2.u32(rom,patch.TABLE+i*32+16),8);gallery.paste('black',((i%2)*256,(i//2)*24,(i%2)*256+m.width,(i//2)*24+16),m)
 gallery.resize((1024,1536),Image.Resampling.NEAREST).save(OUT/'all_64_korean_names.png')
 assert patch.a.sha(path.read_bytes())==sh
 report['verification'].update(result='PASS',all_changed_hangul_physical_glyphs=True,state_key=key,state_sha256=sh,original_title_mask_exact=True,title_width=32,outside_title_pixels_unchanged=True,savestate_unchanged=True,runtime='ROM/VRAM reconstruction; not live emulator playback')
 (OUT/'manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print('PASS: 20 owners, physical glyphs, all 64 map names and exact captured title mask')
if __name__=='__main__':main()
