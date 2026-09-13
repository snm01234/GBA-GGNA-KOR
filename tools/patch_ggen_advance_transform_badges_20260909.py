"""Translate the transform-screen movement and all six aptitude badges."""
from ggen_ss_tiles_common_20260905 import *
import build_ggen_ss1_ss4_tiles_ko_20260905 as painter
import build_ggen_advance_status_ui_tile_overlay_poc as compression
import analyze_ggen_advance_intermission_cycle_states_20260830 as bg
import patch_ggen_advance_stack_warning_support_palette_20260909 as render
from ggen_advance_project_paths import MAIN_TIP_ROM, MAIN_TIP_MANIFEST, FONT_ZIP
from zipfile import ZipFile
import hashlib,json,binascii,shutil

DEST=ROOT/'outputs/20260909_transform_badges/v2_clean_background'
TABLE=0xd54e4
CLONE=0x1fd6000
def sha(b):return hashlib.sha256(b).hexdigest()

def main():
 DEST.mkdir(parents=True,exist_ok=True)
 parent=MAIN_TIP_ROM.read_bytes()
 assert sha(parent)==json.loads(MAIN_TIP_MANIFEST.read_text(encoding='utf8'))['sha256']
 source=u32(parent,TABLE)-0x8000000;assert source==0xd45dc
 assert raster.pointer_hits(parent,source+0x8000000)==[TABLE]
 old=sem.lzss_decompress(parent[source+4:source+4+u16(parent,source)])
 assert len(old)==190*32
 maps={i:sem.parse_map(parent,u32(parent,TABLE+i*4)) for i in range(2,17)}
 main_canvas=sem.stitch(old,maps[2])
 # The same screen's empty name field supplies an intact native cap and
 # scanline gradient. Old brown glyph backing must not be used as a donor.
 donor=[row[:40] for row in main_canvas[112:128]]
 assert all(v not in (4,5) for row in donor for v in row)
 blanks=[]
 movement={'width':4,'height':2,'cells':[maps[2]['cells'][y*30+x] for y in (14,15) for x in range(17,21)]}
 assert movement['cells']==[110,111,112,113,118,119,120,121]
 jobs=[('移動','이동',movement,7)]+[(jp,ko,maps[i],4) for i,jp,ko in [(3,'汎用','범용'),(4,'宇宙','우주'),(5,'地上','지상'),(6,'万能','만능'),(7,'水陸','수륙'),(8,'飛行','비행')]]
 with ZipFile(FONT_ZIP) as z:font=painter.fontpair.load_bdf(z,'Galmuri11.bdf')
 atlas=bytearray(old);pending={};reports=[];images=[]
 states={n:statefmt.parse_png_state(ROOT/f'SD Gundam GGeneration Advance (Korean).ss{n}')[0] for n in (1,2)}
 colors=raster.palette_rgb(states[1][0x960:0x980])
 for jp,ko,m,left in jobs:
  before=sem.stitch(old,m);right=32 if ko=='이동' else 28
  if ko=='이동':clean=[row[:32] for row in donor]
  else:
   # Aptitude capsules start two pixels earlier than the name/move field.
   # Mirror the donor cap to form a short, symmetric 32x16 capsule.
   clean=[[donor[y][x+2 if x<16 else 33-x] for x in range(32)] for y in range(16)]
  assert all(v not in (4,5) for row in clean for v in row)
  after=[row[:] for row in clean]
  ink,w,h=raster.native_ink(font,ko)
  assert w<=right-left-2 and h<=12,(ko,w,h)
  x=left+(right-left-w)//2;y=(16-h)//2
  painter.paint(after,ko,x,y,font,10,5,clip=(left,right))
  guard=6 if ko=='이동' else 3
  assert all(clean[y][x]==before[y][x] for y in range(16) for x in range(32) if y in (0,15) or x<guard or (ko!='이동' and x>=32-guard))
  # Every change from the clean plate belongs to the Korean glyph or its
  # one-pixel outline; no old Japanese backing can survive elsewhere.
  placed={(a+x,b+y) for a,b in ink};outline=raster.dilate(placed,32,16)
  assert all(after[yy][xx]==clean[yy][xx] or (xx,yy) in outline for yy in range(16) for xx in range(32))
  assert all(after[yy][xx]!=5 or (xx,yy) in outline for yy in range(16) for xx in range(32))
  updates=painter.tile_updates(before,after,m)
  for tid,raw in updates.items():
   assert tid not in pending or pending[tid]==raw
   pending[tid]=raw
  reports.append({'jp':jp,'ko':ko,'source_tiles':m['cells'],'glyph_origin':[x,y],'glyph_size':[w,h]})
  index=len(reports)
  images.extend([(f'{index} before',raster.render_canvas(before,colors)),(f'{index} clean background',raster.render_canvas(clean,colors)),(f'{index} Korean',raster.render_canvas(after,colors))])
  blanks.append((f'{index} clean',raster.render_canvas(clean,colors)))
 for tid,raw in pending.items():atlas[tid*32:(tid+1)*32]=raw
 assert all(old[i]==atlas[i] or i//32 in pending for i in range(len(old)))
 for i in range(9,17):assert sem.stitch(old,maps[i])==sem.stitch(atlas,maps[i])
 # Check main canvas outside movement and the default general-type badge.
 main_before=sem.stitch(old,maps[2]);main_after=sem.stitch(atlas,maps[2])
 for y in range(160):
  for x in range(240):
   assert main_before[y][x]==main_after[y][x] or (112<=y<128 and (136<=x<168 or 192<=x<224))
 live_reports={}
 for n,st in states.items():
  assert u32(st,8)==binascii.crc32(parent)&0xffffffff
  fixed=bytearray(st);v=st[0x1000:0x19000];info=bg.bg_info(st,1)
  assert info['char_base']==info['scroll_x']==info['scroll_y']==0
  bindings=[]
  for sx,m in [(17,movement),(24,maps[3 if n==1 else 6])]:
   for k,sid in enumerate(m['cells']):
    x=sx+k%4;y=14+k//4;c=bg.map_entry(v,info['screen_base'],info['size'],x,y);tid=c&1023
    assert c>>12==11 and not c&0xc00
    assert v[tid*32:(tid+1)*32]==old[sid*32:(sid+1)*32]
    fixed[0x1000+tid*32:0x1000+(tid+1)*32]=atlas[sid*32:(sid+1)*32]
    bindings.append({'live':tid,'source':sid})
  render.renderer.OUT=DEST
  render.render_affine_banner(bytes(fixed)).resize((960,640),Image.Resampling.NEAREST).save(DEST/f'ss{n}_after_static.png')
  live_reports[n]={'state_sha256':sha((ROOT/f'SD Gundam GGeneration Advance (Korean).ss{n}').read_bytes()),'bindings':bindings}
 blob=compression.literal_only_compress(bytes(atlas));assert len(blob)<=0x2000
 assert sem.lzss_decompress(blob[4:])==atlas
 assert not any(parent[CLONE:CLONE+0x2000])
 assert not any(CLONE+0x8000000<=word[0]<CLONE+0x8002000 for word in struct.iter_unpack('<I',parent))
 candidate=bytearray(parent);candidate[CLONE:CLONE+len(blob)]=blob
 struct.pack_into('<I',candidate,TABLE,CLONE+0x8000000)
 assert all(a==b or TABLE<=i<TABLE+4 or CLONE<=i<CLONE+len(blob) for i,(a,b) in enumerate(zip(parent,candidate)))
 result=DEST/'ggen_advance_transform_badges_clean_background_v2_20260909.gba';result.write_bytes(candidate)
 gallery(images,DEST/'badges_before_after.png',5)
 gallery(blanks,DEST/'clean_backgrounds.png',5)
 report={'parent':{'sha256':sha(parent)},'output':{'path':str(result.relative_to(ROOT)),'sha256':sha(candidate),'size':len(candidate)},'resource':{'table':hex(TABLE),'original_atlas':hex(source),'clone':hex(CLONE),'blob_size':len(blob)},'labels':reports,'live_states':live_reports,'verification':{'result':'PASS','both_states_rom_crc_match':True,'all_32_live_target_tiles_exact':True,'compression_roundtrip':True,'unrelated_atlas_tiles_unchanged':True,'size_badges_maps_9_to_16_unchanged':True,'outside_main_canvas_target_rectangles_unchanged':True,'native_badge_perimeters_preserved':True,'clone_allocation_zero_and_no_aligned_pointer_references':True,'only_clone_and_single_atlas_pointer_changed':True,'runtime_emulator':'not run; supplied state tile ownership and static reconstruction verified'}}
 report['background_reconstruction']={'donor':'same resource main map, empty name field at x=0..39, y=112..127','move':'native left cap and gradient copied directly','aptitude':'native left cap shifted by two pixels and mirrored','verification':'blank plates contain no palette index 4/5; every final dark pixel belongs to the new Korean outline; all pixels outside new glyph/outline match the clean plate'}
 report['verification']['clean_background_contains_no_japanese_dark_pixels']=True
 report['verification']['only_new_korean_glyph_and_outline_added_to_clean_plate']=True
 (DEST/'manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
 print(json.dumps({'output':report['output'],'verification':report['verification']},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
