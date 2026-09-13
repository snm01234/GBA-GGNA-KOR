"""Clean and translate the C40EDC BG2 movement/assignment badges."""
from ggen_ss_tiles_common_20260905 import *
from ggen_advance_project_paths import MAIN_TIP_ROM, MAIN_TIP_MANIFEST, FONT_ZIP
import build_ggen_advance_remodel_anim3_followup_20260905 as paint
import render_ggen_ss_tiles_20260905 as renderer
import analyze_ggen_advance_intermission_cycle_states_20260830 as bg
from zipfile import ZipFile
import hashlib,json

DEST=ROOT/'outputs/20260907_ggen_ss1_assignment_badges'
SOURCE=0xC40EDC
TARGET=0x1FCA000
OWNERS=[0x68464,0x68658]
def sha(b):return hashlib.sha256(b).hexdigest()

def main():
 DEST.mkdir(exist_ok=True)
 parent=MAIN_TIP_ROM.read_bytes()
 assert sha(parent)==json.loads(MAIN_TIP_MANIFEST.read_text(encoding='utf8'))['sha256']
 statepath=ROOT/'SD Gundam GGeneration Advance (Korean).ss1'
 st,_=statefmt.parse_png_state(statepath)
 assert parent[SOURCE:SOURCE+16].hex()=='1a000e14100030024002de0800000000'
 assert raster.pointer_hits(parent,SOURCE+0x08000000)==OWNERS
 atlas=sem.lzss_decompress(parent[SOURCE+0x240:SOURCE+0x240+2270])
 assert len(atlas)==239*32
 cells=list(struct.unpack_from('<280H',parent,SOURCE+16))
 spec={'width':14,'height':20,'cells':cells}
 before=sem.stitch(atlas,spec);after=[row[:] for row in before]
 clean=[row[:] for row in before]
 reports=[]
 with ZipFile(FONT_ZIP) as z:font=paint.fontpair.load_bdf(z,'Galmuri11.bdf')
 # Reuse the blank nameplate's intact rounded frame and vertical gradient.
 # Its center is shortened, retaining both original end caps.
 for y,jp,ko in [(96,'移動タイプ','이동 타입'),(112,'現在の配属','현재 배속')]:
  for dy in range(16):
   donor=before[80+dy]
   strip=donor[4:11]+[donor[50]]*54+donor[101:108]
   assert len(strip)==68 and not any(v in (4,5) for v in strip)
   after[y+dy][4:72]=strip;clean[y+dy][4:72]=strip
  info=paint.paint_text(after,(10,y,66,y+16),ko,font)
  reports.append({'source':jp,'korean':ko,'paint':info})
 selected={ty*14+tx for ty in range(12,16) for tx in range(9)}
 ids={cells[i]&1023 for i in selected}
 assert not any((c&1023) in ids for i,c in enumerate(cells) if i not in selected)
 newatlas=bytearray(atlas);written={};live=[]
 bi=bg.bg_info(st,2);vram=st[0x1000:0x19000]
 for i in sorted(selected):
  tx,ty=i%14,i//14;c=cells[i];tid=c&1023
  e=bg.map_entry(vram,bi['screen_base'],bi['size'],16+tx,ty)
  assert e&0xfff==c&0xfff
  off=bi['char_base']+(e&1023)*32
  assert vram[off:off+32]==atlas[tid*32:tid*32+32]
  tile=[row[tx*8:tx*8+8] for row in after[ty*8:ty*8+8]]
  if c&0x800:tile=tile[::-1]
  if c&0x400:tile=[row[::-1] for row in tile]
  raw=raster.encode_tile(tile)
  assert tid not in written or written[tid]==raw
  written[tid]=raw;newatlas[tid*32:tid*32+32]=raw
  live.append((off,raw))
 assert sem.stitch(newatlas,spec)==after
 assert all(v==before[y][x] for y,row in enumerate(after) for x,v in enumerate(row) if not(4<=x<72 and 96<=y<128))
 assert all(a==b or i//32 in ids for i,(a,b) in enumerate(zip(atlas,newatlas)))
 blob=bytearray(parent[SOURCE:SOURCE+0x240]);struct.pack_into('<H',blob,0,0xA)
 struct.pack_into('<H',blob,10,len(newatlas));blob.extend(newatlas)
 assert all(v==0 for v in parent[TARGET:TARGET+len(blob)])
 candidate=bytearray(parent);candidate[TARGET:TARGET+len(blob)]=blob
 for owner in OWNERS:struct.pack_into('<I',candidate,owner,TARGET+0x08000000)
 cursor=0
 for start,end in sorted([(p,p+4) for p in OWNERS]+[(TARGET,TARGET+len(blob))]):
  assert candidate[cursor:start]==parent[cursor:start];cursor=end
 assert candidate[cursor:]==parent[cursor:]
 result=DEST/'ggen_ss1_assignment_badges_ko_20260907.gba';result.write_bytes(candidate)
 derived=bytearray(st)
 for off,raw in live:derived[0x1000+off:0x1000+off+32]=raw
 result.with_suffix('.ss1').write_bytes(raster.replace_state_chunk(statepath,derived))
 renderer.OUT=DEST
 renderer.render(st).resize((720,480),Image.Resampling.NEAREST).save(DEST/'before.png')
 renderer.render(derived).resize((720,480),Image.Resampling.NEAREST).save(DEST/'after.png')
 colors=raster.palette_rgb(st[0x960:0x980])
 for name,canvas in [('clean',clean),('korean',after)]:
  im=Image.new('RGB',(72,32));px=im.load()
  for y in range(32):
   for x in range(72):px[x,y]=colors[canvas[96+y][x]]
  im.resize((432,192),Image.Resampling.NEAREST).save(DEST/f'{name}_badges.png')
 manifest={'parent_sha256':sha(parent),'reference_state_sha256':sha(statepath.read_bytes()),
  'output':{'path':str(result.relative_to(ROOT)),'size':len(candidate),'sha256':sha(candidate)},
  'translations':reports,'resource':{'source':hex(SOURCE),'target':hex(TARGET),'owners':[hex(p) for p in OWNERS],'bytes':len(blob),'tiles':len(atlas)//32},
  'verification':{'result':'PASS','all_36_live_cells_match_source':True,'clean_base_has_no_original_ink_or_shadow':True,'native_nameplate_frame_and_gradient_reused':True,'target_tiles_not_shared_outside_badges':True,'tile_count_and_map_unchanged':True,'outside_two_badges_pixel_exact':True,'all_other_rom_bytes_preserved':True,'runtime':'Decoded ROM and supplied-state rendering verified; live emulator transitions not run'}}
 (DEST/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
 print(json.dumps(manifest,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
