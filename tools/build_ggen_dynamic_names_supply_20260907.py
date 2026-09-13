"""Repair 12x12 dynamic weapon names and the supply-screen damaged label."""
import sys,json,struct,shutil,hashlib,copy
from collections import Counter
from pathlib import Path
from PIL import Image,ImageDraw
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'analysis'))
import audit_ggen_dynamic_names_20260907 as audit
import ggen_ss_tiles_common_20260905 as c
import ggen_advance_project_paths as p
import ggen_advance_painted_glyph_identity as glyph
import patch_ggen_advance_pending_readable_batch_20260907 as prev
import build_ggen_advance_unified_rom_poc as unified
import build_ggen_advance_map_script_sheet as sheet
import _tmp_classify_pending_readable_20260907 as dec
from ggen_advance_text_codec import *
OUT=audit.OUT
START,END=0x1FF0000,0x1FF8000
def sha(b):return hashlib.sha256(b).hexdigest()
def save(path,obj):path.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def main():
 jp=p.ORIGINAL_ROM.read_bytes();parent=p.MAIN_TIP_ROM.read_bytes();before_sheet=p.TRANSLATION_MERGED_JSON.read_bytes();merged=json.loads(before_sheet);by={r['record_id']:r for r in merged['records']};owners={o['owner_id']:o for o in merged['owners']}
 assert sha(parent)==json.loads(p.MAIN_TIP_MANIFEST.read_text(encoding='utf-8'))['sha256'];assert not any(parent[START:END])
 dynamic=[r for r in merged['records'] if r['source_scope']=='scenario_dynamic'];assert len(dynamic)==165 and all(r['scope_status']=='alias' for r in dynamic)
 jobs=[]
 for row in dynamic:
  canonical=by[row['alias_of']];assert canonical['translation_status']=='translated'
  text=audit.OVERRIDES.get(row['record_id'],('',canonical['translation_ko']))[1];assert len(text)<=12
  jobs.append({'row':row,'canonical':canonical,'text':text,'mode':12})
 status=by['GGA-UI-001BE7AA'];assert status['translation_ko']=='파손 중'
 jobs.append({'row':status,'text':'파손중','mode':8})
 candidate=bytearray(parent);allowed=set();fonts={8:glyph.load_galmuri8(),12:glyph.load_galmuri12()};bases={8:glyph.FONT8_RELOCATED,12:glyph.FONT12_RELOCATED};nativebases={8:glyph.fontops.FONT_8X16_BASE,12:glyph.fontops.FONT_12X12_BASE};strides={8:32,12:18};counts={8:glyph.fontops.FONT_8X16_COUNT,12:glyph.fontops.FONT_12X12_COUNT}
 dictionaries={8:load_dictionary(jp,DICT_8X16_BASE,DICT_8X16_END),12:load_dictionary(jp,DICT_12X12_BASE,DICT_12X12_END)}
 maps={8:dec.load_identified_slot_to_char(dec.CHARMAP_8X16_PATH),12:dec.load_identified_slot_to_char(dec.CHARMAP_12X12_PATH)};maps[12].update(dec.CORRECTED_LOW_KANA)
 live8,live12=unified.collect_live_slots(jp,merged['records']);live={8:live8,12:live12};occupied={8:set(),12:set()};slots={8:{},12:{}};wanted={8:{},12:{}};painted=[]
 def write(off,data):candidate[off:off+len(data)]=data;allowed.update(range(off,off+len(data)))
 for mode in (8,12):
  rev={}
  for s,ch in maps[mode].items():rev.setdefault(ch,s)
  chars=set(''.join(j['text'] for j in jobs if j['mode']==mode))-{' '}
  for ch in sorted(chars):
   if '가'<=ch<='힣':
    packed=(glyph.packed_8x16 if mode==8 else glyph.packed_12x12)(ch,fonts[mode])
    slot=prev.try_recover(glyph.recover_unique_8x16_slots if mode==8 else glyph.recover_unique_12x12_slots,candidate,fonts[mode],ch)
   else:
    possibilities=unified.candidate_char_spellings(ch);source=next((rev[x] for x in possibilities if x in rev),None);assert source is not None,ch
    packed=jp[nativebases[mode]+source*strides[mode]:nativebases[mode]+(source+1)*strides[mode]]
    hits=[s for s in range(counts[mode]) if glyph.slot_raw(candidate,bases[mode],s,strides[mode])==packed];slot=hits[0] if hits else None
   if slot is None:
    slot=(prev.choose_free_8x16 if mode==8 else prev.choose_free_12x12)(candidate,jp,live[mode],occupied[mode]);write(bases[mode]+slot*strides[mode],packed);painted.append({'mode':mode,'char':ch,'slot':hex(slot)})
   slots[mode][ch]=slot;wanted[mode][ch]=packed;occupied[mode].add(slot)
 def rendered_correct(rom,address,text,mode):
  sl=expand_to_slots(read_tokens(rom,address-0x8000000)[0],dictionaries[mode])
  if len(sl)!=len(text):return False
  for s,ch in zip(sl,text):
   cell=glyph.slot_raw(rom,bases[mode],s,strides[mode])
   if ch==' ':
    if any(cell):return False
   elif cell!=wanted[mode][ch]:return False
  return True
 cursor=START;cache={};reports=[];prev.BATCH_ID='dynamic-12x12-and-supply-damaged-20260907'
 for job in jobs:
  row,text,mode=job['row'],job['text'],job['mode'];raw=bytes.fromhex(row['raw_hex']);off=int(row['target_file_offset'],16);assert jp[off:off+len(raw)]==raw
  changes=[];oldptrs=[];newptrs=[]
  for oid in row['owner_ids']:
   owner=int(oid[-8:],16);assert c.u32(jp,owner)==0x8000000+off
   addr=c.u32(parent,owner);oldptrs.append(hex(addr))
   if not rendered_correct(parent,addr,text,mode):
    key=(mode,text)
    if key not in cache:
     payload=prev.encode_text(text,slots[mode],{});cache[key]=cursor;write(cursor,payload);cursor+=len(payload)
    addr=cache[key]+0x8000000;write(owner,struct.pack('<I',addr));changes.append(hex(owner))
   assert rendered_correct(candidate,addr,text,mode);newptrs.append(hex(addr))
  if mode==12:
   old_alias=row['alias_of'];source_text=maps[12]
   original_slots=expand_to_slots(read_tokens(jp,off)[0],dictionaries[12]);jptext=''.join(maps[12].get(s,f'<{s:04X}>') for s in original_slots)
   if row['record_id'] in audit.OVERRIDES:jptext=audit.OVERRIDES[row['record_id']][0]
   unresolved=[f'0x{s:04X}' for s in original_slots if s not in maps[12]] if '<' in jptext else []
   row.update(previous_alias_of=old_alias,alias_of='',scope_status='included',record_kind='dynamic_fragment_text',semantic_category='dynamic_weapon_name_12x12',translation_policy='translate',container_id=row['record_id'],translation_unit_id=row['record_id'],consumer_font_mode='12x12')
   for oid in row['owner_ids']:owners[oid]['target_container_ids']=[row['record_id']]
   note='Separate 12x12 battle dialogue payload from 8x16 production weapon names; original dynamic source retained. Previous alias: '+old_alias
  else:jptext='破損中';unresolved=[];note='Supply status at x=216 has 24 pixels (3 cells); omit space to fit 파손중. Previous translated sheet was not applied.'
  prev.mark_row(row,jptext,text,note)
  row['source_unresolved_slots']=unresolved;row['source_decode_status']='partial' if unresolved else 'complete';row['qa_status']='static_consumer_and_actual_glyph_verified';prev.update_payload_hash(row)
  reports.append({'id':row['record_id'],'mode':mode,'japanese':jptext,'korean':text,'owners':row['owner_ids'],'old_pointers':oldptrs,'new_pointers':newptrs,'changed_owners':changes})
 assert cursor<END
 # Production weapon owners and previous independently corrected dynamic names
 # are preserved; only owners whose visible glyphs were wrong are retargeted.
 for job in jobs[:-1]:
  for oid in job['canonical']['owner_ids']:
   owner=int(oid[-8:],16);assert candidate[owner:owner+4]==parent[owner:owner+4]
 assert candidate[0xF00000:0xFC0000]==parent[0xF00000:0xFC0000]
 changes={i for i,(a,b) in enumerate(zip(parent,candidate)) if a!=b};assert changes<=allowed and len(candidate)==len(parent)
 # Review screenshots are explicitly derived previews: replace just the
 # measured font cells in the captured image using the candidate ROM glyphs.
 for n,key,x,y in [(1,'GGA-DYNAMIC-001F1E02',48,130),(2,'GGA-UI-001BE7AA',216,72)]:
  r=next(x for x in reports if x['id']==key);mode=r['mode'];w,height=(12,12) if mode==12 else (8,16)
  im=Image.open(OUT/f'ss{n}_embedded.png').convert('RGB');old=im.copy();fg=(115,82,24)
  # Reconstruct only the two original weapon-name cells (preserve !), or
  # the three damaged-status cells at the right screen edge.
  rect=(x,y,x+len(r['korean'])*w,y+height);bg=Counter(im.crop(rect).getdata()).most_common(1)[0][0];im.paste(bg,rect)
  for i,ch in enumerate(r['korean']):
   raw=glyph.slot_raw(candidate,bases[mode],slots[mode][ch],strides[mode]);mask=(glyph.fontops.unpack_12x12 if mode==12 else glyph.fontops.unpack_8x16)(raw);im.paste(fg,(x+i*w,y),mask)
  im.resize((960,640),Image.Resampling.NEAREST).save(OUT/f'ss{n}_after_preview.png')
 # Every correction displayed with the actual candidate 12x12 cells.
 changed=[r for r in reports if r['mode']==12 and r['changed_owners']];proof=Image.new('RGB',(240,len(changed)*20),(255,255,140))
 for rownum,r in enumerate(changed):
  for i,ch in enumerate(r['korean']):
   if ch==' ':continue
   mask=glyph.fontops.unpack_12x12(wanted[12][ch]);proof.paste((115,82,24),(i*12,rownum*20),mask)
 proof.resize((720,proof.height*3),Image.Resampling.NEAREST).save(OUT/'dynamic_corrected_names.png')
 output=OUT/'ggen_dynamic_names_supply_ko_20260907.gba';output.write_bytes(candidate)
 assert p.MAIN_TIP_ROM.read_bytes()==parent and p.TRANSLATION_MERGED_JSON.read_bytes()==before_sheet,'concurrent change'
 (OUT/'translation_before.json').write_bytes(before_sheet);shutil.copy2(p.TRANSLATION_MANIFEST,OUT/'translation_manifest_before.json')
 ident=merged['identity'];previous=ident.get('translation_overlay_identity_sha256','');ident['parent_translation_overlay_identity_sha256']=previous;ident['translation_overlay_identity_sha256']=prev.digest({'parent':previous,'batch':prev.BATCH_ID,'records':reports});ident['dynamic_consumer_identity_sha256']=prev.digest([(r['record_id'],r['container_id'],r['translation_unit_id'],r['owner_digest']) for r in dynamic])
 sheet.recount(merged);merged['summary']['translation_overlay_identity_sha256']=ident['translation_overlay_identity_sha256']
 snapshot=OUT/'translation_after.json';save(snapshot,merged);p.TRANSLATION_MERGED_JSON.write_bytes(snapshot.read_bytes());prev.update_translation_manifest(merged,snapshot)
 report={'parent':{'sha256':sha(parent)},'output':{'path':p.advance_relative(output),'sha256':sha(candidate),'size':len(candidate)},'records':reports,'painted_glyphs':painted,'verification':{'result':'PASS','dynamic_names_audited':165,'dynamic_names_corrected':len(changed),'dynamic_owner_pointers_audited':sum(len(r['owners']) for r in reports if r['mode']==12),'dynamic_owner_pointers_changed':sum(len(r['changed_owners']) for r in reports if r['mode']==12),'supply_status_corrected':'破損中 → 파손중','production_8x16_names_preserved':True,'existing_correct_dynamic_owners_preserved':True,'all_dynamic_owners_actual_glyphs_verified':True,'only_audited_bytes_changed':len(changes),'runtime':'Static payload/glyph verification; screenshot previews reconstructed from candidate font cells. Emulator re-entry not run.'}}
 save(OUT/'manifest.json',report);print(json.dumps({k:report[k] for k in ['output','painted_glyphs','verification']},ensure_ascii=False,indent=2))
if __name__=='__main__':sys.stdout.reconfigure(encoding='utf-8');main()
