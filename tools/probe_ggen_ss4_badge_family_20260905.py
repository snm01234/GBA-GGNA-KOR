#!/usr/bin/env python3
import struct,sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import analyze_ggen_advance_fixed_word_semantics_20260830 as sem
from analyze_ggen_advance_action_graphics_scan_20260830 import lzss_decompress
ROOT=Path(__file__).resolve().parents[1];T=0xE0518

def u32(b,o):return struct.unpack_from('<I',b,o)[0]
def atlas(b):
 p=u32(b,T)-0x8000000;h=u32(b,p);return p,lzss_decompress(b[p+4:p+4+(h&65535)])
def main():
 jp=(ROOT/'SD Gundam GGeneration Advance (Japan).gba').read_bytes();ko=(ROOT/'SD Gundam GGeneration Advance (Korean).gba').read_bytes();pj,aj=atlas(jp);pk,ak=atlas(ko)
 out=[]
 for idx in range(20,29):
  m=sem.parse_map(jp,u32(jp,T+idx*4)); ids=[x&1023 for x in m['cells']]
  c=sem.stitch(aj,m)
  rows=[''.join(format(v,'X') for v in row) for row in c]
  out.append({'resource':idx,'ids':ids,'current_equals_jp':[ak[i*32:(i+1)*32]==aj[i*32:(i+1)*32] for i in ids],'rows':rows})
 print(json.dumps({'jp_atlas':hex(pj),'ko_atlas':hex(pk),'resources':out},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
