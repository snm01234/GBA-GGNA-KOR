from inspect_ggen_ss1_ss4_tiles_20260905 import ROOT,OUT,rom,states
from PIL import Image,ImageDraw
import analyze_ggen_advance_fixed_word_semantics_20260830 as sem
import build_ggen_advance_turn_ability_overlays_20260905 as t
import analyze_ggen_advance_unit_list_sprite_state_20260830 as s
import struct
colors=t.palette_rgb(states[0][s.STATE_PALETTE:s.STATE_PALETTE+32])
print('palette',colors)
for off in [0xa9beac,0xa9c04c,0xa9c24c,0xa9c424]:print(hex(off),rom[off:off+64].hex())
items=[]
for table,count in [(0xd87bc,13),(0xe0518,69)]:
 p=struct.unpack_from('<I',rom,table)[0]-0x8000000;h=struct.unpack_from('<I',rom,p)[0];atlas=sem.lzss_decompress(rom[p+4:p+4+(h&65535)])
 for i in range(1,count):
  m=sem.parse_map(rom,struct.unpack_from('<I',rom,table+i*4)[0])
  if m and m['width']<=16 and m['height']<=6:
   c=sem.stitch(atlas,m);items.append((f'{table:x}:{i} {m["offset"]:x}',t.render_canvas(c,colors)))
sheet=Image.new('RGB',(660,len(items)*75),(40,40,40));d=ImageDraw.Draw(sheet)
for i,(label,im) in enumerate(items):d.text((0,i*75),label,fill='white');sheet.paste(im.resize((im.width*3,im.height*3)),(180,i*75))
sheet.save(OUT/'maps.png')
st=states[3];oam=st[s.STATE_OAM:s.STATE_OAM+1024]
for i in range(128):
 e=s.parse_oam_entry(oam,i)
 if e['y']<=150 and e['y']+e['height']>144 and e['x']>=128 and int(e['attr0'],16)&0x300!=0x200:
  print('OBJ',e)
  for tid in range(e['tile'],e['tile']+e['width']//8*e['height']//8):
   raw=st[s.STATE_VRAM+0x10000+tid*32:s.STATE_VRAM+0x10000+(tid+1)*32]
   hits=[];p=rom.find(raw)
   while p>=0 and len(hits)<8:hits.append(hex(p));p=rom.find(raw,p+1)
   print(hex(tid),hits)
