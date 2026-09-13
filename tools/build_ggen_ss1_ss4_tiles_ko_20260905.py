"""Patch measured graphics owners; reconstruct row gradients before Hangul ink."""
from ggen_ss_tiles_common_20260905 import *
from zipfile import ZipFile
from collections import defaultdict
import hashlib,json,binascii,shutil
import test_ggen_advance_font_pair as fontpair
import build_ggen_advance_status_ui_tile_overlay_poc as status
import analyze_ggen_advance_remaining_ui_draw_calls_20260902 as draw
from ggen_advance_project_paths import FONT_ZIP,MAIN_TIP_MANIFEST

ROM=ROOT/'SD Gundam GGeneration Advance (Korean).gba'
RESULT=OUT/'ggen_ss1_ss4_tiles_ko_20260905.gba'
def sha(b):return hashlib.sha256(b).hexdigest()
def copy(c):return [r[:] for r in c]
def paint(c,text,x,y,font,face,edge,shadow=None,clip=None):
 ink,_,_=raster.native_ink(font,text)
 ink={(a+x,b+y) for a,b in ink};outline=raster.dilate(ink,len(c[0]),len(c))
 shade={(a+1,b+1) for a,b in outline} if shadow is not None else set()
 def valid(a,b):return 0<=b<len(c) and 0<=a<len(c[0]) and (clip is None or clip[0]<=a<clip[1])
 for pts,color in [(shade,shadow),(outline,edge),(ink,face)]:
  for a,b in pts:
   if valid(a,b):c[b][a]=color
 return {'text':text,'origin':[x,y],'face':face,'outline':edge,'shadow':shadow,'ink_pixels':len(ink)}
def row_restore(c,box,donor):
 x0,y0,x1,y1=box
 for y in range(y0,y1):
  val=donor[y-y0]
  for x in range(x0,x1):c[y][x]=val
def tile_updates(before,after,m):
 updates={}
 for idx,cell in enumerate(m['cells']):
  x=idx%m['width']*8;y=idx//m['width']*8
  old=raster.encode_tile([row[x:x+8] for row in before[y:y+8]])
  tile=[row[x:x+8] for row in after[y:y+8]]
  if cell&0x400:tile=[list(reversed(row)) for row in tile]
  if cell&0x800:tile=list(reversed(tile))
  payload=raster.encode_tile(tile);tid=cell&1023
  if tid in updates:assert updates[tid]==payload,('shared tile conflict',tid)
  updates[tid]=payload
 return updates
