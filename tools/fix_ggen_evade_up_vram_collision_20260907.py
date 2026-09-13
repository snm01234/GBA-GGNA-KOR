"""Fix the actual ss1-proven collision with portrait tiles at VRAM 0x208+."""
from ggen_ss_tiles_common_20260905 import *
import build_ggen_advance_ss4_stat_badges_ko_20260905 as b
import build_ggen_advance_status_ui_tile_overlay_poc as status
import render_ggen_ss_tiles_20260905 as renderer
import analyze_ggen_advance_intermission_cycle_states_20260830 as bg
from ggen_advance_project_paths import MAIN_TIP_ROM,MAIN_TIP_MANIFEST,ORIGINAL_ROM
import hashlib,json
DEST=ROOT/'outputs/20260907_ggen_evade_up_runtime_fix'
def sha(x):return hashlib.sha256(x).hexdigest()
def main():
 parent=MAIN_TIP_ROM.read_bytes();jp=ORIGINAL_ROM.read_bytes()
 assert sha(parent)==json.loads(MAIN_TIP_MANIFEST.read_text(encoding='utf8'))['sha256']
 stpath=ROOT/'SD Gundam GGeneration Advance (Korean).ss1';st,_=statefmt.parse_png_state(stpath)
 off=u32(parent,b.TABLE)-0x8000000;length=u32(parent,off)&65535
 atlas=status.lzss_decompress(parent[off+4:off+4+length]);assert len(atlas)==527*32
 current=b.parse_map(parent,26);wanted=b.stitch(atlas,current)
 original=b.parse_map(jp,26);hit=b.parse_map(parent,24)
 oldids=[c&1023 for c in original['cells']];hitids=[c&1023 for c in hit['cells']]
 selected={oldids[i] for i in [0,1,2,4,5,6]}
 for idx in range(1,69):
  m=sem.parse_map(parent,u32(parent,b.TABLE+idx*4))
  if m:assert not selected&{c&1023 for c in m['cells']}
 newatlas=bytearray(atlas[:519*32]);cells=[]
 for n,cell in enumerate(original['cells']):
  tid=hitids[n] if n in [3,7] else oldids[n]
  payload=raster.encode_tile([row[n%4*8:n%4*8+8] for row in wanted[n//4*8:n//4*8+8]])
  if n in [3,7]:assert payload==atlas[tid*32:tid*32+32]
  else:newatlas[tid*32:tid*32+32]=payload
  cells.append((cell&0xf000)|tid)
 assert max(c&1023 for c in cells)+1<0x200
 newmap=bytearray(parent[current['offset']:current['offset']+20]);struct.pack_into('<8H',newmap,4,*cells)
 blob=status.literal_only_compress(newatlas)
 candidate=bytearray(parent);candidate[off:off+4+length]=blob+bytes(4+length-len(blob))
 candidate[current['offset']:current['offset']+20]=newmap
 assert b.stitch(newatlas,b.parse_map(candidate,26))==wanted
 assert all(x==y or i//32 in selected for i,(x,y) in enumerate(zip(atlas[:519*32],newatlas)))
 # Direct evidence: newly added badge tile 0x208 was overwritten with portrait pixels.
 portrait=st[0x1000+0x208*32:0x1000+0x209*32]
 assert portrait==parent[0xA67BC:0xA67DC]
 info=bg.bg_info(st,1);derived=bytearray(st)
 for n,cell in enumerate(cells):
  tid=cell&1023;vo=0x1000+(tid+1)*32
  assert st[vo:vo+32]==atlas[tid*32:tid*32+32]
  derived[vo:vo+32]=newatlas[tid*32:tid*32+32]
  tx,ty=12+n%4,13+n//4
  mo=0x1000+info['screen_base']+ty*64+tx*2
  e=u16(st,mo);assert e&1023==520+n
  struct.pack_into('<H',derived,mo,(e&0xf000)|(tid+1))
 assert derived[0x1000+0x200*32:0x1000+0x220*32]==st[0x1000+0x200*32:0x1000+0x220*32]
 cursor=0
 for a,z in sorted([(off,off+4+length),(current['offset'],current['offset']+20)]):
  assert candidate[cursor:a]==parent[cursor:a];cursor=z
 assert candidate[cursor:]==parent[cursor:]
 result=DEST/'ggen_evade_up_runtime_fix_20260907.gba';result.write_bytes(candidate)
 result.with_suffix('.ss1').write_bytes(raster.replace_state_chunk(stpath,derived))
 renderer.OUT=DEST;renderer.render(derived).resize((720,480),Image.Resampling.NEAREST).save(DEST/'after.png')
 report={'parent_sha256':sha(parent),'state_sha256':sha(stpath.read_bytes()),'output':{'path':str(result.relative_to(ROOT)),'size':len(candidate),'sha256':sha(candidate)},
 'root_cause':'Previous appended glyphs were displayed at VRAM tiles 0x208-0x20F, which the portrait loader overwrites. Tile 0x208 exactly matches portrait ROM bytes at 0xA67BC.',
 'fix':'Restore original 519-tile atlas size; paint the six original private evade body tiles; reuse existing clean hit arrow cap tiles. No appended VRAM allocations.',
 'map_ids':[hex(c&1023) for c in cells],
 'verification':{'result':'PASS','collision_verified_from_fresh_user_state':True,'original_atlas_size_restored':True,'all_target_tiles_below_portrait_region':True,'six_body_slots_unshared':True,'hit_arrow_caps_byte_exact':True,'portrait_region_unchanged':True,'same_approved_badge_pixels':True,'runtime':'Verified against freshly captured collision state and reconstructed graphics; subsequent live re-entry not run'}}
 (DEST/'manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
