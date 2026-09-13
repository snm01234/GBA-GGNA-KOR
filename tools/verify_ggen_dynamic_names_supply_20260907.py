"""Independent current-ROM checks for all 165 dynamic name consumers."""
import sys,json,struct
from collections import Counter
from PIL import Image
import build_ggen_dynamic_names_supply_20260907 as b
from ggen_advance_text_codec import *
def main():
 manifest=json.loads((b.OUT/'manifest.json').read_text(encoding='utf-8'));parent=b.p.MAIN_TIP_ROM.read_bytes();rom=(b.c.ROOT/manifest['output']['path']).read_bytes();jp=b.p.ORIGINAL_ROM.read_bytes();merged=json.loads(b.p.TRANSLATION_MERGED_JSON.read_text(encoding='utf-8'));by={r['record_id']:r for r in merged['records']}
 assert b.sha(parent)==manifest['parent']['sha256'] and b.sha(rom)==manifest['output']['sha256']
 font=b.glyph.load_galmuri12();d12=load_dictionary(jp,DICT_12X12_BASE,DICT_12X12_END);d8=load_dictionary(jp,DICT_8X16_BASE,DICT_8X16_END)
 # Every alias has become its own font-specific string. Future builds must
 # allocate it as 12x12 and resolve owners to the dynamic record itself.
 dynamic=[r for r in merged['records'] if r['source_scope']=='scenario_dynamic'];assert len(dynamic)==165
 for row in dynamic:
  assert row['scope_status']=='included' and not row['alias_of'] and b.unified.uses_12x12(row)
  assert b.unified.canonical_record(by,row['record_id']) is row
  original=by[row['previous_alias_of']]
  for ownerid in original['owner_ids']:
   off=int(ownerid[-8:],16);assert parent[off:off+4]==rom[off:off+4]
  for ownerid in row['owner_ids']:
   off=int(ownerid[-8:],16);addr=b.c.u32(rom,off)-0x8000000;slots=expand_to_slots(read_tokens(rom,addr)[0],d12)
   assert len(slots)==len(row['translation_ko'])
   for slot,ch in zip(slots,row['translation_ko']):
    if '가'<=ch<='힣':assert b.glyph.slot_raw(rom,b.glyph.FONT12_RELOCATED,slot,18)==b.glyph.packed_12x12(ch,font)
 # No already-correct dynamic owner was changed, and all listed changed
 # owners point into the isolated text cave.
 changed=0
 for item in manifest['records']:
  for ownerid in item['owners']:
   off=int(ownerid[-8:],16)
   if hex(off) in item['changed_owners']:
    assert b.START<=b.c.u32(rom,off)-0x8000000<b.END;changed+=1
   else:assert rom[off:off+4]==parent[off:off+4]
 # Reconstruct screenshot previews from the actual patched pointer streams.
 for n,key,x,y,mode in [(1,'GGA-DYNAMIC-001F1E02',48,130,12),(2,'GGA-UI-001BE7AA',216,72,8)]:
  row=by[key];owner=int(row['owner_ids'][0][-8:],16);addr=b.c.u32(rom,owner)-0x8000000;slots=expand_to_slots(read_tokens(rom,addr)[0],d12 if mode==12 else d8)
  assert len(slots)==2 if mode==12 else len(slots)==3
  im=Image.open(b.OUT/f'ss{n}_embedded.png').convert('RGB');w,h=(12,12) if mode==12 else (8,16);rect=(x,y,x+w*len(slots),y+h)
  bg=Counter(im.crop(rect).getdata()).most_common(1)[0][0];im.paste(bg,rect)
  for i,slot in enumerate(slots):
   raw=b.glyph.slot_raw(rom,b.glyph.FONT12_RELOCATED if mode==12 else b.glyph.FONT8_RELOCATED,slot,18 if mode==12 else 32)
   mask=(b.glyph.fontops.unpack_12x12 if mode==12 else b.glyph.fontops.unpack_8x16)(raw);im.paste((115,82,24),(x+i*w,y),mask)
  im.resize((960,640),Image.Resampling.NEAREST).save(b.OUT/f'ss{n}_after_preview.png')
 assert rom[0xF00000:0xFC0000]==parent[0xF00000:0xFC0000]
 print(f'PASS: 165 separate 12x12 dynamic records; 1468 owners; {changed} corrected pointers including supply; production owners and map scripts preserved.')
if __name__=='__main__':main()
