#!/usr/bin/env python3
"""List connected green (palette 12..14) components in ss4 stat badges."""
from __future__ import annotations
import collections, json, struct, sys
from pathlib import Path
THIS=Path(__file__).resolve().parent
if str(THIS) not in sys.path: sys.path.insert(0,str(THIS))
import analyze_ggen_advance_fixed_word_semantics_20260830 as sem
import build_ggen_advance_status_ui_tile_overlay_poc as status
from ggen_advance_project_paths import MAIN_TIP_ROM
TABLE=0x000E0518
GREEN={12,13,14}
def u32(b,o): return struct.unpack_from('<I',b,o)[0]
def main():
 rom=MAIN_TIP_ROM.read_bytes(); p=u32(rom,TABLE)-0x08000000; h=u32(rom,p); atlas=status.lzss_decompress(rom[p+4:p+4+(h&0xffff)])
 result=[]
 for idx in (21,23,24,25,27):
  m=sem.parse_map(rom,u32(rom,TABLE+idx*4)); c=sem.stitch(atlas,m)
  pts={(x,y) for y in range(16) for x in range(32) if c[y][x] in GREEN}; comps=[]
  while pts:
   seed=pts.pop(); q=[seed]; comp={seed}
   while q:
    x,y=q.pop()
    for n in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
     if n in pts: pts.remove(n); comp.add(n); q.append(n)
   xs=[p[0] for p in comp]; ys=[p[1] for p in comp]
   comps.append({'size':len(comp),'bbox':[min(xs),min(ys),max(xs)+1,max(ys)+1],'touch_text_edge':any(x in (0,23) or y in (1,13) for x,y in comp),'coords':sorted([list(p) for p in comp],key=lambda v:(v[1],v[0]))})
  comps.sort(key=lambda a:(-a['size'],a['bbox']))
  result.append({'resource':idx,'components':comps})
 if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
 print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
