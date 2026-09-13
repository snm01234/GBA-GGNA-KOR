#!/usr/bin/env python3
"""Find live palette variants of the ss4 E0518 effect/stat badge tiles in all current ss states."""
from __future__ import annotations
import json,struct,sys
from pathlib import Path
THIS=Path(__file__).resolve().parent
if str(THIS) not in sys.path:sys.path.insert(0,str(THIS))
import analyze_ggen_advance_unit_list_sprite_state_20260830 as sf
import analyze_ggen_advance_intermission_cycle_states_20260830 as bg
from analyze_ggen_advance_action_graphics_scan_20260830 import lzss_decompress
from ggen_advance_project_paths import ADVANCE_ROOT
T=0xE0518
LABELS={21:'운동',23:'위력',24:'명중',25:'장갑',26:'회복',27:'반응',28:'운동'}
def u32(b,o):return struct.unpack_from('<I',b,o)[0]
def parse_map(b,p):
 o=p-0x8000000;w,h=b[o],b[o+1];return list(struct.unpack_from(f'<{w*h}H',b,o+4))
def main():
 rom=(ADVANCE_ROOT/'SD Gundam GGeneration Advance (Korean).gba').read_bytes();p=u32(rom,T)-0x8000000;h=u32(rom,p);a=lzss_decompress(rom[p+4:p+4+(h&65535)])
 raw_to=[];targets={}
 for idx,name in LABELS.items():
  ids=[x&1023 for x in parse_map(rom,u32(rom,T+idx*4))]
  for sid in ids:targets.setdefault(bytes(a[sid*32:(sid+1)*32]),set()).add((idx,name,sid))
 out={}
 for n in range(1,10):
  path=ADVANCE_ROOT/f'SD Gundam GGeneration Advance (Korean).ss{n}'
  if not path.exists():continue
  st,_=sf.parse_png_state(path);v=st[sf.STATE_VRAM:sf.STATE_IWRAM];io=st[sf.STATE_IO:sf.STATE_PALETTE];disp=struct.unpack_from('<H',io,0)[0];hits=[]
  for l in range(4):
   if not(disp&(0x100<<l)):continue
   inf=bg.bg_info(st,l)
   if inf['color_8bpp']:continue
   for sy in range(0,160,8):
    for sx in range(0,240,8):
     wx,wy=sx+inf['scroll_x'],sy+inf['scroll_y'];e=bg.map_entry(v,inf['screen_base'],inf['size'],wx//8,wy//8);tid=e&1023;raw=bytes(v[inf['char_base']+tid*32:inf['char_base']+(tid+1)*32])
     if raw in targets:hits.append({'layer':l,'xy':[sx,sy],'live_tile':tid,'palette':(e>>12)&15,'sources':[list(x) for x in sorted(targets[raw])]})
  out[str(n)]=hits
 (ADVANCE_ROOT/'legacy/analysis/ggen_advance_ss4_badge_state_variants_20260905.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
 print(json.dumps({n:{'hits':len(h),'palettes':sorted({x['palette'] for x in h}),'labels':sorted({s[1] for x in h for s in x['sources']})} for n,h in out.items()},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
