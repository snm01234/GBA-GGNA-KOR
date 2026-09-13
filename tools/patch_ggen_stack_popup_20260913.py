"""Fix warning-only composite tiles without increasing the 386-tile atlas."""
import json,struct
from collections import defaultdict
from pathlib import Path
from PIL import Image
import ggen_ss_tiles_common_20260905 as g
import analyze_ggen_advance_intermission_cycle_states_20260830 as bg
import build_ggen_advance_status_ui_tile_overlay_poc as compression
import render_ggen_ss_tiles_20260905 as renderer
import build_ggen_allclear_profiles_ko_20260912 as assets
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs/20260913_stack_popup'
EXPECTED='4a13e413447cccae2ededd5067423df040092f38ba2028cb091d14027a3b8565'
def main():
 OUT.mkdir(parents=True,exist_ok=True);parent=(ROOT/'SD Gundam GGeneration Advance (Korean).gba').read_bytes();assert assets.sha(parent)==EXPECTED
 ao=g.u32(parent,0xdab70)-0x8000000;old=g.sem.lzss_decompress(parent[ao+4:ao+4+(g.u32(parent,ao)&65535)])
 maps={i:g.sem.parse_map(parent,g.u32(parent,0xdab70+i*4)) for i in range(2,25)}
 originals={i:g.sem.stitch(old,m) for i,m in maps.items()};wanted={i:[r[:] for r in im] for i,im in originals.items()}
 targets=[]
 for idx,donor in [(13,11),(14,12)]:
  y=(maps[idx]['height']-5)*8;dy=(maps[donor]['height']-5)*8
  # Keep the popup's horizontal lower border at row zero. Restore the folder
  # roof/tab below it identically on both cards, including its top two rows.
  for yy in range(1,8):
   wanted[idx][y+yy][8:40]=originals[donor][dy+yy][8:40]
  if idx==13:
   # The first three rows are the warning border/shadow, not label content.
   for yy in range(3,8):wanted[idx][y+yy][48:80]=originals[donor][dy+yy][48:80]
  for tx in range(10):
   ty=y//8
   if any(wanted[idx][y+yy][tx*8:tx*8+8]!=originals[idx][y+yy][tx*8:tx*8+8] for yy in range(8)):targets.append((idx,ty*10+tx))
 # Reclaim one duplicated blank frame tile by pointing its map at an exact
 # existing duplicate. No added VRAM, and no visual change in the flight label.
 cells={i:list(m['cells']) for i,m in maps.items()}
 assert old[323*32:324*32]==old[48*32:49*32]
 uses=defaultdict(list)
 for idx,m in maps.items():
  for n,c in enumerate(m['cells']):uses[c&1023].append((idx,n))
 assert {idx for idx,_ in uses[323]}=={20}
 for idx,n in uses[323]:cells[idx][n]=(cells[idx][n]&0xfc00)|48
 targetset=set(targets)
 retired={maps[i]['cells'][n]&1023 for i,n in targets if all(ref in targetset for ref in uses[maps[i]['cells'][n]&1023])}|{323}
 available=iter(sorted(retired));atlas=bytearray(old);cache={old[i*32:(i+1)*32]:i for i in range(len(old)//32) if i not in retired};alloc=[]
 for idx,n in targets:
  m=maps[idx];tx=n%m['width'];ty=n//m['width'];c=m['cells'][n];assert not c&0xc00
  raw=g.raster.encode_tile([wanted[idx][ty*8+yy][tx*8:tx*8+8] for yy in range(8)])
  if raw in cache:tid=cache[raw]
  else:
   tid=next(available);cache[raw]=tid;atlas[tid*32:(tid+1)*32]=raw;alloc.append(tid)
  cells[idx][n]=(c&0xfc00)|tid
 candidate=bytearray(parent);allowed=set();mapchanges=[]
 for idx,m in maps.items():
  assert g.sem.stitch(atlas,dict(m,cells=cells[idx]))==wanted[idx],('unexpected shared tile change',idx)
  for n,(a,b) in enumerate(zip(m['cells'],cells[idx])):
   if a==b:continue
   off=m['offset']+4+n*2;struct.pack_into('<H',candidate,off,b);allowed.update(range(off,off+2));mapchanges.append((idx,n,a,b))
 blob=compression.literal_only_compress(bytes(atlas));assert len(blob)==4+(g.u32(parent,ao)&65535) and len(atlas)==386*32
 assert g.sem.lzss_decompress(blob[4:])==atlas
 candidate[ao:ao+len(blob)]=blob;allowed.update(range(ao,ao+len(blob)))
 assert all(a==b or i in allowed for i,(a,b) in enumerate(zip(parent,candidate)))
 # Palette selectors of warning composites remain unchanged. Both folder
 # interiors now have identical shapes under the preserved popup lower edge.
 left=wanted[13][-40:];right=wanted[14][-40:]
 assert all(left[y][8:40]==right[y][8:40] for y in range(1,32))
 proofs=[];renderer.OUT=OUT
 for sn in (2,3):
  path=ROOT/f'SD Gundam GGeneration Advance (Korean).ss{sn}';sh=assets.sha(path.read_bytes());st,_=g.statefmt.parse_png_state(path);rt=bytearray(st)
  assert st[0x1020:0x1020+len(old)]==old
  rt[0x1020:0x1020+len(atlas)]=atlas;inf=bg.bg_info(st,1)
  if sn==3:
   for idx,x0,y0 in [(13,10,5),(14,20,6)]:
    m=maps[idx]
    for yy in range(m['height']):
     for xx in range(m['width']):
      n=yy*m['width']+xx;o=0x1000+inf['screen_base']+((y0+yy)*32+x0+xx)*2;e=g.u16(st,o)
      assert (e&0xfff)==((m['cells'][n]&0xfff)+1),(idx,xx,yy,hex(e),hex(m['cells'][n]))
      struct.pack_into('<H',rt,o,(e&0xf000)|((cells[idx][n]&0xfff)+1))
  before=renderer.render(st);after=renderer.render(rt)
  if sn==2:assert before.tobytes()==after.tobytes()
  after.resize((960,640),Image.Resampling.NEAREST).save(OUT/f'ss{sn}_after_reconstructed.png')
  assert assets.sha(path.read_bytes())==sh;proofs.append(dict(state=sn,sha256=sh,atlas_exact=True))
 out=OUT/'ggen_stack_popup_20260913.gba';out.write_bytes(candidate)
 report=dict(parent_sha256=EXPECTED,output=dict(path=out.relative_to(ROOT).as_posix(),size=len(candidate),sha256=assets.sha(candidate)),atlas_offset=hex(ao),modified_map_entries=mapchanges,reused_tiles=alloc,state_proofs=proofs,verification=dict(result='PASS',all_23_maps_roundtrip=True,unchanged_normal_screen=True,left_right_folder_interiors_identical=True,popup_bottom_border_preserved=True,compatibility_uses_korean_donor=True,atlas_tiles=386,savestates_preserved=True,runtime='ROM/VRAM reconstruction; not live emulator playback'))
 (OUT/'manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(report,ensure_ascii=True))
if __name__=='__main__':main()
