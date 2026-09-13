from ggen_ss_tiles_common_20260905 import *
import analyze_ggen_advance_intermission_cycle_states_20260830 as bg
import analyze_ggen_advance_remaining_ui_draw_calls_20260902 as draw
r=(ROOT/'SD Gundam GGeneration Advance (Korean).gba').read_bytes()
streams=bg.accepted_streams(r)
for n,l,box in [(8,1,(32,16,144,32)),(9,2,(80,36,160,52))]:
 st,_=statefmt.parse_png_state(ROOT/f'SD Gundam GGeneration Advance (Korean).ss{n}');info=bg.bg_info(st,l);v=st[0x1000:0x19000];live={}
 print(n,info)
 for y in range(box[1]//8,(box[3]+7)//8):
  cells=[]
  for x in range(box[0]//8,(box[2]+7)//8):
   c=bg.map_entry(v,info['screen_base'],info['size'],x,y);cells.append(hex(c));tid=c&1023;live[tid]=v[info['char_base']+tid*32:info['char_base']+(tid+1)*32]
  print(cells)
 print(bg.match_streams(live,streams)[:2])
 for tid,raw in list(live.items())[:8]:print(hex(tid),hex(r.find(raw)))
