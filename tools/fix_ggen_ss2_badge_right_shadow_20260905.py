"""Remove Japanese shadow at x=24..25 from all five ss2 badge maps."""
from ggen_ss_tiles_common_20260905 import *
from build_ggen_ss1_ss4_tiles_ko_20260905 import tile_updates
import build_ggen_advance_status_ui_tile_overlay_poc as status
from ggen_advance_project_paths import MAIN_TIP_MANIFEST
import hashlib,json,binascii,shutil

def main():
 parent=(ROOT/'SD Gundam GGeneration Advance (Korean).gba').read_bytes()
 digest=lambda b:hashlib.sha256(b).hexdigest()
 assert digest(parent)==json.loads(MAIN_TIP_MANIFEST.read_text(encoding='utf-8'))['sha256']
 p=u32(parent,0xd87bc)-0x8000000;size=4+(u32(parent,p)&65535)
 atlas=sem.lzss_decompress(parent[p+4:p+size]);patched=bytearray(atlas);pending={};items=[];rows=[]
 st,_=statefmt.parse_png_state(ROOT/'SD Gundam GGeneration Advance (Korean).ss2')
 colors=raster.palette_rgb(st[0x960:0x980])
 for i,text in [(8,'탑재'),(9,'출격'),(10,'확정'),(11,'퇴각'),(12,'격파')]:
  m=sem.parse_map(parent,u32(parent,0xd87bc+i*4));before=sem.stitch(atlas,m);after=[r[:] for r in before];changed=[]
  for y in range(2,15):
   for x in (24,25):
    if after[y][x] in (4,5):
     after[y][x]=6 if x==24 else (9 if y==14 else 7)
     changed.append([x,y])
  assert all(after[y][x] not in (4,5) for y in range(16) for x in (24,25))
  assert all(before[y][x]==after[y][x] for y in range(16) for x in range(32) if x not in (24,25))
  for tid,new in tile_updates(before,after,m).items():
   if tid in pending:assert pending[tid]==new
   pending[tid]=new
  rows.append({'map':i,'text':text,'erased_shadow_pixels':len(changed),'coordinates':changed})
  items.extend([(f'{i} before',raster.render_canvas(before,colors)),(f'{i} after',raster.render_canvas(after,colors))])
 replacements={}
 for tid,new in pending.items():
  old=atlas[tid*32:(tid+1)*32]
  patched[tid*32:(tid+1)*32]=new
  if old!=new:
   assert old not in replacements or replacements[old]==new
   replacements[old]=new
 blob=status.literal_only_compress(bytes(patched));assert len(blob)==size and sem.lzss_decompress(blob[4:])==patched
 candidate=bytearray(parent);candidate[p:p+size]=blob
 assert candidate[:p]==parent[:p] and candidate[p+size:]==parent[p+size:]
 dest=ROOT/'outputs/20260905_ggen_ss2_badge_right_cleanup';dest.mkdir(exist_ok=True)
 rom=dest/'ggen_ss2_badge_right_cleanup_20260905.gba';rom.write_bytes(candidate)
 state_rows=[]
 for n in range(1,5):
  src=OUT/f'ggen_ss1_ss4_tiles_ko_20260905.ss{n}';st,_=statefmt.parse_png_state(src);new=bytearray(st);hits=0
  for off in range(0x1000,0x19000,32):
   old=st[off:off+32]
   if old in replacements:new[off:off+32]=replacements[old];hits+=1
  assert n==2 or hits==0
  struct.pack_into('<I',new,8,binascii.crc32(candidate)&0xffffffff)
  rom.with_suffix(f'.ss{n}').write_bytes(raster.replace_state_chunk(src,bytes(new)))
  if n==2:
   from render_ggen_ss_tiles_20260905 import render
   render(bytes(new)).resize((960,640),Image.Resampling.NEAREST).save(dest/'ss2_after.png')
  state_rows.append({'state':n,'changed_vram_tiles':hits})
 shutil.copy2(ROOT/'SD Gundam GGeneration Advance (Korean).sav',rom.with_suffix('.sav'))
 gallery(items,dest/'badge_edges_before_after.png',6)
 manifest={'parent':{'sha256':digest(parent)},'output':{'path':str(rom.relative_to(ROOT)),'sha256':digest(candidate),'size':len(candidate)},'targets':rows,'states':state_rows,'verification':{'result':'PASS','background_only_columns':[24,25],'no_shadow_indices_4_5_in_right_edge':True,'shared_tiles_consistent':True,'compression_roundtrip':True,'other_rom_resources_byte_identical':True,'runtime':'user verified previous patch; this followup checked by graphics-memory reconstruction'},'atlas_file_offset':hex(p)}
 (dest/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'rows':rows,'states':state_rows},ensure_ascii=False))
if __name__=='__main__':main()
