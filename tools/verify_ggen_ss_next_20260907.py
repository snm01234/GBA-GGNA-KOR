"""Verify animation source remaps, dialogue boundaries and lookup preservation."""
import sys,json,struct
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'analysis'))
import build_ggen_ss_next_20260907 as b
import ggen_advance_project_paths as p
import analyze_ggen_advance_battle_map_script_gap_20260905 as h
import extract_ggen_advance_map_script_dialogue as e
from ggen_advance_text_codec import *
def main():
 m=json.loads((b.OUT/'manifest.json').read_text(encoding='utf-8'));parent=p.MAIN_TIP_ROM.read_bytes();candidate=(b.c.ROOT/m['output']['path']).read_bytes();jp=p.ORIGINAL_ROM.read_bytes()
 assert b.sha(parent)==m['parent']['sha256'] and b.sha(candidate)==m['output']['sha256']
 # The 53 frame lookup changes must be the only timeline changes.
 src=0x170D1C;clone=b.TITLE_CLONE;gr=0x6200;pr=0x6D20
 st=b.c.statefmt.parse_png_state(b.c.ROOT/'SD Gundam GGeneration Advance (Korean).ss1')[0]
 atlas=parent[src+gr:src+pr];live=st[0x13000:0x13B00]
 ids=[next(i for i in range(89) if atlas[i*32:(i+1)*32]==live[n*32:(n+1)*32]) for n in range(88)]
 old=struct.pack('<88H',*ids);new=struct.pack('<88H',*range(89,177));timeline=bytearray(parent[src:src+gr]);hits=0;cursor=0
 while True:
  cursor=timeline.find(old,cursor)
  if cursor<0:break
  timeline[cursor:cursor+176]=new;cursor+=176;hits+=1
 struct.pack_into('<I',timeline,12,pr+88*32)
 assert hits==53 and candidate[clone:clone+gr]==timeline
 assert candidate[clone+gr:clone+pr]==atlas
 assert candidate[clone+pr+88*32:clone+pr+88*32+192]==parent[src+pr:src+pr+192]
 # Every added segment must return to its own original terminator, including
 # the second line. The bytecode after that terminator is never moved.
 oldh=h.find_hook_table(parent);newh=h.find_hook_table(candidate)
 oldmap=h.load_lookup(parent,oldh['table_address'],oldh['count']);newmap=h.load_lookup(candidate,newh['table_address'],newh['count'])
 for k,v in oldmap.items():assert newmap[k]==v
 for row in m['dialogue']['boxes']:
  for seg in row['segments']:
   o=int(seg['original'],16);n,end=newmap[o+0x8000000];raw=read_tokens(jp,o)[1]
   assert n==int(seg['payload'],16)+0x8000000 and end==0x8000000+o+len(raw)-1 and jp[end-0x8000000]==0
 # The fixed extractor reaches both captured text windows and all 12 siblings.
 extraction=e.extract(p.ORIGINAL_ROM,b.dec.CHARMAP_12X12_PATH);records={r['record_id']:r for r in extraction['records']}
 for key in b.TRANSLATIONS:
  row=records['GGA-MAPSCRIPT-'+key];assert len(row['segments'])==len(b.TRANSLATIONS[key])
 assert any(op==0xF6E388 for op,setup in e.find_setup_prints(jp))
 assert records['GGA-MAPSCRIPT-00F6E426']['source_text_seed']=='……ん？\\nなんだ、あれは！？'
 assert candidate[0xF00000:0xFC0000]==parent[0xF00000:0xFC0000]
 print('PASS: 53 animated frames; original timeline/palette/atlas; 14 dialogue boxes; all previous lookup entries; original bytecode.')
if __name__=='__main__':main()
