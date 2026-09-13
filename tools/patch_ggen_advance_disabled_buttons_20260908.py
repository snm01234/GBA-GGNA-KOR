"""Close the remaining known disabled-button raster and audit shared variants."""
import json
from collections import Counter
from zipfile import ZipFile
from pathlib import Path
import build_ggen_advance_allclear_continue_active_ko_20260905 as a
import analyze_ggen_advance_ss1_ss2_graphics_20260902 as transport
import build_ggen_advance_ss1_ss2_graphics_ko_test_20260902 as transport_builder
import struct
from ggen_ss_tiles_common_20260905 import direct, canvas_direct
from ggen_advance_project_paths import MAIN_TIP_ROM, MAIN_TIP_MANIFEST, ORIGINAL_ROM, FONT_ZIP

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs/20260908_ggen_advance_disabled_buttons'

def main():
 parent=MAIN_TIP_ROM.read_bytes();jp=ORIGINAL_ROM.read_bytes()
 assert a.sha256(parent)==json.loads(MAIN_TIP_MANIFEST.read_text(encoding='utf8'))['sha256']
 off,_,grel,prel,graphics,palettes=a.load_graphics(parent)
 *_,jg,jpal=a.load_graphics(jp)
 _,records=a.sprite.animation_records(parent,a.base.RESOURCE)
 anim={i:a.base.old.animation_info(records,i) for i in range(26)}
 before={i:a.base.old.canvas_for(graphics,n) for i,n in anim.items()}
 native={i:a.base.old.canvas_for(jg,n) for i,n in anim.items()}
 assert before[20]==native[20]
 for i in (18,19,21):assert before[i]!=native[i]
 plate,_=a.base.build_active_clean_plate([native[i] for i in a.base.ACTIVE_PLATE_ANIMS])
 clean=a.base.apply_plate(before[20],a.base.build_disabled_clean_plate(plate))
 with ZipFile(FONT_ZIP) as z:font=a.base.fontpair.load_bdf(z,'Galmuri11.bdf')
 desired,paint=a.base.render_korean(clean,'로드',font,4)
 ink={(x,y) for y in range(16) for x in range(80) if desired[y][x]!=clean[y][x]}
 users={sid:{i for i,n in anim.items() if sid in n['source_ids']} for sid in range(240)}
 patched=bytearray(graphics);skipped=set();updates={}
 for sid,x,y in anim[20]['positions']:
  raw=a.base.old.encode_tile([desired[y+k][x:x+8] for k in range(8)])
  if raw==graphics[sid*32:(sid+1)*32]:continue
  if users[sid]-{20}:
   coords={(xx,yy) for yy in range(y,y+8) for xx in range(x,x+8)}
   assert not coords&ink;skipped|=coords;continue
  assert sid not in updates or updates[sid]==raw
  updates[sid]=raw;patched[sid*32:(sid+1)*32]=raw
 assert updates
 after={i:a.base.old.canvas_for(patched,n) for i,n in anim.items()}
 diffs={(x,y) for y in range(16) for x in range(80) if after[20][y][x]!=desired[y][x]}
 assert diffs<=skipped and not diffs&ink
 assert all(after[i]==before[i] for i in range(26) if i!=20)
 # Recheck all previously translated disabled title labels against their
 # expected Korean ink/outline, rather than merely relying on old reports.
 audit=[]
 for i,text in [(18,'이어하기'),(19,'부록'),(20,'로드'),(21,'컨티뉴')]:
  base=a.base.apply_plate(native[i],a.base.build_disabled_clean_plate(plate))
  expected,_=a.base.render_korean(base,text,font,4)
  mask={(x,y) for y in range(16) for x in range(80) if expected[y][x]!=base[y][x]}
  assert all(after[i][y][x]==expected[y][x] for x,y in mask),text
  audit.append({'family':'title','text':text,'animation':i,'result':'Korean ink verified'})
 # Transport commands use the same tile multiset under a disabled palette;
 # two animations reorder padding objects, so compare multisets, not order.
 active_transport=struct.unpack_from('<I',parent,0x66CE8)[0]
 assert active_transport==transport_builder.SS1_CLONE_ADDR
 header=transport.spriteutil.parse_resource_header(parent,active_transport)
 jheader=transport.spriteutil.parse_resource_header(jp,transport.OBJ_RESOURCE)
 transport_previews=[]
 for i,text in enumerate(['탑재','내리기','이동','변형']):
  normal=transport.parse_animation_cross(parent,active_transport,i)
  disabled=transport.parse_animation_cross(parent,active_transport,i+8)
  assert Counter(normal['source_ids'])==Counter(disabled['source_ids'])
  ko_canvas,_,_=transport_builder.resource_canvas(parent,active_transport,i+8)
  jp_canvas,_,_=transport_builder.resource_canvas(jp,transport.OBJ_RESOURCE,i+8)
  assert ko_canvas!=jp_canvas
  audit.append({'family':'transport','text':text,'animation':i+8,'result':'shares translated normal graphics; palette-only disabled style'})
 # Measured scatter/maintain disabled states reuse these normal direct owners.
 for owner,text in [(0xA9C264,'산개'),(0xA9C43C,'유지')]:
  assert canvas_direct(parent,direct(parent,owner))!=canvas_direct(jp,direct(jp,owner))
  audit.append({'family':'formation','text':text,'owner':hex(owner),'result':'translated normal raster preserved; disabled shares raster per measured family'})
 candidate=bytearray(parent);candidate[off+grel:off+prel]=patched
 assert candidate[:off+grel]==parent[:off+grel] and candidate[off+prel:]==parent[off+prel:]
 OUT.mkdir(exist_ok=True);result=OUT/'ggen_advance_disabled_buttons_candidate_20260908.gba';result.write_bytes(candidate)
 from PIL import Image,ImageDraw
 preview=Image.new('RGB',(660,6*80),(30,30,30));draw=ImageDraw.Draw(preview)
 for row,(name,canvas) in enumerate([('load before',before[20]),('load after',after[20]),('continue reference',after[21]),('continue from save',after[18]),('extras',after[19]),('load active reference',after[5])]):
  draw.text((4,row*80+8),name,fill='white');preview.paste(a.base.image_for(canvas,palettes[:32],6),(165,row*80))
 preview.save(OUT/'disabled_family.png')
 report={'parent':{'sha256':a.sha256(parent)},'output':{'path':str(result.relative_to(ROOT)),'sha256':a.sha256(candidate),'size':len(candidate)},'fixed':{'translation':'ロード → 로드','animation':20,'resource':hex(a.base.RESOURCE),'tiles':sorted(updates),'paint':paint},'audit':audit,'verification':{'result':'PASS','all_other_25_title_animations_pixel_exact':True,'shared_tiles_preserved':True,'other_rom_regions_unchanged':True,'runtime_emulator':'not run; ROM resource and Korean raster verification'},'scope':'Known disabled title, transport, formation and previously fixed action-menu families; no claim of exhaustive game-state traversal.'}
 (OUT/'manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8');print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
