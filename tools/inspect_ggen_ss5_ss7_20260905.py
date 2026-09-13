from ggen_ss_tiles_common_20260905 import *
import analyze_ggen_advance_intermission_cycle_states_20260830 as bg
import analyze_ggen_advance_remaining_ui_draw_calls_20260902 as draw
OUT=ROOT/'outputs/20260905_ggen_ss5_ss7_tiles';OUT.mkdir(exist_ok=True)
r=(ROOT/'SD Gundam GGeneration Advance (Korean).gba').read_bytes()
for n in (5,7):
 st,_=statefmt.parse_png_state(ROOT/f'SD Gundam GGeneration Advance (Korean).ss{n}')
 print('STATE',n)
 for l in range(4):bg.render_bg(st,bg.bg_info(st,l),OUT/f'ss{n}_bg{l}.png')
 resources={}
 for i in range(100):
  p=u32(st,0x19000+0x1f98+i*40)
  if 0x8000000<=p<0xa000000:resources.setdefault(hex(p),[]).append(i)
 print(resources)
 if n==5:
  info=bg.bg_info(st,1);v=st[0x1000:0x19000]
  print('BG1',info)
  for y in (16,17):print([hex(bg.map_entry(v,info['screen_base'],info['size'],x,y)) for x in range(1,13)])
 else:
  for i in range(128):
   e=statefmt.parse_oam_entry(st[0xc00:0x1000],i);a=int(e['attr0'],16)
   if a&0x300==0x200 or not(e['y']<95 and e['y']+e['height']>81 and e['x']<145 and e['x']+e['width']>98):continue
   print('OBJ',e)
   for tid in range(e['tile'],e['tile']+e['width']//8*e['height']//8):
    raw=st[0x11000+tid*32:0x11000+(tid+1)*32];hits=[];p=r.find(raw)
    while p>=0 and len(hits)<8:hits.append(hex(p));p=r.find(raw,p+1)
    print(hex(tid),hits)
