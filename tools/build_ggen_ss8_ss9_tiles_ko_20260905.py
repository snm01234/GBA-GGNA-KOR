"""Settlement bars and gradient level-up lettering, from measured ss8/ss9."""
from ggen_ss_tiles_common_20260905 import *
import analyze_ggen_advance_intermission_cycle_states_20260830 as bg
import analyze_ggen_advance_remaining_ui_draw_calls_20260902 as draw
import build_ggen_advance_status_ui_tile_overlay_poc as status
from build_ggen_ss1_ss4_tiles_ko_20260905 import paint
from ggen_advance_project_paths import FONT_ZIP,MAIN_TIP_MANIFEST
import test_ggen_advance_font_pair as fontpair
from zipfile import ZipFile
from collections import Counter
import json,hashlib,binascii,shutil
DEST=ROOT/'outputs/20260905_ggen_ss8_ss9_tiles'
RESULT=DEST/'ggen_ss8_ss9_tiles_ko_20260905.gba'
def sha(b):return hashlib.sha256(b).hexdigest()
def spaced_ink(font,text,gap):
 result=set();cursor=0;height=0
 for ch in text:
  pts,w,h=raster.native_ink(font,ch);result|={(x+cursor,y) for x,y in pts};cursor+=w+gap;height=max(height,h)
 return result,cursor-gap,height
