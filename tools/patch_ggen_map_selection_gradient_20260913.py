"""Restore the map-selection title gradient, then paint Korean bitmap text."""
import json,struct
from pathlib import Path
from PIL import Image
from zipfile import ZipFile
import build_ggen_allclear_profiles_ko_20260912 as assets
import analyze_ggen_advance_intermission_cycle_states_20260830 as bg
import render_ggen_ss_tiles_20260905 as renderer
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs/20260913_ss1_gradient'
EXPECTED='729fb5474dd98d7c8b9ecb81368049bf92e6862fd4cae0f420b584a098f7a3f3'
SOURCE=0xcc0e54;DEST=0x13d4000;BOX=(6,4,68,19)
def main():
 OUT.mkdir(parents=True,exist_ok=True);path=ROOT/'SD Gundam GGeneration Advance (Korean).gba';parent=path.read_bytes();assert assets.sha(parent)==EXPECTED
 statepath=path.with_suffix('.ss1');statehash=assets.sha(statepath.read_bytes());state,_=assets.sf.parse_png_state(statepath)
 meta,old=assets.resource(parent,SOURCE);clean=old.copy();gradient=[]
 # Samples on both sides of the title agree at every scanline. Entire glyph
 # face and shadow area is replaced, rather than partially erasing ink pixels.
 for y in range(BOX[1],BOX[3]):
  value=old.getpixel((4,y));assert value==old.getpixel((68,y));gradient.append(value)
  clean.paste(value,(BOX[0],y,BOX[2],y+1))
 for y in range(BOX[1],BOX[3]):
  assert all(clean.getpixel((x,y))==gradient[y-BOX[1]] for x in range(BOX[0],BOX[2]))
 new=clean.copy()
 with ZipFile(ROOT/'assets/fonts/Galmuri.zip') as z:font=assets.BdfFont.from_bytes(z.read('Galmuri11.bdf'),'Galmuri11')
 assets.paint(new,'맵 선택',BOX,font,cell=12,face=11,outline=2)
 for y in range(old.height):
  for x in range(old.width):
   if not(BOX[0]<=x<BOX[2] and BOX[1]<=y<BOX[3]):assert old.getpixel((x,y))==new.getpixel((x,y))
 blob,rebuild=assets.rebuilt_resource(parent,meta,new);assert DEST+len(blob)<0x13d8000 and not any(parent[DEST:DEST+len(blob)])
 owners=[i for i in range(0,len(parent)-4,4) if parent[i:i+4]==struct.pack('<I',0x8000000+SOURCE)];assert owners==[0x6b6c0,0x7ad14]
 cand=bytearray(parent);cand[DEST:DEST+len(blob)]=blob;allowed=set(range(DEST,DEST+len(blob)))
 for owner in owners:struct.pack_into('<I',cand,owner,0x8000000+DEST);allowed.update(range(owner,owner+4))
 assert bytes(v for line in assets.sem.stitch(rebuild['gfx'],rebuild) for v in line)==new.tobytes()
 assert cand[SOURCE:SOURCE+meta['gr']+meta['size']]==parent[SOURCE:SOURCE+meta['gr']+meta['size']]
 changed={i for i,(a,b) in enumerate(zip(parent,cand)) if a!=b};assert changed<=allowed
 # Bind the complete background resource to the actual captured VRAM/map.
 info=bg.bg_info(state,2);assert info['char_base']==0x8000 and info['scroll_x']==info['scroll_y']==0
 gfxstart=0x1000+info['char_base'];assert state[gfxstart:gfxstart+len(meta['gfx'])]==meta['gfx']
 runtime=bytearray(state);runtime[gfxstart:gfxstart+len(rebuild['gfx'])]=rebuild['gfx']
 for y in range(meta['height']):
  for x in range(meta['width']):
   i=y*meta['width']+x;off=0x1000+info['screen_base']+(y*32+x)*2;oldentry=struct.unpack_from('<H',state,off)[0]
   assert (oldentry&0xfff)==(meta['cells'][i]&0xfff),(x,y,hex(oldentry),hex(meta['cells'][i]))
   struct.pack_into('<H',runtime,off,(oldentry&0xf000)|(rebuild['cells'][i]&0xfff))
 renderer.OUT=OUT;before=renderer.render(state);after=renderer.render(runtime)
 for y in range(160):
  for x in range(240):
   if not(BOX[0]<=x<BOX[2] and BOX[1]<=y<BOX[3]):assert before.getpixel((x,y))==after.getpixel((x,y))
 after.resize((960,640),Image.Resampling.NEAREST).save(OUT/'after_reconstructed.png')
 comp=Image.new('RGB',(960,1280));comp.paste(before.resize((960,640),Image.Resampling.NEAREST),(0,0));comp.paste(after.resize((960,640),Image.Resampling.NEAREST),(0,640));comp.save(OUT/'before_after.png')
 pal=state[0x800+15*32:0x800+16*32];palette=assets.raster.palette_rgb(pal);strip=Image.new('RGB',(384,3*96))
 for i,im in enumerate([old,clean,new]):
  crop=im.crop((0,0,96,24));rgb=assets.raster.render_canvas([[crop.getpixel((x,y)) for x in range(96)] for y in range(24)],palette)
  strip.paste(rgb.resize((384,96),Image.Resampling.NEAREST),(0,i*96))
 strip.save(OUT/'title_restore_steps.png')
 assert assets.sha(statepath.read_bytes())==statehash
 out=OUT/'ggen_map_selection_gradient_20260913.gba';out.write_bytes(cand)
 report=dict(parent_sha256=EXPECTED,output=dict(path=out.relative_to(ROOT).as_posix(),sha256=assets.sha(cand),size=len(cand)),source_resource=hex(SOURCE),new_resource=hex(DEST),owners=[hex(o) for o in owners],translation='맵 선택',gradient=gradient,clear_box=BOX,changed_bytes=len(changed),source_state_sha256=statehash,verification=dict(result='PASS',gradient_samples_agree=True,full_japanese_ink_and_shadow_region_cleared=True,resource_roundtrip=True,captured_vram_and_600_map_cells_exact=True,outside_title_pixels_unchanged=True,unrelated_rom_bytes_preserved=True,savestate_unchanged=True,runtime='ROM/VRAM reconstruction; not live emulator playback'))
 (OUT/'manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(report,ensure_ascii=True))
if __name__=='__main__':main()
