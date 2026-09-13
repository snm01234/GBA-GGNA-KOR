#!/usr/bin/env python3
"""Targeted glyph-shape identification for status-table 4x2 badges used around ss4."""
from __future__ import annotations
import json, struct, sys
from pathlib import Path
THIS=Path(__file__).resolve().parent
if str(THIS) not in sys.path: sys.path.insert(0,str(THIS))
import analyze_ggen_advance_fixed_word_semantics_20260830 as sem
from analyze_ggen_advance_action_graphics_scan_20260830 import lzss_decompress
from ggen_advance_project_paths import ADVANCE_ROOT

JP=ADVANCE_ROOT/'SD Gundam GGeneration Advance (Japan).gba'
CM=ADVANCE_ROOT/'analysis'/'ggen_advance_12x12_identified_charmap_20260828.json'
OUT=ADVANCE_ROOT/'analysis'/'ggen_advance_ss4_stat_badge_semantics_20260905.json'
TABLE=0x000E0518
TERMS=[
 '命中','反応','威力','攻撃','防御','回避','装甲','運動','限界','移動','射撃','近接','操縦','格闘',
 '射程','範囲','相性','地形','地上','宇宙','万能','水陸','飛行','汎用','能力','情報','補給','回復',
 '命中率','回避率','反応値','移動力','攻撃力','防御力'
]

def u32(b,o): return struct.unpack_from('<I',b,o)[0]
def dice(a,b): return 2*len(a&b)/(len(a)+len(b)) if a and b else 0.0

def main():
 data=JP.read_bytes(); cm=json.loads(CM.read_text(encoding='utf-8'))['verified_charmap']; rev={v:int(k,16) for k,v in cm.items() if isinstance(v,str)}
 terms=[t for t in TERMS if all(ch in rev for ch in t)]
 glyph={ch:sem.glyph_points(data,rev[ch]) for t in terms for ch in t}
 ptr=u32(data,TABLE); off=ptr-0x08000000; h=u32(data,off); atlas=lzss_decompress(data[off+4:off+4+(h&0xffff)])
 rows=[]
 for idx in range(20,29):
  obj=sem.parse_map(data,u32(data,TABLE+idx*4)); assert obj and (obj['width'],obj['height'])==(4,2)
  pix=sem.stitch(atlas,obj); values={str(v):{(x,y) for y in range(16) for x in range(32) if pix[y][x]==v} for v in range(1,16)}
  # This purple/blue badge family shades the Japanese face across indices 6 and 7.
  # Combined planes are included so gradient shading does not weaken glyph matching.
  values['6+7']={(x,y) for y in range(16) for x in range(32) if pix[y][x] in (6,7)}
  values['5+6+7']={(x,y) for y in range(16) for x in range(32) if pix[y][x] in (5,6,7)}
  hits=[]
  for t in terms:
   width=len(t)*12
   if width>32: continue
   for x0 in range(0,32-width+1):
    for y0 in range(0,5):
     target=set()
     for ci,ch in enumerate(t):
      target|={(x0+ci*12+x,y0+y) for x,y in glyph[ch]}
     for v,obs in values.items():
      s=dice(target,obs)
      if s>=0.35: hits.append({'term':t,'score':s,'value':v,'x':x0,'y':y0,'target':len(target),'observed':len(obs),'intersection':len(target&obs)})
  hits.sort(key=lambda z:z['score'],reverse=True)
  rows.append({'resource_index':idx,'file_offset':hex(obj['offset']),'tiles':[hex(c&1023) for c in obj['cells']],'palette_banks':sorted({c>>12 for c in obj['cells']}),'top':hits[:30]})
 OUT.write_text(json.dumps({'terms':terms,'resources':rows},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps([{'resource':r['resource_index'],'top':r['top'][:8]} for r in rows],ensure_ascii=False,indent=2))
if __name__=='__main__': main()
