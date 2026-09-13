#!/usr/bin/env python3
"""Bind ss2/ss3 散開/維持 live BG2 tiles to nearby direct graphic owners."""
from __future__ import annotations
import json, sys
from pathlib import Path
THIS_DIR=Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path: sys.path.insert(0,str(THIS_DIR))
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
import analyze_ggen_advance_intermission_cycle_states_20260830 as bg
from ggen_ss_tiles_common_20260905 import direct, canvas_direct
from ggen_advance_project_paths import ADVANCE_ROOT

ROM=ADVANCE_ROOT/'SD Gundam GGeneration Advance (Korean).gba'
OUT=ADVANCE_ROOT/'analysis'/'ggen_advance_scatter_maintain_direct_owners_20260905.json'


def target_tile_rows(state:bytes):
 info=bg.bg_info(state,2);vram=state[statefmt.STATE_VRAM:statefmt.STATE_IWRAM]
 coords={
  'scatter':[(x,y) for y in (120,128) for x in range(24,80,8)],
  'maintain':[(x,y) for y in (136,144) for x in range(24,80,8)],
 }
 result={}
 for name,pts in coords.items():
  rows=[]
  for sx,sy in pts:
   wx,wy=sx+info['scroll_x'],sy+info['scroll_y']
   entry=bg.map_entry(vram,info['screen_base'],info['size'],wx//8,wy//8)
   tid=entry&0x3ff;off=info['char_base']+tid*32
   rows.append({'screen':[sx,sy],'tile':tid,'pal':(entry>>12)&15,'raw':bytes(vram[off:off+32])})
  result[name]=rows
 return result


def main():
 rom=ROM.read_bytes();states={}
 for n in (2,3):
  st,_=statefmt.parse_png_state(ADVANCE_ROOT/f'SD Gundam GGeneration Advance (Korean).ss{n}')
  states[n]=target_tile_rows(st)
 wanted={}
 for n,groups in states.items():
  for name,rows in groups.items():
   for row in rows:
    if any(row['raw']): wanted.setdefault(row['raw'],[]).append({'state':n,'label':name,'screen':row['screen'],'tile':row['tile'],'pal':row['pal']})
 owners=[]
 # This entire family lives in the A9xxxx direct graphics table.
 for off in range(0x00A98000,0x00A9CE14,4):
  try:m=direct(rom,off)
  except Exception:continue
  hits=[]
  for tid in range(m['size']//32):
   raw=rom[m['graphics_offset']+tid*32:m['graphics_offset']+(tid+1)*32]
   if raw in wanted:
    hits.append({'source_tile':tid,'live':wanted[raw]})
  if hits:
   c=canvas_direct(rom,m)
   owners.append({'owner':off,'width':m['width'],'height':m['height'],'graphics_offset':m['graphics_offset'],'graphics_size':m['size'],'palette_offset':m['palette_offset'],'hits':hits,'canvas_rows':[''.join(format(v,'X') for v in row) for row in c]})
 # palette banks used in the two states, for normal/focus/disabled comparison
 pals={}
 for n in (2,3):
  st,_=statefmt.parse_png_state(ADVANCE_ROOT/f'SD Gundam GGeneration Advance (Korean).ss{n}')
  p=st[statefmt.STATE_PALETTE:statefmt.STATE_OAM]
  used=sorted({r['pal'] for g in states[n].values() for r in g})
  pals[n]={str(i):bytes(p[i*32:(i+1)*32]).hex() for i in used}
 value_counts={}
 for n,groups in states.items():
  value_counts[str(n)]={}
  for name,rows in groups.items():
   counts={}
   for row in rows:
    for b in row['raw']:
     for v in (b&15,b>>4): counts[str(v)]=counts.get(str(v),0)+1
   value_counts[str(n)][name]=counts
 report={'owners':owners,'live':{str(n):{name:[{k:v for k,v in r.items() if k!='raw'} for r in rows] for name,rows in groups.items()} for n,groups in states.items()},'palettes':pals,'value_counts':value_counts}
 OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 target_canvases={hex(o['owner']):o['canvas_rows'] for o in owners if o['owner'] in (0xA9C264,0xA9C43C,0xA9CA24,0xA9CBFC)}
 print(json.dumps({'owners':[{'owner':hex(o['owner']),'size':[o['width'],o['height']],'gfx':hex(o['graphics_offset']),'hits':len(o['hits'])} for o in owners], 'target_canvases':target_canvases, 'value_counts':value_counts, 'live':report['live'], 'palette_same':{str(i):pals[2].get(str(i))==pals[3].get(str(i)) for i in sorted(set(map(int,pals[2]))|set(map(int,pals[3])))}},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
