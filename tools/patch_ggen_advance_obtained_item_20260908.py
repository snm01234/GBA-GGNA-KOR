"""Translate the two obtained-item settlement overlays, preserving other cells."""
from ggen_ss_tiles_common_20260905 import *
import analyze_ggen_advance_intermission_cycle_states_20260830 as bg
import analyze_ggen_advance_remaining_ui_draw_calls_20260902 as draw
import build_ggen_advance_status_ui_tile_overlay_poc as status
import test_ggen_advance_font_pair as fontpair
from build_ggen_ss8_ss9_tiles_ko_20260905 import spaced_ink
from ggen_advance_project_paths import MAIN_TIP_ROM, MAIN_TIP_MANIFEST, FONT_ZIP
from zipfile import ZipFile
from collections import Counter
import json, hashlib

DEST=ROOT/'outputs/20260908_ggen_advance_obtained_item'
def sha(b):return hashlib.sha256(b).hexdigest()

def main():
 parent=MAIN_TIP_ROM.read_bytes();assert sha(parent)==json.loads(MAIN_TIP_MANIFEST.read_text(encoding='utf8'))['sha256']
 st,_=statefmt.parse_png_state(ROOT/'SD Gundam GGeneration Advance (Korean).ss1')
 info=bg.bg_info(st,1);v=st[0x1000:0x19000]
 off=u32(parent,0xe8020)-0x8000000;size=u32(parent,off)&65535
 atlas=sem.lzss_decompress(parent[off+4:off+4+size]);assert v[32:32+len(atlas)]==atlas
 assert status.literal_only_compress(atlas)==parent[off:off+4+size]
 maps=[sem.parse_map(parent,p+0x8000000) for p in (0xe7894,0xe7d48,0xe7eb4)]
 for y in (1,2):
  for x in range(4,14):
   assert (bg.map_entry(v,info['screen_base'],info['size'],x,y+13)&1023)==(maps[1]['cells'][y*30+x]&1023)+1
 screen,_=draw.layer_pixels(st,1)
 before=[[r[32:144] for r in screen[y:y+16]] for y in (16,40,64,88)]
 fills=[10,11,10,9,6,6,6,6,6,6,6,6,9,10,11,10];template=[]
 for y in range(16):
  line=[]
  for x in range(112):
   vals=[c[y][x] for c in before if c[y][x] not in (12,15)]
   line.append(Counter(vals).most_common(1)[0][0] if vals else fills[y])
  if y in (6,7,8,9):line[:6]=[11,10,9,8,7,6]
  template.append(line)
 with ZipFile(FONT_ZIP) as z:font=fontpair.load_bdf(z,'Galmuri11.bdf')
 ink,w,h=spaced_ink(font,'입수아이템',0);assert w<=74
 points={(x+3,y+2) for x,y in ink}
 desired={};previews=[]
 for mi in (1,2):
  m=maps[mi];canvas=sem.stitch(atlas,m);old=[row[32:112] for row in canvas[8:24]];new=[r[:] for r in old]
  for y in range(16):
   for x in range(80):
    if new[y][x] in (12,15):new[y][x]=template[y][x+14 if x>=64 else x]
  assert not any(v in (12,15) for row in new for v in row)
  for x,y in raster.dilate(points,80,16):new[y][x]=12
  for x,y in points:new[y][x]=15
  previews.append((old,new))
  for y in range(2):
   for x in range(10):desired[(mi,(y+1)*30+x+4)]=raster.encode_tile([row[x*8:x*8+8] for row in new[y*8:y*8+8]])
 protected=set();owned=set()
 for mi,m in enumerate(maps):
  for idx,c in enumerate(m['cells']):(owned if (mi,idx) in desired else protected).add(c&1023)
 pool=sorted(owned-protected);lookup={atlas[k*32:(k+1)*32]:k for k in protected}
 candidate=bytearray(parent);newatlas=bytearray(atlas);allowed=[];bindings={}
 for (mi,idx),raw in desired.items():
  if raw not in lookup:
   assert pool,'no private tile slots remaining'
   sid=pool.pop(0);lookup[raw]=sid;newatlas[sid*32:(sid+1)*32]=raw
  sid=lookup[raw];bindings[(mi,idx)]=sid
  p=maps[mi]['offset']+4+idx*2;c=maps[mi]['cells'][idx];assert not c&0xc00
  struct.pack_into('<H',candidate,p,(c&0xfc00)|sid);allowed.append((p,p+2))
 blob=status.literal_only_compress(newatlas);assert len(blob)==size+4
 assert sem.lzss_decompress(blob[4:])==newatlas
 candidate[off:off+len(blob)]=blob;allowed.append((off,off+len(blob)))
 for mi,m in enumerate(maps):
  nm=sem.parse_map(candidate,m['offset']+0x8000000)
  for idx,c in enumerate(m['cells']):
   nc=nm['cells'][idx]
   if (mi,idx) in desired:assert newatlas[(nc&1023)*32:((nc&1023)+1)*32]==desired[(mi,idx)]
   else:assert c==nc and atlas[(c&1023)*32:((c&1023)+1)*32]==newatlas[(nc&1023)*32:((nc&1023)+1)*32]
 mask=bytearray(len(parent))
 for a,b in allowed:mask[a:b]=b'\1'*(b-a)
 assert all(mask[i] for i,(a,b) in enumerate(zip(parent,candidate)) if a!=b)
 result=DEST/'ggen_advance_obtained_item_candidate_20260908.gba';result.write_bytes(candidate)
 fixed=bytearray(st);fixed[0x1020:0x1020+len(newatlas)]=newatlas
 for (mi,idx),sid in bindings.items():
  if mi!=1:continue
  y,x=divmod(idx,30);p=0x1000+info['screen_base']+((y+13)*32+x)*2
  struct.pack_into('<H',fixed,p,(u16(st,p)&0xfc00)|(sid+1))
 # Static reconstruction only: do not modify the user's save state.
 import render_ggen_ss_tiles_20260905 as render
 render.OUT=DEST
 render.render(bytes(fixed)).resize((960,640),Image.Resampling.NEAREST).save(DEST/'ss1_after_static.png')
 colors=raster.palette_rgb(st[0x9e0:0xa00])
 gallery([(f'{i} {label}',raster.render_canvas(c,colors)) for i,pair in enumerate(previews) for label,c in zip(('before','after'),pair)],DEST/'before_after.png',4)
 report={'parent':{'sha256':sha(parent)},'output':{'path':str(result.relative_to(ROOT)),'sha256':sha(candidate),'size':len(candidate)},'state_sha256':sha((ROOT/'SD Gundam GGeneration Advance (Korean).ss1').read_bytes()),'translation':'入手アイテム → 입수아이템','cause':'Obtained-item overlay maps E7D48 and E7EB4 still used native tiles; earlier translation updated only base map E7894.','atlas':hex(off),'maps':[hex(m['offset']) for m in maps[1:]],'verification':{'result':'PASS','updated_state_atlas_byte_exact':True,'active_overlay_tilemap_matched':True,'all_other_map_cells_and_tile_pixels_preserved':True,'compression_roundtrip':True,'atlas_size_unchanged':True,'runtime_emulator':'not run; static reconstruction from updated SS1 and patched ROM'}}
 (DEST/'manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8');print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
