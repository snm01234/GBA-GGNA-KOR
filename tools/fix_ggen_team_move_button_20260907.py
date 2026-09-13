"""Correct the audited 移動 button in both states without changing atlas size."""
import json,struct,binascii,sys
from zipfile import ZipFile
from PIL import Image
import build_ggen_advance_team_card_ui_ko_20260903 as t
import render_ggen_ss_tiles_20260905 as render
from ggen_advance_project_paths import ORIGINAL_ROM

OUT=t.ROOT/'outputs/20260907_team_move_button_fix'
def main():
 OUT.mkdir(exist_ok=True)
 parent=t.MAIN_TIP_ROM.read_bytes();jp=ORIGINAL_ROM.read_bytes()
 assert t.sha256(parent)==json.loads(t.MAIN_TIP_MANIFEST.read_text(encoding='utf-8'))['sha256']
 original,_=t.decode_atlas(jp)
 off=t.u32(parent,t.ATLAS_POINTER)-t.ROM_BASE;size=t.u32(parent,off)&65535
 atlas=t.scan.lzss_decompress(parent[off+4:off+4+size]);assert len(atlas)==386*32
 patched=bytearray(atlas);ids=set();previews=[]
 with ZipFile(t.FONT_ZIP) as z:font=t.fontpair.load_bdf(z,'Galmuri11.bdf')
 normal=t.canvas(original,t.LABELS['storage_normal']['ids'])
 for name in ('storage_normal','storage_focus'):
  row=t.LABELS[name];source=t.canvas(original,row['ids']);before=t.canvas(atlas,row['ids'])
  after,_=t.draw_label(source,'이동',row['kind'],font)
  expected_old,_=t.draw_label(source,'격납',row['kind'],font)
  if name.endswith('focus'):
   for y in range(24):
    for x in (27,28):after[y][x]=normal[y][x];expected_old[y][x]=normal[y][x]
  assert before==expected_old,'current button differs from audited raster'
  t.write_canvas(patched,row['ids'],after);ids.update(row['ids']);previews.append((before,after))
  assert t.canvas(patched,row['ids'])==after
 assert all(a==b or n//32 in ids for n,(a,b) in enumerate(zip(atlas,patched)))
 for name,row in t.LABELS.items():
  if not name.startswith('storage_'):assert t.canvas(atlas,row['ids'])==t.canvas(patched,row['ids'])
 blob=t.action.literal_only_lzss_body(bytes(patched));assert len(blob)==size
 assert t.scan.lzss_decompress(blob)==patched
 candidate=bytearray(parent);candidate[off+4:off+4+size]=blob
 assert candidate[:off+4]==parent[:off+4] and candidate[off+4+size:]==parent[off+4+size:]
 state,_=t.statefmt.parse_png_state(t.STATE);fixed=bytearray(state);live=[]
 for src in sorted(ids):
  p=0x1000+(src+1)*32
  if state[p:p+32]==atlas[src*32:(src+1)*32]:fixed[p:p+32]=patched[src*32:(src+1)*32];live.append(src)
 assert set(t.LABELS['storage_normal']['ids'])<=set(live)
 struct.pack_into('<I',fixed,8,binascii.crc32(candidate)&0xffffffff)
 (OUT/'preview.ss1').write_bytes(t.state_writer.replace_state_chunk(t.STATE,bytes(fixed)))
 render.OUT=OUT;render.render(bytes(fixed)).resize((720,480),Image.Resampling.NEAREST).save(OUT/'ss1_after.png')
 colors=[t.bgutil.rgb555(int.from_bytes(state[0x800+11*32+i*2:0x800+11*32+i*2+2],'little')) for i in range(16)]
 im=Image.new('RGB',(64,48))
 for row,pair in enumerate(previews):
  for col,c in enumerate(pair):
   for y,line in enumerate(c):
    for x,v in enumerate(line):im.putpixel((col*32+x,row*24+y),colors[v])
 im.resize((512,384),Image.Resampling.NEAREST).save(OUT/'normal_focus_before_after.png')
 result=OUT/'ggen_team_move_button_fixed_20260907.gba';result.write_bytes(candidate)
 report={'parent':{'sha256':t.sha256(parent)},'output':{'path':t.advance_relative(result),'sha256':t.sha256(candidate),'size':len(candidate)},'correction':{'japanese':'移動','before':'격납','after':'이동','variants':['normal','focus'],'source_tiles':sorted(ids)},'verification':{'result':'PASS','previous_raster_matches_audit':True,'atlas_size_preserved':len(atlas),'other_labels_pixel_exact':True,'only_selected_atlas_tiles_changed':True,'compression_roundtrip':True,'ss1_visible_source_tiles_matched':True,'runtime':'static ROM verification and derived SS1 render; emulator re-entry not run'}}
 (OUT/'manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':sys.stdout.reconfigure(encoding='utf-8');main()
