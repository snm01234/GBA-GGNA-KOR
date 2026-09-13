"""Resolve previously withheld E0518 resource 26 as 回避 from fresh ss1."""
from ggen_ss_tiles_common_20260905 import *
import build_ggen_advance_ss4_stat_badges_ko_20260905 as b
import build_ggen_advance_status_ui_tile_overlay_poc as status
import analyze_ggen_advance_intermission_cycle_states_20260830 as bg
import render_ggen_ss_tiles_20260905 as renderer
from ggen_advance_project_paths import MAIN_TIP_ROM,MAIN_TIP_MANIFEST,FONT_ZIP,ORIGINAL_ROM
from zipfile import ZipFile
import hashlib,json
DEST=ROOT/'outputs/20260907_ggen_evade_up_fix'
MAP=0x1FD4000
def sha(x):return hashlib.sha256(x).hexdigest()
def main():
 parent=MAIN_TIP_ROM.read_bytes();jp=ORIGINAL_ROM.read_bytes()
 assert sha(parent)==json.loads(MAIN_TIP_MANIFEST.read_text(encoding='utf8'))['sha256']
 statepath=ROOT/'SD Gundam GGeneration Advance (Korean).ss1';st,_=statefmt.parse_png_state(statepath)
 off=u32(parent,b.TABLE)-0x8000000;size=u32(parent,off)&65535
 atlas=status.lzss_decompress(parent[off+4:off+4+size])
 assert status.literal_only_compress(atlas)==parent[off:off+4+size]
 jo=u32(jp,b.TABLE)-0x8000000;ja=status.lzss_decompress(jp[jo+4:jo+4+(u32(jp,jo)&65535)])
 m=b.parse_map(parent,26);before=b.stitch(atlas,m)
 clean,info=b.build_common_background(b.stitch(ja,b.parse_map(jp,24)))
 after=[row[:] for row in clean]
 with ZipFile(FONT_ZIP) as z:font=b.fontpair.load_bdf(z,'Galmuri11.bdf')
 painting=b.paint(after,'회피',font,(1,2))
 # Same approved template and painting must reproduce the adjacent 명중 badge.
 hit=[row[:] for row in clean];b.paint(hit,'명중',font,(1,2))
 assert hit==b.stitch(atlas,b.parse_map(parent,24))
 first=len(atlas)//32;newatlas=bytearray(atlas);newcells=[]
 for n,cell in enumerate(m['cells']):
  tile=[row[n%4*8:n%4*8+8] for row in after[n//4*8:n//4*8+8]]
  newatlas.extend(raster.encode_tile(tile));newcells.append((cell&0xf000)|(first+n))
 assert newatlas[:len(atlas)]==atlas and first+8<=1024
 blob=status.literal_only_compress(newatlas);end=off+len(blob)
 assert not any(parent[off+4+size:end])
 newmap=bytearray(parent[m['offset']:m['offset']+20]);struct.pack_into('<8H',newmap,4,*newcells)
 assert not any(parent[MAP:MAP+len(newmap)])
 candidate=bytearray(parent);candidate[off:end]=blob;candidate[MAP:MAP+len(newmap)]=newmap
 struct.pack_into('<I',candidate,b.TABLE+26*4,MAP+0x8000000)
 assert b.stitch(newatlas,b.parse_map(candidate,26))==after
 for idx in range(20,29):
  if idx!=26:assert b.stitch(newatlas,b.parse_map(candidate,idx))==b.stitch(atlas,b.parse_map(parent,idx))
 # Live map 26 occupies x96..127/y104..119, using BG1.
 derived=bytearray(st);bi=bg.bg_info(st,1);v=st[0x1000:0x19000]
 for n,cell in enumerate(m['cells']):
  tx=12+n%4;ty=13+n//4;e=bg.map_entry(v,bi['screen_base'],bi['size'],tx,ty)
  vo=bi['char_base']+(e&1023)*32
  assert v[vo:vo+32]==atlas[(cell&1023)*32:(cell&1023)*32+32]
  assert not e&0xc00
  raw=raster.encode_tile([row[n%4*8:n%4*8+8] for row in after[n//4*8:n//4*8+8]])
  derived[0x1000+vo:0x1000+vo+32]=raw
 cursor=0
 for a,z in sorted([(off,end),(MAP,MAP+20),(b.TABLE+104,b.TABLE+108)]):
  assert candidate[cursor:a]==parent[cursor:a];cursor=z
 assert candidate[cursor:]==parent[cursor:]
 result=DEST/'ggen_evade_up_badge_ko_20260907.gba';result.write_bytes(candidate)
 result.with_suffix('.ss1').write_bytes(raster.replace_state_chunk(statepath,derived))
 renderer.OUT=DEST
 renderer.render(derived).resize((720,480),Image.Resampling.NEAREST).save(DEST/'after.png')
 report={'parent_sha256':sha(parent),'output':{'path':str(result.relative_to(ROOT)),'size':len(candidate),'sha256':sha(candidate)},
 'root_cause':'Resource 26 was explicitly withheld in the previous stat badge builder because its semantics were uncertain and arrow cap tiles were shared with resource 20. Fresh ss1 identifies it as 回避.',
 'translation':{'source':'回避','korean':'회피','resource':26,'painting':painting},
 'resource':{'atlas':hex(off),'private_map':hex(MAP),'new_tiles':list(range(first,first+8))},
 'verification':{'result':'PASS','eight_live_tiles_match':True,'same_background_font_gradient_as_hit':True,'all_old_atlas_tiles_unchanged':True,'shared_arrow_tiles_preserved':True,'all_other_stat_badges_unchanged':True,'only_atlas_extension_private_map_and_pointer_changed':True,'runtime':'ROM and supplied-state rendering verified; live emulator transitions not run'}}
 (DEST/'manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
