import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'analysis'))
import _tmp_classify_pending_readable_20260907 as dec
import patch_ggen_special_title_20260907 as b
import render_ggen_ss_tiles_20260905 as render
import analyze_ggen_advance_intermission_cycle_states_20260830 as bg
from ggen_advance_text_codec import *
OUT=b.ROOT/'outputs/20260907_ss1_ss4_next'
def main():
 r=b.MAIN_TIP_ROM.read_bytes();jp=b.ORIGINAL_ROM.read_bytes();d=load_dictionary(jp,DICT_12X12_BASE,DICT_12X12_END);cm=dec.load_identified_slot_to_char(dec.CHARMAP_12X12_PATH);cm.update(dec.CORRECTED_LOW_KANA)
 rows=json.loads(b.TRANSLATION_MERGED_JSON.read_text(encoding='utf-8'))['records'];hits=[]
 for row in rows:
  if not row.get('source_scope','').startswith('scenario'):continue
  decoded=[]
  for seg in row.get('segments') or [row]:
   try:sl=expand_to_slots(read_tokens(bytes.fromhex(seg['raw_hex']),0)[0],d);decoded.append(''.join(cm.get(s,f'<{s:04X}>') for s in sl))
   except:pass
  s=' / '.join(decoded)
  if ('ライン' in s and any(c in s for c in ['防','敵','第'])) or ('あれは' in s) or ('なんだ' in s and len(s)<55):hits.append({'id':row['record_id'],'decode':s,'row':row})
 (OUT/'dialogue_candidates.json').write_text(json.dumps(hits,ensure_ascii=False,indent=2),encoding='utf-8')
 print('DIALOGUE',[(x['id'],x['decode'],x['row'].get('translation_segments'),x['row'].get('translation_status')) for x in hits])
 for n in (1,2):
  st,_=render.statefmt.parse_png_state(b.ROOT/f'SD Gundam GGeneration Advance (Korean).ss{n}')
  print('STATE',n,'BGS',[(i,bg.bg_info(st,i)) for i in range(4)])
  print('OAM',[render.statefmt.parse_oam_entry(st[0xc00:0x1000],i) for i in range(128) if not (int(render.statefmt.parse_oam_entry(st[0xc00:0x1000],i)['attr0'],16)&0x300==0x200)])
  if n==2:
   for i in range(4):
    info=bg.bg_info(st,i)
    for x,y in [(6,17),(7,17),(6,18)]:
     c=bg.map_entry(st[0x1000:0x19000],info['screen_base'],info['size'],x,y);p=0x1000+info['char_base']+(c&1023)*32;raw=st[p:p+32]
     if len(set(raw))>3:print('BG_TILE',i,x,y,hex(c),hex(jp.find(raw)),raw.hex())
if __name__=='__main__':sys.stdout.reconfigure(encoding='utf-8');main()
