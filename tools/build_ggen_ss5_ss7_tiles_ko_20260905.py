"""Korean leadership/range and all nine ID-command ribbon graphics."""
from ggen_ss_tiles_common_20260905 import *
from build_ggen_ss1_ss4_tiles_ko_20260905 import paint,tile_updates,row_restore
import build_ggen_advance_status_ui_tile_overlay_poc as status
import analyze_ggen_advance_remaining_ui_draw_calls_20260902 as draw
from ggen_advance_project_paths import FONT_ZIP,MAIN_TIP_MANIFEST
from zipfile import ZipFile
import test_ggen_advance_font_pair as fontpair
import hashlib,json,binascii,shutil

DEST=ROOT/'outputs/20260905_ggen_ss5_ss7_tiles'
RESULT=DEST/'ggen_ss5_ss7_tiles_ko_20260905.gba'
ID_LABELS=[('捕獲','포획'),('移動力','이동력'),('preemptive attack (user-identified)','선제공격'),('威力','위력'),('命中','명중'),('装甲','장갑'),('回避','회피'),('反応','반응'),('ID消去','ID삭제')]
def sha(b):return hashlib.sha256(b).hexdigest()
def main():
 parent=(ROOT/'SD Gundam GGeneration Advance (Korean).gba').read_bytes()
 assert sha(parent)==json.loads(MAIN_TIP_MANIFEST.read_text(encoding='utf-8'))['sha256']
 out=bytearray(parent);DEST.mkdir(exist_ok=True);replacements={};allowed=[];report=[];items=[]
 with ZipFile(FONT_ZIP) as z:
  font11=fontpair.load_bdf(z,'Galmuri11.bdf');font9=fontpair.load_bdf(z,'Galmuri9.bdf')
  condensed=fontpair.load_bdf(z,'Galmuri11-Condensed.bdf')
 def replace(old,new):
  if old==new:return
  assert old not in replacements or replacements[old]==new
  replacements[old]=new
 def write(off,new):out[off:off+len(new)]=new;allowed.append((off,off+len(new)))
 st5,_=statefmt.parse_png_state(ROOT/'SD Gundam GGeneration Advance (Korean).ss5')
 st7,_=statefmt.parse_png_state(ROOT/'SD Gundam GGeneration Advance (Korean).ss7')
 screen,_=draw.layer_pixels(st5,1);colors=raster.palette_rgb(st5[0x960:0x980])
 off=u32(parent,0xe0518)-0x8000000;size=4+(u32(parent,off)&65535)
 oldatlas=sem.lzss_decompress(parent[off+4:off+size]);atlas=bytearray(oldatlas);pending={}
 for jp,ko,x,ids in [('指揮','지휘',8,[246,247,248,249,254,255,256,257]),('範囲','범위',56,[250,251,252,253,258,259,260,261])]:
  m={'width':4,'height':2,'cells':ids};before=sem.stitch(oldatlas,m)
  assert before==[row[x:x+32] for row in screen[128:144]],'ss5 source ownership mismatch'
  after=[r[:] for r in before];background=[screen[y][44] for y in range(128,144)]
  row_restore(after,(0,0,32,16),background);clean=[r[:] for r in after]
  info=paint(after,ko,5,2,font11,10,5)
  for tid,new in tile_updates(before,after,m).items():
   assert tid not in pending or pending[tid]==new
   pending[tid]=new
  report.append({'source':jp,'translation':ko,'atlas':hex(off),'source_tiles':ids,'background_rows':background,**info})
  for name,c in [('before',before),('clean',clean),('after',after)]:items.append((f'ss5 {jp} {name}',raster.render_canvas(c,colors)))
 for tid,new in pending.items():
  old=oldatlas[tid*32:(tid+1)*32];atlas[tid*32:(tid+1)*32]=new;replace(old,new)
 blob=status.literal_only_compress(bytes(atlas));assert len(blob)==size and sem.lzss_decompress(blob[4:])==atlas;write(off,blob)
 signature=parent[0xc36910:0xc36924]
 owners=[p for p in range(0xc30000,0xc50000,4) if parent[p:p+20]==signature]
 assert owners==[0xc341f8+i*0x684 for i in range(9)]
 for base,(jp,ko) in zip(owners,ID_LABELS):
  g=parent[base+0x384:base+0x664];colors=raster.palette_rgb(parent[base+0x664:base+0x684])
  m={'width':4,'height':2,'cells':list(range(15,23))};before=sem.stitch(g,m)
  # Tiles 10/11 are the native unlettered top/bottom band; no inferred fill.
  clean=sem.stitch(g,{'width':4,'height':2,'cells':[10]*4+[11]*4});after=[r[:] for r in clean]
  font=condensed if ko=='선제공격' else font9
  ink,w,h=raster.native_ink(font,ko)
  assert h in (9,11) and w<=28,(ko,w,h)
  y0=13-h
  info=paint(after,ko,(32-w)//2,y0,font,1,15,5)
  assert after[0]==before[0]==[0]*32 and after[15]==before[15]==[0]*32
  contour=raster.dilate({(a+(32-w)//2,b+y0) for a,b in ink},32,16)
  assert all(after[y][x]==clean[y][x] for y in range(16) for x in range(32) if (x,y) not in contour and (x-1,y-1) not in contour)
  for tid,new in tile_updates(before,after,m).items():
   old=g[tid*32:(tid+1)*32]
   if old!=new:write(base+0x384+tid*32,new);replace(old,new)
  if jp=='回避':
   assert st7[0x11000+324*32:0x11000+332*32]==g[15*32:23*32]
   assert colors==raster.palette_rgb(st7[0xac0:0xae0])
  report.append({'source':jp,'translation':ko,'resource':hex(base),'source_tiles':list(range(15,23)),'clean_background_source_tiles':[10,11],'font':'Galmuri11-Condensed' if ko=='선제공격' else 'Galmuri9','glyph_width':w,'glyph_height':h,**info})
  if ko=='선제공격':
   raster.render_canvas(after,colors).resize((512,256),Image.Resampling.NEAREST).save(DEST/'preemptive_attack_condensed.png')
  for name,c in [('before',before),('clean',clean),('after',after)]:items.append((f'ID {jp} {name}',raster.render_canvas(c,colors)))
 # Check every ROM byte outside the declared atlas/word tiles.
 mask=bytearray(len(parent))
 for a,b in allowed:mask[a:b]=b'\1'*(b-a)
 assert all(mask[i] for i,(a,b) in enumerate(zip(parent,out)) if a!=b)
 RESULT.write_bytes(out);shutil.copy2(ROOT/'SD Gundam GGeneration Advance (Korean).sav',RESULT.with_suffix('.sav'))
 state_reports=[]
 from render_ggen_ss_tiles_20260905 import render
 for n,st in [(5,st5),(7,st7)]:
  fixed=bytearray(st);hits=0;cache=[]
  for p in range(0x1000,0x19000,32):
   old=st[p:p+32]
   if old in replacements:fixed[p:p+32]=replacements[old];hits+=1
  for p in range(0x19000,len(st)-31,4):
   old=st[p:p+32]
   if old in replacements:fixed[p:p+32]=replacements[old];cache.append(hex(p))
  assert hits>0
  struct.pack_into('<I',fixed,8,binascii.crc32(out)&0xffffffff)
  src=ROOT/f'SD Gundam GGeneration Advance (Korean).ss{n}'
  RESULT.with_suffix(f'.ss{n}').write_bytes(raster.replace_state_chunk(src,bytes(fixed)))
  a=render(st);b=render(bytes(fixed));b.resize((960,640),Image.Resampling.NEAREST).save(DEST/f'ss{n}_after.png')
  pair=Image.new('RGB',(480,160));pair.paste(a,(0,0));pair.paste(b,(240,0));pair.resize((1440,480),Image.Resampling.NEAREST).save(DEST/f'ss{n}_before_after.png')
  state_reports.append({'state':n,'changed_vram_tiles':hits,'changed_workram_cache':cache})
 gallery(items,DEST/'before_clean_after.png',5)
 manifest={'kind':'ggen_ss5_ss7_tiles_ko_20260905','parent':{'sha256':sha(parent)},'output':{'path':str(RESULT.relative_to(ROOT)),'size':len(out),'sha256':sha(out)},'targets':report,'states':state_reports,'allowed_ranges':allowed,'verification':{'result':'PASS','scope':'ROM compression roundtrip, saved VRAM ownership/reconstruction, visual inspection','ss5_live_owner_exact':True,'ss7_live_owner_exact':True,'native_id_ribbon_background_tiles_preserved':True,'id_headers_caps_and_palettes_unchanged':True,'outside_declared_graphics_byte_identical':True,'runtime_emulator':'not performed'}}
 (DEST/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'targets':len(report),'states':state_reports,'sha256':sha(out)},ensure_ascii=False))
if __name__=='__main__':main()
