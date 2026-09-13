#!/usr/bin/env python3
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import analyze_ggen_advance_fixed_word_semantics_20260830 as sem
ROOT=Path(__file__).resolve().parents[1]
r=(ROOT/'SD Gundam GGeneration Advance (Japan).gba').read_bytes();cm=json.loads((ROOT/'analysis/ggen_advance_12x12_identified_charmap_20260828.json').read_text(encoding='utf8'))['verified_charmap'];rev={v:int(k,16) for k,v in cm.items() if isinstance(v,str)}
for term in ['攻撃','威力','射程','防御','運動','移動','回復','回避','命中','装甲','反応']:
 print('\nTERM',term)
 pts=set()
 for ci,ch in enumerate(term):pts|={(ci*12+x,y) for x,y in sem.glyph_points(r,rev[ch])}
 for y in range(12):print(''.join('#' if (x,y) in pts else ' ' for x in range(24)))
