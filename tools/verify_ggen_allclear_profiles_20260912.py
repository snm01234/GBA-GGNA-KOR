"""Verify resource ownership and reconstruct the four screens from patched ROM data.

These PNGs are deterministic VRAM/font reconstructions, not emulator captures.
"""
import json,pickle,struct
from pathlib import Path
from PIL import Image
import build_ggen_allclear_profiles_ko_20260912 as build
import analyze_ggen_advance_unit_list_sprite_state_20260830 as sf
import analyze_ggen_advance_intermission_cycle_states_20260830 as bg
import render_ggen_ss_tiles_20260905 as renderer
import build_ggen_advance_ko_poc as fo
import ggen_advance_text_codec as codec
import ggen_advance_painted_glyph_identity as glyph
ROOT=build.ROOT;OUT=build.OUT
def u16(b,o):return struct.unpack_from('<H',b,o)[0]
def put16(b,o,v):struct.pack_into('<H',b,o,v)
def main():
 data=pickle.load((OUT/'reconstruction.pkl').open('rb'));report=json.loads((OUT/'manifest.json').read_text(encoding='utf-8'));rom=(ROOT/report['output']['path']).read_bytes()
 assert build.sha(rom)==report['output']['sha256']
 for row in report['graphics']:
  o=int(row['target'],16);m=data['new'][int(row['source'],16)];gr=u16(rom,o+8);size=u16(rom,o+10)
  assert u16(rom,o)==0xa and rom[o+gr:o+gr+size]==m['gfx']
  assert list(struct.unpack_from(f"<{len(m['cells'])}H",rom,o+16))==m['cells']
  for owner in row['owners']:assert struct.unpack_from('<I',rom,int(owner,16))[0]==build.BASE+o
 renderer.OUT=OUT
 proofs=[];frames=[]
 for n in range(1,5):
  original,_=sf.parse_png_state(ROOT/f'SD Gundam GGeneration Advance (Korean)_allclear.ss{n}');st=bytearray(original)
  def load(o,layer,x,y,base,paladd):
   old=data['old'][o];new=data['new'][o];info=bg.bg_info(st,layer);cb=info['char_base'];dest=0x1000+cb+base*32
   assert original[dest:dest+len(old['gfx'])]==old['gfx'],(n,hex(o),'source VRAM mismatch')
   if old['height']==2:
    for yy in range(old['height']):
     for xx in range(old['width']):
      c=old['cells'][yy*old['width']+xx];expected=((c&1023)+base)|(c&0xc00)|(((c>>12)+paladd)&15)<<12
      actual=bg.map_entry(original[0x1000:0x19000],info['screen_base'],info['size'],x+xx,y+yy)
      assert actual==expected,(n,hex(o),x+xx,y+yy,hex(actual),hex(expected))
   proofs.append(dict(state=n,source=hex(o),vram=hex(0x6000000+cb+base*32),bytes=len(old['gfx']),exact=True))
   st[dest:dest+len(new['gfx'])]=new['gfx']
   for yy in range(old['height']):
    for xx in range(old['width']):
     i=yy*old['width']+xx;c=new['cells'][i];v=((c&1023)+base)|(c&0xc00)|(((c>>12)+paladd)&15)<<12
     off=0x1000+info['screen_base']+((y+yy)*32+x+xx)*2;put16(st,off,v)
  if n==1:load(0xcc1558,2,0,0,0,11)
  if n in (2,3):
   load(0xcc1d70,2,0,0,0,11);load(0xcc2a80 if n==2 else 0xcc2d04,2,7,1,255,11)
   # Native D594B0 coordinates: W-row at x=9,y=9; A-row at x=1,y=6.
   load(0xcc4188 if n==2 else 0xcc496c,1,1 if n==2 else 9,6 if n==2 else 9,0x2e4,11)
  if n==4:
   load(0xcc055c,2,0,0,0,11)
   assert original[0x11000+200*32:0x11000+208*32]==(ROOT/'SD Gundam GGeneration Advance (Japan).gba').read_bytes()[0xcbfba8:0xcbfca8]
   st[0x11000+200*32:0x11000+208*32]=rom[0xcbfba8:0xcbfca8]
  rows=[]
  if n==1:rows=[(row,24,40+i*16,200,1) for i,row in enumerate([r for r in report['texts'] if r['kind']=='bgm'][:7])]
  if n==2:rows=[(row,120,40+i*16,112,1) for i,row in enumerate([r for r in report['texts'] if r['kind']=='character_short_name'][:7])]
  if n==3:rows=[(next(r for r in report['texts'] if r['kind']=='empty_group'),120,40,112,3)]
  if n==4:rows=[(next(r for r in report['texts'] if r['kind']=='profile_description'),8,72,224,1)]
  info=bg.bg_info(st,0);screen=0x1000+info['screen_base']
  for row,x,y,width,color in rows:
   for ty in range(y//8,y//8+2):
    for tx in range(x//8,(x+width)//8):put16(st,screen+(ty*32+tx)*2,0x2ff)
  used={0x2ff}|set(range(0x2e4,0x300))
  for l in (0,1):
   inf=bg.bg_info(st,l)
   for y in range(20):
    for x in range(30):used.add(bg.map_entry(st[0x1000:0x19000],inf['screen_base'],inf['size'],x,y)&1023)
  free=iter(i for i in range(0x2e4) if i not in used)
  for row,x,y,width,color in rows:
   ptr=struct.unpack_from('<I',rom,int(row['owner'],16))[0];assert ptr==int(row['pointer'],16)
   tokens,raw=codec.read_tokens(rom,ptr-build.BASE);assert raw.hex()==row['encoded_hex'];slots=[codec.normalized_slot(t) for t in tokens]
   mode=row['mode'];advance=8 if mode==8 else 12;assert len(slots)*advance<=width
   canvas=Image.new('L',(width,16));fontbase=glyph.FONT8_RELOCATED if mode==8 else glyph.FONT12_RELOCATED;stride=32 if mode==8 else 18
   for j,slot in enumerate(slots):
    b=rom[fontbase+slot*stride:fontbase+(slot+1)*stride];mask=fo.unpack_8x16(b) if mode==8 else fo.unpack_12x12(b)
    canvas.paste(color,(j*advance,0,j*advance+mask.width,mask.height),mask)
   for ty in range(2):
    for tx in range(width//8):
     tid=next(free);encoded=build.raster.encode_tile([[canvas.getpixel((tx*8+xx,ty*8+yy)) for xx in range(8)] for yy in range(8)])
     st[0x1000+tid*32:0x1000+(tid+1)*32]=encoded;put16(st,screen+((y//8+ty)*32+x//8+tx)*2,0xb000|tid)
  frame=renderer.render(st);frame.resize((960,640),Image.Resampling.NEAREST).save(OUT/f'ss{n}_reconstructed.png');frames.append(frame)
  (OUT/f'ss{n}_reconstructed_vram.bin').write_bytes(st)
 sheet=Image.new('RGB',(960,640))
 for n,im in enumerate(frames):sheet.paste(im.resize((480,320),Image.Resampling.NEAREST),((n%2)*480,(n//2)*320))
 sheet.save(OUT/'four_screens_reconstructed.png')
 # All Hangul payloads refer to the intended physical glyph; metadata alone is insufficient.
 for row in report['texts']:
  mode=row['mode'];font=glyph.load_galmuri8() if mode==8 else glyph.load_galmuri12();packer=glyph.packed_8x16 if mode==8 else glyph.packed_12x12;base=glyph.FONT8_RELOCATED if mode==8 else glyph.FONT12_RELOCATED;stride=32 if mode==8 else 18
  slots=[codec.normalized_slot(t) for t in codec.read_tokens(bytes.fromhex(row['encoded_hex']),0)[0]]
  assert len(slots)==len(row['ko'])
  for char,slot in zip(row['ko'],slots):
   if '가'<=char<='힣':assert rom[base+slot*stride:base+(slot+1)*stride]==packer(char,font)
 report['verification'].update(source_resource_vram_exact=proofs,all_hangul_physical_glyphs_verified=True,screen_reconstruction='four_screens_reconstructed.png',runtime='Headless SDL mGBA did not open its GDB listener; deterministic ROM/VRAM reconstruction used.')
 (OUT/'manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print('PASS: exact original VRAM ownership, resource roundtrips, font identities, four screen reconstructions')
if __name__=='__main__':main()

