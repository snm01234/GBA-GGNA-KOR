from pathlib import Path
import struct
from PIL import Image,ImageDraw
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
import analyze_ggen_advance_fixed_word_semantics_20260830 as sem
import build_ggen_advance_turn_ability_overlays_20260905 as raster
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs/20260905_ggen_ss1_ss4_tiles'
def u16(b,o):return struct.unpack_from('<H',b,o)[0]
def u32(b,o):return struct.unpack_from('<I',b,o)[0]
def direct(r,o):
 w,h=r[o+2:o+4];mr=u16(r,o+4);gr=u16(r,o+8);size=u16(r,o+10);pr=u16(r,o+12)
 assert u16(r,o)==2 and mr==16 and gr==(mr+w*h*2+3)&~3 and pr==gr+size
 ids=list(struct.unpack_from(f'<{w*h}H',r,o+mr))
 assert max(i&1023 for i in ids)*32<size
 return {'offset':o,'width':w,'height':h,'cells':ids,'graphics_offset':o+gr,'size':size,'palette_offset':o+pr}
def canvas_direct(r,m):return sem.stitch(r[m['graphics_offset']:m['graphics_offset']+m['size']],m)
def gallery(items,path,scale=3):
 width=max(440,max(im.width*scale+180 for _,im in items));height=sum(max(im.height*scale+8,30) for _,im in items)
 sheet=Image.new('RGB',(width,height),(35,35,35));d=ImageDraw.Draw(sheet);y=0
 for name,im in items:
  d.text((4,y+4),name,fill='white');sheet.paste(im.resize((im.width*scale,im.height*scale),Image.Resampling.NEAREST),(180,y));y+=max(im.height*scale+8,30)
 sheet.save(path)
if __name__=='__main__':
 r=(ROOT/'SD Gundam GGeneration Advance (Korean).gba').read_bytes();items=[];metadata=[]
 for o in range(0xa98000,0xa9ce14,4):
  try:m=direct(r,o)
  except (AssertionError,ValueError,struct.error):continue
  metadata.append(m);items.append((hex(o),raster.render_canvas(canvas_direct(r,m),raster.palette_rgb(r[m['palette_offset']:m['palette_offset']+32]))))
 gallery(items,OUT/'direct_catalog.png',2)
 import json
 (OUT/'direct_catalog.json').write_text(json.dumps(metadata,indent=2))
 st,_=statefmt.parse_png_state(ROOT/'SD Gundam GGeneration Advance (Korean).ss2')
 colors=raster.palette_rgb(st[statefmt.STATE_PALETTE+160:statefmt.STATE_PALETTE+192]);p=u32(r,0xd87bc)-0x8000000;a=sem.lzss_decompress(r[p+4:p+4+(u32(r,p)&65535)])
 gallery([(str(i),raster.render_canvas(sem.stitch(a,sem.parse_map(r,u32(r,0xd87bc+i*4))),colors)) for i in range(8,13)],OUT/'ss2_family.png',5)



