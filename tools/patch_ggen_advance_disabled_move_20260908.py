"""Translate action resource 42 using the approved 이동 mask and disabled colors."""
from ggen_ss_tiles_common_20260905 import *
import build_ggen_advance_action_menu_ko_poc as action
import analyze_ggen_advance_intermission_cycle_states_20260830 as bg
import render_ggen_ss_tiles_20260905 as renderer
from ggen_advance_project_paths import MAIN_TIP_ROM, MAIN_TIP_MANIFEST
import hashlib,json

DEST=ROOT/'outputs/20260908_ggen_advance_disabled_move'
def sha(b):return hashlib.sha256(b).hexdigest()

def main():
 parent=MAIN_TIP_ROM.read_bytes();assert sha(parent)==json.loads(MAIN_TIP_MANIFEST.read_text(encoding='utf8'))['sha256']
 statepath=ROOT/'SD Gundam GGeneration Advance (Korean).ss2'
 st,_=statefmt.parse_png_state(statepath)
 table=u32(parent,action.TABLE_CONSUMER_LITERALS[0])-0x8000000
 assert all(u32(parent,p)==table+0x8000000 for p in action.TABLE_CONSUMER_LITERALS)
 off=u32(parent,table)-0x8000000;size=u32(parent,off)&65535
 atlas=sem.lzss_decompress(parent[off+4:off+4+size]);assert len(atlas)==239*32
 assert action.literal_only_lzss_body(atlas)==parent[off+4:off+4+size]
 maps={i:action.parse_map(parent,u32(parent,table+i*4)) for i in range(1,44) if u32(parent,table+i*4)}
 target=maps[42];normal=action.stitch_map(atlas,maps[18]);before=action.stitch_map(atlas,target)
 assert (target['width'],target['height'])==(4,2)
 ids={c&1023 for c in target['cells']};assert len(ids)==8
 for i,m in maps.items():
  if i!=42:assert not ids&{c&1023 for c in m['cells']},f'shared target tile in resource {i}'
 info=bg.bg_info(st,0);v=st[0x1000:0x19000];live=[]
 for n,c in enumerate(target['cells']):
  x=4+n%4;y=7+n//4;cell=bg.map_entry(v,info['screen_base'],info['size'],x,y)
  tid=cell&1023;assert not cell&0xc00
  assert v[tid*32:(tid+1)*32]==atlas[(c&1023)*32:((c&1023)+1)*32]
  live.append(tid)
 assert set(v for row in before for v in row)=={2,3,11}
 # Retain the rounded native perimeter. Disabled ID (resource 43) uses
 # fill/face 3, contour 2, outer border 11. Reuse the normal Korean mask.
 after=[[11 if p==11 else 3 for p in row] for row in before]
 for y in range(1,15):
  for x in range(1,31):
   if normal[y][x]==5:after[y][x]=2
 assert {(x,y) for y in range(1,15) for x in range(1,31) if after[y][x]==2}=={(x,y) for y in range(1,15) for x in range(1,31) if normal[y][x]==5}
 assert all(after[y][x]==before[y][x] for y in range(16) for x in range(32) if before[y][x]==11)
 newatlas=bytearray(atlas)
 for n,c in enumerate(target['cells']):
  assert not c&0xc00;x=n%4*8;y=n//4*8
  raw=action.encode_tile([row[x:x+8] for row in after[y:y+8]])
  p=(c&1023)*32;newatlas[p:p+32]=raw
 assert action.stitch_map(newatlas,target)==after
 assert all(a==b or i//32 in ids for i,(a,b) in enumerate(zip(atlas,newatlas)))
 for i,m in maps.items():
  if i!=42:assert action.stitch_map(atlas,m)==action.stitch_map(newatlas,m)
 blob=action.literal_only_lzss_body(newatlas);assert len(blob)==size and sem.lzss_decompress(blob)==newatlas
 candidate=bytearray(parent);candidate[off+4:off+4+size]=blob
 assert candidate[:off+4]==parent[:off+4] and candidate[off+4+size:]==parent[off+4+size:]
 DEST.mkdir(exist_ok=True);result=DEST/'ggen_advance_disabled_move_candidate_20260908.gba';result.write_bytes(candidate)
 fixed=bytearray(st)
 for n,c in enumerate(target['cells']):
  p=0x1000+live[n]*32;sid=c&1023;fixed[p:p+32]=newatlas[sid*32:(sid+1)*32]
 renderer.OUT=DEST
 renderer.render(bytes(fixed)).resize((960,640),Image.Resampling.NEAREST).save(DEST/'ss2_after_static.png')
 colors=raster.palette_rgb(st[0x9c0:0x9e0])
 gallery([(name,raster.render_canvas(canvas,colors)) for name,canvas in [('normal reference',normal),('disabled before',before),('disabled after',after),('disabled ID reference',action.stitch_map(atlas,maps[43]))]],DEST/'before_after.png',6)
 report={'parent':{'sha256':sha(parent)},'output':{'path':str(result.relative_to(ROOT)),'sha256':sha(candidate),'size':len(candidate)},'state_sha256':sha(statepath.read_bytes()),'translation':'移動 → 이동','resource':42,'resource_table':hex(table),'atlas':hex(off),'source_tiles':sorted(ids),'live_tiles':live,'style':{'glyph_contour':'same as approved normal 이동','fill_and_face':3,'outline':2,'border':11},'verification':{'result':'PASS','all_eight_live_tiles_match_source':True,'other_resources_pixel_exact':True,'atlas_size_preserved':len(atlas),'compression_roundtrip':True,'native_border_preserved':True,'runtime_emulator':'not run; static SS2 graphics reconstruction'}}
 (DEST/'manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8');print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
