"""Restore native green behind both profile appearance badges."""
import json,struct,hashlib,shutil
from pathlib import Path
from zipfile import ZipFile
from PIL import Image
import build_ggen_allclear_profiles_ko_20260912 as base
import render_ggen_ss_tiles_20260905 as render
ROOT=base.ROOT;OUT=ROOT/'outputs/20260912_profile_badges_green'
sha=lambda b:hashlib.sha256(b).hexdigest()
def unpack_current(rom,o):
 if struct.unpack_from('<H',rom,o)[0]==0x1a:return base.resource(rom,o)
 kind,w,h,mr,unused,gr,size,pr,reserved=struct.unpack_from('<HBB6H',rom,o);assert kind==0xa
 m=dict(offset=o,width=w,height=h,cells=list(struct.unpack_from(f'<{w*h}H',rom,o+16)),gfx=rom[o+gr:o+gr+size],gr=gr,size=size)
 c=base.sem.stitch(m['gfx'],m);im=Image.new('L',(w*8,h*8));im.putdata([v for row in c for v in row]);return m,im
def main():
 OUT.mkdir(exist_ok=True);render.OUT=OUT
 path=ROOT/'SD Gundam GGeneration Advance (Korean).gba';parent=path.read_bytes();jp=(ROOT/'SD Gundam GGeneration Advance (Japan).gba').read_bytes()
 manifest=json.loads((ROOT/'integrated/main_tip/ggen_advance_main_tip_manifest.json').read_text(encoding='utf-8'));assert sha(parent)==manifest['sha256']
 prior=json.loads((ROOT/'outputs/20260912_allclear_profiles_ko/manifest.json').read_text(encoding='utf-8'))
 unit=int(next(r for r in prior['graphics'] if r['source']=='0xcc055c')['target'],16)
 child=bytearray(parent);allowed=set();cursor=0x13c0000;assert not any(parent[cursor:0x13c8000]);rows=[];previews=[]
 with ZipFile(ROOT/'assets/fonts/Galmuri.zip') as z:font=base.BdfFont.from_bytes(z.read('Galmuri11.bdf'),'Galmuri11')
 for name,source,current,roi,box,ink,outline,n,paladd in [
  ('unit',0xcc055c,unit,(64,29,118,45),(67,29,117,45),{5,11},5,4,11),
  ('character',0xcbfd08,0xcbfd08,(56,29,109,45),(58,29,108,45),{2,11},2,5,11)]:
  native,clean=base.resource(jp,source);old,before=unpack_current(parent,current)
  # Start with native pixels, including the green bevel damaged by the old box fill.
  original=clean.copy();x0,y0,x1,y1=roi
  erased=[]
  for y in range(y0,y1):
   for x in range(x0,x1):
    if clean.getpixel((x,y)) in ink:clean.putpixel((x,y),15);erased.append((x,y))
  after=clean.copy();base.paint(after,'등장작품',box,font,12,11,outline)
  # Brown is permitted only within one pixel of the new Korean face.
  face={(x,y) for y in range(y0,y1) for x in range(x0,x1) if after.getpixel((x,y))==11}
  ring={(x+dx,y+dy) for x,y in face for dx in (-1,0,1) for dy in (-1,0,1)}-face
  brown={(x,y) for y in range(y0,y1) for x in range(x0,x1) if after.getpixel((x,y))==outline}
  assert brown and brown<=ring
  for y in range(after.height):
   for x in range(after.width):
    if not(x0<=x<x1 and y0<=y<y1):assert after.getpixel((x,y))==before.getpixel((x,y))
    elif (x,y) not in face|ring:assert after.getpixel((x,y))==clean.getpixel((x,y))
  blob,new=base.rebuilt_resource(jp,native,after);cursor=(cursor+3)&~3;assert cursor+len(blob)<=0x13c8000
  owners=[];p=parent.find(struct.pack('<I',base.BASE+current))
  while p>=0:assert p%4==0;owners.append(p);p=parent.find(struct.pack('<I',base.BASE+current),p+1)
  assert owners
  child[cursor:cursor+len(blob)]=blob;allowed.update(range(cursor,cursor+len(blob)))
  for p in owners:struct.pack_into('<I',child,p,base.BASE+cursor);allowed.update(range(p,p+4))
  decoded,roundtrip=unpack_current(child,cursor);assert roundtrip.tobytes()==after.tobytes()
  source_state,_=base.sf.parse_png_state(ROOT/f'SD Gundam GGeneration Advance (Korean)_allclear.ss{n}')
  assert source_state[0x9000:0x9000+len(native['gfx'])]==native['gfx']
  # ss4 reference uses the already translated text reconstruction; ss5 uses supplied RAM.
  st=bytearray((ROOT/'outputs/20260912_allclear_profiles_ko/ss4_reconstructed_vram.bin').read_bytes() if n==4 else source_state)
  st[0x9000:0x9000+len(new['gfx'])]=new['gfx']
  for yy in range(new['height']):
   for xx in range(new['width']):
    c=new['cells'][yy*new['width']+xx];v=(c&0xfff)|((((c>>12)+paladd)&15)<<12);struct.pack_into('<H',st,0x1000+0xe800+(yy*32+xx)*2,v)
  frame=render.render(st);frame.resize((960,640),Image.Resampling.NEAREST).save(OUT/f'ss{n}_reconstructed.png');previews.append(frame)
  # Pixel comparison in each actual palette, at 8x for review.
  bank=11 if n==4 else 15;pal=base.raster.palette_rgb(source_state[0x800+bank*32:0x800+(bank+1)*32])
  panel=Image.new('RGB',(54*8,16*8*3))
  for k,im in enumerate((original,before,after)):
   crop=im.crop((x0,y0,x0+54,y0+16));rgb=Image.new('RGB',crop.size);rgb.putdata([pal[v] for v in crop.getdata()]);panel.paste(rgb.resize((432,128),Image.Resampling.NEAREST),(0,k*128))
  panel.save(OUT/f'{name}_native_before_after.png')
  rows.append(dict(name=name,source=hex(source),previous=hex(current),target=hex(cursor),owners=[hex(p) for p in owners],native_state=n,native_graphics_exact=True,erased_japanese_pixels=len(erased),korean_face_pixels=len(face),brown_outline_pixels=len(brown),brown_only_one_pixel_outline=True,unrelated_pixels_unchanged=True))
  cursor+=len(blob)
 changed={i for i,(a,b) in enumerate(zip(parent,child)) if a!=b};assert changed<=allowed
 out=OUT/'ggen_profile_badges_green_20260912.gba';out.write_bytes(child)
 sheet=Image.new('RGB',(960,320))
 for i,im in enumerate(previews):sheet.paste(im.resize((480,320),Image.Resampling.NEAREST),(480*i,0))
 sheet.save(OUT/'both_screens_reconstructed.png')
 report=dict(parent_sha256=sha(parent),output=dict(path=str(out.relative_to(ROOT)),size=len(child),sha256=sha(child)),badges=rows,changed_bytes=len(changed),verification=dict(result='PASS',roundtrip=True,native_green_preserved=True,brown_only_glyph_outline=True,unrelated_rom_bytes_preserved=True,runtime='Deterministic ROM/VRAM reconstruction; no emulator execution.'))
 (OUT/'manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
