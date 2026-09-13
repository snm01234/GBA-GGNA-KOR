from ggen_ss_tiles_common_20260905 import *
import analyze_ggen_advance_intermission_cycle_states_20260830 as bg
import analyze_ggen_advance_remaining_ui_draw_calls_20260902 as draw
r=(ROOT/'SD Gundam GGeneration Advance (Korean).gba').read_bytes()
for o,box in [(0xa98480,(0,72,48,104)),(0xa99cfc,(0,16,40,32)),(0xa9be94,(40,0,72,16)),(0xa9c634,(40,0,72,16))]:
 m=direct(r,o);c=canvas_direct(r,m);print(hex(o),m)
 for row in c[box[1]:box[3]]:print(''.join(hex(i)[2:] for i in row[box[0]:box[2]]))
for n,l,x,y in [(2,1,208,16),(3,1,8,136)]:
 st,_=statefmt.parse_png_state(ROOT/f'SD Gundam GGeneration Advance (Korean).ss{n}');c,_=draw.layer_pixels(st,l);info=bg.bg_info(st,l);cell=bg.map_entry(st[statefmt.STATE_VRAM:statefmt.STATE_IWRAM],info['screen_base'],info['size'],x//8,y//8);print(n,'bank',cell>>12)
 for row in c[y:y+16]:print(''.join(hex(i)[2:] for i in row[x:x+40]))