def main():
 parent=ROM.read_bytes();out=bytearray(parent);meta=json.loads(MAIN_TIP_MANIFEST.read_text(encoding='utf-8'));assert meta['sha256']==sha(parent)
 with ZipFile(FONT_ZIP) as z:font=fontpair.load_bdf(z,'Galmuri11.bdf')
 states=[statefmt.parse_png_state(ROOT/f'SD Gundam GGeneration Advance (Korean).ss{i}')[0] for i in range(1,5)]
 palette=raster.palette_rgb(states[1][statefmt.STATE_PALETTE+352:statefmt.STATE_PALETTE+384])
 replacements={};report=[];gallery=[];allowed=[]
 def record(old,new):
  if old==new:return
  if old in replacements:assert replacements[old]==new,'ambiguous live replacement'
  replacements[old]=new
 def write(off,old,new):
  assert parent[off:off+len(old)]==old
  out[off:off+len(new)]=new;allowed.append((off,off+len(new)))
 for off,labels in [
  (0xa98480,[('공격력',(0,73,46,87),52,3,74),('대상수',(0,89,46,103),52,3,90)]),
  (0xa9aa0c,[('공격력',(0,73,46,87),52,3,74)]),
  (0xa99cfc,[('명중',(4,17,33,31),36,6,18)]),
  (0xa9be94,[('결정',(40,0,72,16),20,43,2)]),
  (0xa9c06c,[('중지',(32,0,64,16),20,35,2)]),
  (0xa9c634,[('결정',(40,0,72,16),20,43,2)]),
  (0xa9c80c,[('중지',(32,0,64,16),20,35,2)]),
 ]:
  m=direct(parent,off);before=canvas_direct(parent,m);after=copy(before)
  for text,box,donor,x,y in labels:
   row_restore(after,box,[before[yy][donor] for yy in range(box[1],box[3])])
   clean=copy(after)
   focus=off in (0xa9c634,0xa9c80c);hit=off==0xa99cfc
   info=paint(after,text,x,y,font,12 if focus else 10,1 if focus else (2 if hit else 5))
   report.append({'owner':hex(off),'box':box,'background_donor_x':donor,**info})
  for tid,new in tile_updates(before,after,m).items():
   pos=m['graphics_offset']+tid*32;old=parent[pos:pos+32]
   if old!=new:write(pos,old,new);record(old,new)
  colors=raster.palette_rgb(parent[m['palette_offset']:m['palette_offset']+32])
  # Large left panels select their second palette for the lower text rows.
  if off in (0xa98480,0xa9aa0c):colors=palette
  for title,c in [('before',before),('clean',clean),('after',after)]:
   if m['height']>6:c=[row[:80] for row in c[72:104]]
   gallery.append((f'{off:x} {title}',raster.render_canvas(c,colors)))
 # Five sibling list badges, including the three not shown in ss2.
 p=u32(parent,0xd87bc)-0x8000000;oldatlas=sem.lzss_decompress(parent[p+4:p+4+(u32(parent,p)&65535)]);atlas=bytearray(oldatlas);pending={}
 for i,text in [(8,'탑재'),(9,'출격'),(10,'확정'),(11,'퇴각'),(12,'격파')]:
  m=sem.parse_map(parent,u32(parent,0xd87bc+i*4));before=sem.stitch(oldatlas,m);after=copy(before)
  # Orange badge has its own gradient, distinct from the yellow HP field.
  row_restore(after,(0,0,24,16),[6,7]+[8]*12+[7,6]);clean=copy(after)
  info=paint(after,text,0,2,font,10,5,4,clip=(0,24));report.append({'owner':hex(0xd87bc),'map':i,'background_rows':[6,7]+[8]*12+[7,6],**info})
  for tid,new in tile_updates(before,after,m).items():
   if tid in pending:assert pending[tid]==new,('badge shared tile',tid)
   pending[tid]=new
  for title,c in [('before',before),('clean',clean),('after',after)]:gallery.append((f'ss2 {i} {title}',raster.render_canvas(c,palette)))
 for tid,new in pending.items():
  old=oldatlas[tid*32:(tid+1)*32];atlas[tid*32:(tid+1)*32]=new;record(old,new)
 blob=status.literal_only_compress(bytes(atlas));clone=0x1f90000
 assert not any(parent[clone:clone+len(blob)]),'clone allocation occupied'
 write(clone,parent[clone:clone+len(blob)],blob);write(0xd87bc,parent[0xd87bc:0xd87c0],struct.pack('<I',0x8000000+clone))
 assert sem.lzss_decompress(blob[4:])==atlas
 # ss3 BG1: exact source IDs are live IDs minus one, E0518 atlas.
 p=u32(parent,0xe0518)-0x8000000;oldatlas=sem.lzss_decompress(parent[p+4:p+4+(u32(parent,p)&65535)]);atlas=bytearray(oldatlas)
 screen,_=draw.layer_pixels(states[2],1);before=[row[8:48] for row in screen[136:152]];after=copy(before)
 row_restore(after,(0,1,34,15),[screen[56+y][60] for y in range(1,15)]);clean=copy(after)
 info=paint(after,'상성',5,2,font,10,5);report.append({'owner':hex(p),'source_ids':[220,221,222,223,224,231,232,233,234,235],**info})
 m={'width':5,'height':2,'cells':[220,221,222,223,224,231,232,233,234,235]}
 assert sem.stitch(oldatlas,m)==before
 for tid,new in tile_updates(before,after,m).items():
  old=oldatlas[tid*32:(tid+1)*32];atlas[tid*32:(tid+1)*32]=new;record(old,new)
 blob=status.literal_only_compress(bytes(atlas));assert len(blob)==4+(u32(parent,p)&65535)
 write(p,parent[p:p+len(blob)],blob);assert sem.lzss_decompress(blob[4:])==atlas
 for title,c in [('before',before),('clean',clean),('after',after)]:gallery.append((f'ss3 {title}',raster.render_canvas(c,palette)))
 # ss4 C5A5DC native OBJ package; preserve the shared left cap.
 offsets=[0xc5bbf0,0xc5d110,0xc5d130,0xc5d150,0xc5d1d0,0xc5d1f0,0xc5d210,0xc5d230,
          0xc5c4d0,0xc5d170,0xc5d190,0xc5d1b0,0xc5d250,0xc5d270,0xc5d290,0xc5d2b0]
 raw=b''.join(parent[o:o+32] for o in offsets);m={'width':8,'height':2,'cells':list(range(16))};before=sem.stitch(raw,m);after=copy(before)
 # The rightmost blank column supplies the exact top/bottom bevel colors.
 row_restore(after,(8,0,62,16),[row[63] for row in before]);clean=copy(after)
 info=paint(after,'남은횟수',9,2,font,10,5);report.append({'owner':'0x08C5A5DC','offsets':[hex(o) for o in offsets],**info})
 for tid,new in tile_updates(before,after,m).items():
  off=offsets[tid];old=parent[off:off+32]
  if old!=new:write(off,old,new);record(old,new)
 objpal=raster.palette_rgb(states[3][statefmt.STATE_PALETTE+512+160:statefmt.STATE_PALETTE+512+192])
 for title,c in [('before',before),('clean',clean),('after',after)]:gallery.append((f'ss4 {title}',raster.render_canvas(c,objpal)))
 OUT.mkdir(parents=True,exist_ok=True);RESULT.write_bytes(out)
 # Derived copies update saved graphics; original user states stay intact.
 state_reports=[]
 for n,st in enumerate(states,1):
  fixed=bytearray(st);hits=0;cache_hits=[]
  for off in range(statefmt.STATE_VRAM,statefmt.STATE_IWRAM,32):
   raw=st[off:off+32]
   if raw in replacements:fixed[off:off+32]=replacements[raw];hits+=1
  # The saved work RAM can hold decoded graphics queued for a later transfer.
  # Match complete changed 4bpp tiles, at the engine's four-byte alignment.
  for off in range(statefmt.STATE_IWRAM,len(st)-31,4):
   raw=st[off:off+32]
   if raw in replacements:
    fixed[off:off+32]=replacements[raw];cache_hits.append(hex(off))
  struct.pack_into('<I',fixed,8,binascii.crc32(out)&0xffffffff)
  original=ROOT/f'SD Gundam GGeneration Advance (Korean).ss{n}'
  RESULT.with_suffix(f'.ss{n}').write_bytes(raster.replace_state_chunk(original,bytes(fixed)))
  state_reports.append({'state':n,'updated_vram_tiles':hits,'updated_cached_tile_offsets':cache_hits})
  import analyze_ggen_advance_intermission_cycle_states_20260830 as bg
  for l in range(4):bg.render_bg(bytes(fixed),bg.bg_info(bytes(fixed),l),OUT/f'patched_ss{n}_bg{l}.png')
 shutil.copy2(ROM.with_suffix('.sav'),RESULT.with_suffix('.sav'))
 from ggen_ss_tiles_common_20260905 import gallery as save_gallery
 save_gallery(gallery,OUT/'before_clean_after.png',4)
 mask=bytearray(len(parent))
 for a,b in allowed:mask[a:b]=b'\1'*(b-a)
 assert all(mask[i] for i,(a,b) in enumerate(zip(parent,out)) if a!=b)
 manifest={'kind':'ggen_ss1_ss4_tiles_ko_20260905','parent':{'sha256':sha(parent)},'output':{'path':str(RESULT.relative_to(ROOT)),'size':len(out),'sha256':sha(out)},'targets':report,'states':state_reports,'verification':{'result':'PASS','scope':'static ROM roundtrip, saved graphics memory reconstruction and visual review','runtime_emulator':'not verified: headless mGBA GDB connection unavailable','compression_roundtrip':True,'shared_tile_consistency':True,'writes_restricted_to_graphics_and_one_atlas_pointer':True},'allowed_ranges':allowed}
 (OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({'output':str(RESULT),'states':state_reports,'targets':len(report)},ensure_ascii=False))
if __name__=='__main__':main()
