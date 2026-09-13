"""Compare dynamic weapon-name consumers with the actual 12x12 painted font."""
import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'analysis'))
import ggen_ss_tiles_common_20260905 as c
import ggen_advance_project_paths as p
import ggen_advance_painted_glyph_identity as g
import patch_ggen_advance_pending_readable_batch_20260907 as prev
from ggen_advance_text_codec import *
OUT=c.ROOT/'outputs/20260907_ss1_ss2_text_next'
OVERRIDES={'GGA-DYNAMIC-001F1A86':('ヒート剣','히트 검'),
 'GGA-DYNAMIC-001F1B54':('吶喊','돌격'),
 'GGA-DYNAMIC-001F1E1B':('単装砲','단장포'),
 'GGA-DYNAMIC-001F1DD3':('迎撃ウェポン・ユニット','요격 웨폰 유닛')}
def main():
 rom=p.MAIN_TIP_ROM.read_bytes();jp=p.ORIGINAL_ROM.read_bytes();rows=json.loads(p.TRANSLATION_MERGED_JSON.read_text(encoding='utf-8'))['records'];by={r['record_id']:r for r in rows}
 dic=load_dictionary(jp,DICT_12X12_BASE,DICT_12X12_END);font=g.load_galmuri12();result=[]
 for row in rows:
  if row['source_scope']!='scenario_dynamic':continue
  source=by[row['alias_of']];text=OVERRIDES.get(row['record_id'],('',source['translation_ko']))[1];owners=[]
  for oid in row['owner_ids']:
   off=int(oid[-8:],16);addr=c.u32(rom,off);raw=read_tokens(rom,addr-0x8000000)[1];slots=expand_to_slots(read_tokens(raw,0)[0],dic)
   mismatch=[]
   for n,ch in enumerate(text):
    if not '가'<=ch<='힣':continue
    if n>=len(slots) or g.slot_raw(rom,g.FONT12_RELOCATED,slots[n],18)!=g.packed_12x12(ch,font):mismatch.append(n)
   owners.append({'offset':hex(off),'address':hex(addr),'raw':raw.hex(),'slots':[hex(s) for s in slots],'glyph_mismatch_positions':mismatch,'length_match':len(slots)==len(text)})
  result.append({'id':row['record_id'],'canonical_id':source['record_id'],'korean':text,'owners':owners,'needs_reencode':any(x['glyph_mismatch_positions'] or not x['length_match'] for x in owners)})
 (OUT/'dynamic_consumer_audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
 print('Records',len(result),'needs correction',sum(x['needs_reencode'] for x in result),'owner count',sum(len(x['owners']) for x in result))
 print('Already correct',[x['id'] for x in result if not x['needs_reencode']])
if __name__=='__main__':main()