def main():
 parent=(ROOT/'SD Gundam GGeneration Advance (Korean).gba').read_bytes();assert sha(parent)==json.loads(MAIN_TIP_MANIFEST.read_text(encoding='utf-8'))['sha256']
 out=bytearray(parent);DEST.mkdir(exist_ok=True);repl={};allowed=[];reports=[];items=[]
 with ZipFile(FONT_ZIP) as z:font=fontpair.load_bdf(z,'Galmuri11.bdf')
 states={n:statefmt.parse_png_state(ROOT/f'SD Gundam GGeneration Advance (Korean).ss{n}')[0] for n in (8,9)}
 st=states[8];screen,_=draw.layer_pixels(st,1);colors=raster.palette_rgb(st[0x9e0:0xa00])
 before=[[row[32:144] for row in screen[y:y+16]] for y in (16,40,64,88,112)]
 template=[];fills=[10,11,10,9,6,6,6,6,6,6,6,6,9,10,11,10]
 for y in range(16):
  row=[]
  for x in range(112):
   vals=[c[y][x] for c in before[:4] if c[y][x] not in (12,15)]
   row.append(Counter(vals).most_common(1)[0][0] if vals else fills[y])
  if y in (6,7,8,9):row[:6]=[11,10,9,8,7,6]
  template.append(row)
 oldoff=0xe6ea4;oldatlas=sem.lzss_decompress(parent[oldoff+4:oldoff+4+(u32(parent,oldoff)&65535)]);atlas=bytearray(oldatlas);desired={}
 def record(old,new):
  if old!=new:
   assert old not in repl or repl[old]==new
   repl[old]=new
 def screen_tiles(st,layer,old,new,box,handler):
  info=bg.bg_info(st,layer);v=st[0x1000:0x19000];x0,y0,x1,y1=box
  for ty in range(y0//8,(y1+7)//8):
   for tx in range(x0//8,(x1+7)//8):
    c=bg.map_entry(v,info['screen_base'],info['size'],tx,ty);assert not(c&0xc00)
    tile=[row[tx*8-x0:tx*8-x0+8] for row in new[ty*8-y0:ty*8-y0+8]]
    raw=raster.encode_tile(tile);oldraw=v[info['char_base']+(c&1023)*32:info['char_base']+(c&1023)*32+32]
    handler(c&1023,oldraw,raw,tx,ty)
 labels=['맵클리어EXP','이벤트보너스EXP','보급포인트','전함수리비용','획득아이템']
 for i,(y,text) in enumerate(zip((16,40,64,88,112),labels)):
  old=before[i];clean=[r[:] for r in old]
  for yy in range(16):
   for x in range(112):
    if old[yy][x] in (12,15):clean[yy][x]=template[yy][x+14 if i==4 and x>=64 else x]
  assert not any(v in (12,15) for row in clean for v in row)
  new=[r[:] for r in clean];ink,w,h=spaced_ink(font,text,0);assert w<=106
  pts={(x+3,y+2) for x,y in ink}
  for px,py in raster.dilate(pts,112,16):new[py][px]=12
  for px,py in pts:new[py][px]=15
  def apply(tid,oldraw,newraw,tx,ty):
   sid=tid-1;assert oldatlas[sid*32:(sid+1)*32]==oldraw
   desired[(tx,ty)]=newraw
  screen_tiles(st,1,old,new,(32,y,144,y+16),apply)
  reports.append({'text':text,'source_atlas':hex(oldoff),'screen_rect':[32,y,144,y+16],'face':15,'outline':12})
  for name,c in [('before',old),('clean',clean),('after',new)]:items.append((f'ss8 {i} {name}',raster.render_canvas(c,colors)))
 maps=[sem.parse_map(parent,p+0x8000000) for p in (0xe7894,0xe7d48,0xe7eb4)]
 protected=set();owned=set()
 for mi,m in enumerate(maps):
  for idx,c in enumerate(m['cells']):
   xy=(idx%m['width'],idx//m['width'])
   (owned if mi==0 and xy in desired else protected).add(c&1023)
 pool=sorted(owned-protected);lookup={oldatlas[k*32:(k+1)*32]:k for k in protected};bindings={}
 for xy,payload in desired.items():
  if payload not in lookup:
   assert pool,'no free target-owned source slot'
   sid=pool.pop(0);lookup[payload]=sid;atlas[sid*32:(sid+1)*32]=payload
  bindings[xy]=lookup[payload]
  x,y=xy;pos=0xe7894+4+(y*30+x)*2;cell=u16(parent,pos)
  struct.pack_into('<H',out,pos,(cell&0xfc00)|bindings[xy]);allowed.append((pos,pos+2))
 blob=status.literal_only_compress(bytes(atlas));clone=0x1f94000;assert not any(parent[clone:clone+len(blob)])
 assert raster.pointer_hits(parent,0x80e6ea4)==[0xe8020]
 out[clone:clone+len(blob)]=blob;allowed.append((clone,clone+len(blob)));struct.pack_into('<I',out,0xe8020,clone+0x8000000);allowed.append((0xe8020,0xe8024));assert sem.lzss_decompress(blob[4:])==atlas
 # Level-up title is raw graphics. Preserve the per-screen-row ink gradient.
 st=states[9];screen,_=draw.layer_pixels(st,2);old=[r[80:160] for r in screen[32:56]];clean=[r[:] for r in old]
 for y in range(5,20):
  for x in range(80):
   if clean[y][x] in range(3,14):clean[y][x]=14
 assert all(v==14 for row in clean[5:20] for v in row)
 new=[r[:] for r in clean];ink,w,h=spaced_ink(font,'레벨업!',2);x0=(80-w)//2;y0=6
 pts={(x+x0,y+y0) for x,y in ink};edge=raster.dilate(pts,80,24);shade={(x+1,y+1) for x,y in edge}
 for x,y in edge|shade:
  if 0<=x<80 and 0<=y<24:new[y][x]=12
 gradient={}
 for y in range(6,17):
  vals=[v for v in old[y] if v in range(5,12)];gradient[y]=Counter(vals).most_common(1)[0][0]
 for x,y in pts:new[y][x]=gradient[y]
 assert new[:5]==old[:5] and new[20:]==old[20:]
 def apply_raw(tid,oldraw,newraw,tx,ty):
  # Measured linear 12-tile stride beginning at live tile 0x1AE.
  pos=0xe3f4c+(tid-0x1ae)*32;assert parent[pos:pos+32]==oldraw
  if oldraw!=newraw:out[pos:pos+32]=newraw;allowed.append((pos,pos+32));record(oldraw,newraw)
 screen_tiles(st,2,old,new,(80,32,160,56),apply_raw)
 reports.append({'text':'레벨업!','face_gradient_by_local_y':gradient,'outline':12,'font':'Galmuri11','raw_start':'0xE3F4C'})
 for name,c in [('before',old),('clean',clean),('after',new)]:items.append((f'ss9 {name}',raster.render_canvas(c,colors)))
 mask=bytearray(len(out))
 for a,b in allowed:mask[a:b]=b'\1'*(b-a)
 assert all(mask[i] for i,(a,b) in enumerate(zip(parent,out)) if a!=b)
 RESULT.write_bytes(out);shutil.copy2(ROOT/'SD Gundam GGeneration Advance (Korean).sav',RESULT.with_suffix('.sav'))
 from render_ggen_ss_tiles_20260905 import render
 sr=[]
 for n,st in states.items():
  fixed=bytearray(st);hits=0
  for p in range(0x1000,0x19000,32):
   oldraw=st[p:p+32]
   if oldraw in repl:fixed[p:p+32]=repl[oldraw];hits+=1
  assert st[0x1020:0x1020+len(oldatlas)]==oldatlas
  fixed[0x1020:0x1020+len(atlas)]=atlas
  info=bg.bg_info(st,1)
  for (x,y),sid in bindings.items():
   pos=0x1000+info['screen_base']+(y*32+x)*2
   struct.pack_into('<H',fixed,pos,(u16(st,pos)&0xfc00)|(sid+1))
  struct.pack_into('<I',fixed,8,binascii.crc32(out)&0xffffffff)
  src=ROOT/f'SD Gundam GGeneration Advance (Korean).ss{n}';RESULT.with_suffix(f'.ss{n}').write_bytes(raster.replace_state_chunk(src,bytes(fixed)))
  render(bytes(fixed)).resize((960,640),Image.Resampling.NEAREST).save(DEST/f'ss{n}_after.png');sr.append({'state':n,'vram_tiles':hits})
 gallery(items,DEST/'before_clean_after.png',4)
 m={'parent':{'sha256':sha(parent)},'output':{'path':str(RESULT.relative_to(ROOT)),'size':len(out),'sha256':sha(out)},'targets':reports,'states':sr,'allowed_ranges':allowed,'verification':{'result':'PASS','scope':'static graphics and compression validation','shared_tiles_consistent':True,'compression_roundtrip':True,'native_levelup_gradient_preserved':True,'runtime_emulator':'not performed'}}
 (DEST/'manifest.json').write_text(json.dumps(m,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(sr))
if __name__=='__main__':main()





