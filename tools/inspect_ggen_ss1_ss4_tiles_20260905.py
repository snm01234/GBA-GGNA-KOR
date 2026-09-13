from pathlib import Path
import struct,json
import analyze_ggen_advance_unit_list_sprite_state_20260830 as s
import analyze_ggen_advance_intermission_cycle_states_20260830 as bg
import analyze_ggen_advance_fixed_word_semantics_20260830 as sem
import build_ggen_advance_turn_ability_overlays_20260905 as t
from PIL import Image,ImageDraw
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs/20260905_ggen_ss1_ss4_tiles'
OUT.mkdir(parents=True,exist_ok=True)
rom=(ROOT/'SD Gundam GGeneration Advance (Korean).gba').read_bytes()
states=[]
for n in range(1,5):
 st,_=s.parse_png_state(ROOT/f'SD Gundam GGeneration Advance (Korean).ss{n}')
 states.append(st)
 res={}
 for i in range(100):
  off=s.STATE_IWRAM+0x1f98+i*40
  p=struct.unpack_from('<I',st,off)[0]
  if 0x08000000<=p<0x0a000000:res.setdefault(hex(p),[]).append(i)
 print('STATE',n,'resources',res)
 for l in range(4):bg.render_bg(st,bg.bg_info(st,l),OUT/f'ss{n}_bg{l}.png')
 for table in [0xd54e4,0xd87bc,0xdab70,0xe0518]:
  p=struct.unpack_from('<I',rom,table)[0]-0x08000000
  h=struct.unpack_from('<I',rom,p)[0]
  atlas=sem.lzss_decompress(rom[p+4:p+4+(h&65535)]) if h>>16==0x8000 else rom[p+4:p+4+h]
  matches=sum(st[s.STATE_VRAM+i:s.STATE_VRAM+i+32] in atlas for i in range(0,65536,32))
  print(hex(table),hex(p),hex(h),len(atlas),matches)
streams=bg.accepted_streams(rom)
for n,l,box in [(1,2,(0,72,48,104)),(1,2,(32,120,80,152)),(1,1,(112,24,144,40)),(2,1,(208,16,240,32)),(3,1,(8,136,48,152))]:
 st=states[n-1]; info=bg.bg_info(st,l);vram=st[s.STATE_VRAM:s.STATE_IWRAM];live={}
 for y in range(box[1]//8,box[3]//8):
  for x in range(box[0]//8,box[2]//8):
   cell=bg.map_entry(vram,info['screen_base'],info['size'],x,y);tid=cell&1023
   live[tid]=vram[info['char_base']+tid*32:info['char_base']+tid*32+32]
 print('TARGET',n,l,box,bg.match_streams(live,streams)[:2])
 for tid,raw in live.items():
  hits=[];pos=rom.find(raw)
  while pos>=0 and len(hits)<10:
   hits.append(hex(pos));pos=rom.find(raw,pos+1)
  print(hex(tid),hits)
