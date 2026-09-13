"""Clean 指揮/範囲 on C5A5DC animation 1, preserving other animations."""
from ggen_ss_tiles_common_20260905 import *
from ggen_advance_project_paths import MAIN_TIP_ROM,MAIN_TIP_MANIFEST,FONT_ZIP
import build_ggen_advance_ss1_ss2_graphics_ko_test_20260902 as ss
import build_ggen_advance_remodel_anim3_followup_20260905 as paint
import render_ggen_ss_tiles_20260905 as renderer
from zipfile import ZipFile
import hashlib,json

DEST=ROOT/'outputs/20260907_ggen_ss1_command_range_badges'
SOURCE=0x8C5A5DC
TARGET=0x9FD0000
def sha(b):return hashlib.sha256(b).hexdigest()

def main():
 DEST.mkdir(exist_ok=True)
 parent=MAIN_TIP_ROM.read_bytes()
 assert sha(parent)==json.loads(MAIN_TIP_MANIFEST.read_text(encoding='utf8'))['sha256']
 statepath=ROOT/'SD Gundam GGeneration Advance (Korean).ss1'
 st,_=statefmt.parse_png_state(statepath)
 h=ss.spr.parse_resource_header(parent,SOURCE)
 before,_,_=ss.resource_canvas(parent,SOURCE,1)
 after=[r[:] for r in before];clean=[r[:] for r in before]
 rects=[(10,38,'指揮','지휘'),(56,86,'範囲','범위')]
 reports=[]
 with ZipFile(FONT_ZIP) as z:font=paint.fontpair.load_bdf(z,'Galmuri11.bdf')
 for left,right,jp,ko in rects:
  for y in range(144,160):
   donor=before[y][44]
   assert donor in (6,9,10,11)
   after[y][left:right]=[donor]*(right-left)
   clean[y][left:right]=[donor]*(right-left)
  reports.append({'source':jp,'korean':ko,'paint':paint.paint_text(after,(left,144,right,160),ko,font)})
 assert all(v==before[y][x] for y,row in enumerate(after) for x,v in enumerate(row) if not(y>=144 and (10<=x<38 or 56<=x<86)))
 _,records=ss.animrec.animation_records(parent,SOURCE)
 parsed,ids,lookup=ss.parse_animation_cross(records,1)
 objects=parsed['objects'];minx=min(int(o['x']) for o in objects);miny=min(int(o['y']) for o in objects)
 graphics=bytearray(h['graphics']);prefix=bytearray(parent[h['offset']:h['offset']+h['graphics_rel']])
 cursor=0;edits=0
 for obj in objects:
  wt,ht=[int(v)//8 for v in obj['size_px']]
  for ty in range(ht):
   for tx in range(wt):
    x=int(obj['x'])-minx+tx*8;y=int(obj['y'])-miny+ty*8
    raw=raster.encode_tile([row[x:x+8] for row in after[y:y+8]])
    old=ids[cursor+ty*wt+tx]
    if raw==h['graphics'][old*32:old*32+32]:continue
    new=len(graphics)//32;graphics.extend(raw)
    struct.pack_into('<H',prefix,lookup-h['offset']+(cursor+ty*wt+tx)*2,new);edits+=1
  cursor+=wt*ht
 assert graphics[:len(h['graphics'])]==h['graphics']
 struct.pack_into('<I',prefix,12,len(prefix)+len(graphics))
 blob=prefix+graphics+h['palettes'];off=TARGET-0x8000000
 assert not any(parent[off:off+len(blob)])
 owners=raster.pointer_hits(parent,SOURCE);assert owners==[459056,459124,459920,460836]
 candidate=bytearray(parent);candidate[off:off+len(blob)]=blob
 for p in owners:struct.pack_into('<I',candidate,p,TARGET)
 for anim in range(5):
  a,p,b=ss.resource_canvas(parent,SOURCE,anim);c,q,d=ss.resource_canvas(candidate,TARGET,anim)
  assert p==q and b==d and c==(after if anim==1 else a)
 cursor=0
 for a,b in sorted([(p,p+4) for p in owners]+[(off,off+len(blob))]):
  assert candidate[cursor:a]==parent[cursor:a];cursor=b
 assert candidate[cursor:]==parent[cursor:]
 # Validate the visible OBJ tiles against the source before replacing them.
 derived=bytearray(st);live_count=0
 for i in range(51,57):
  e=statefmt.parse_oam_entry(st[0xC00:0x1000],i)
  assert e['palette_bank']==5 and not(int(e['attr1'],16)&0x3000)
  for ty in range(e['height']//8):
   for tx in range(e['width']//8):
    x=e['x']-128+tx*8;y=e['y']+ty*8
    assert 0<=x<112 and 144<=y<160
    pos=0x11000+(e['tile']+ty*(e['width']//8)+tx)*32
    old=raster.encode_tile([row[x:x+8] for row in before[y:y+8]])
    assert st[pos:pos+32]==old
    raw=raster.encode_tile([row[x:x+8] for row in after[y:y+8]])
    derived[pos:pos+32]=raw;live_count+=1
 result=DEST/'ggen_ss1_command_range_badges_ko_20260907.gba';result.write_bytes(candidate)
 result.with_suffix('.ss1').write_bytes(raster.replace_state_chunk(statepath,derived))
 renderer.OUT=DEST
 for name,data in [('before',st),('after',derived)]:
  renderer.render(data).resize((720,480),Image.Resampling.NEAREST).save(DEST/f'{name}.png')
 colors=raster.palette_rgb(st[0xAA0:0xAC0]);im=Image.new('RGB',(112,16));px=im.load()
 for y in range(16):
  for x in range(112):px[x,y]=colors[clean[y+144][x]]
 im.resize((672,96),Image.Resampling.NEAREST).save(DEST/'clean_badge.png')
 report={'parent_sha256':sha(parent),'reference_state_sha256':sha(statepath.read_bytes()),
  'output':{'path':str(result.relative_to(ROOT)),'size':len(candidate),'sha256':sha(candidate)},'translations':reports,
  'resource':{'source':hex(SOURCE),'target':hex(TARGET),'animation':1,'owners':[hex(p) for p in owners],'appended_tiles':edits,'bytes':len(blob)},
  'verification':{'result':'PASS','live_obj_tiles_match':live_count,'old_glyph_and_shadow_removed':True,'native_row_gradient_restored':True,'other_four_animations_pixel_exact':True,'outside_label_rectangles_pixel_exact':True,'old_graphics_and_other_rom_data_preserved':True,'runtime':'ROM resource and supplied-state rendering verified; live emulator transitions not run'}}
 (DEST/'manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
 print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
