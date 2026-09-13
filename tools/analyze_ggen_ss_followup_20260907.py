import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'analysis'))
import _tmp_classify_pending_readable_20260907 as dec
import patch_ggen_special_title_20260907 as base
from ggen_advance_text_codec import *
from ggen_ss_tiles_common_20260905 import *
import build_ggen_advance_ss4_stat_badges_ko_20260905 as badges
import build_ggen_advance_status_ui_tile_overlay_poc as status

OUT=ROOT/'outputs/20260907_ss1_ss4_followup'
def main():
 r=base.ORIGINAL_ROM.read_bytes();cur=base.MAIN_TIP_ROM.read_bytes()
 d=load_dictionary(r,DICT_8X16_BASE,DICT_8X16_END)
 cm=dec.load_identified_slot_to_char(dec.CHARMAP_8X16_PATH)
 rows=json.loads(base.TRANSLATION_MERGED_JSON.read_text(encoding='utf-8'))['records']; found=[]
 for row in rows:
  if row.get('source_scope','').startswith('scenario'):continue
  try:
   raw=bytes.fromhex(row['raw_hex']);slots=expand_to_slots(read_tokens(raw,0)[0],d);s=''.join(cm.get(x,f'<{x:04X}>') for x in slots)
  except Exception:continue
  cat=row.get('semantic_category','')
  if any(x in s for x in ('700','軽減','砂漠','森林','この','コマンド','使用しない')) or ('terrain' in cat) or ('defense' in cat) or (0x18cf30<=int(row['target_file_offset'],16)<0x18cfc0):
   found.append({'id':row['record_id'],'jp':s,'ko':row.get('translation_ko'),'status':row.get('translation_status'),'category':cat,'owners':row.get('owner_ids'),'raw':row['raw_hex']})
 (OUT/'text_inventory.json').write_text(json.dumps(found,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(found,ensure_ascii=False,indent=2))
 st,_=statefmt.parse_png_state(ROOT/'SD Gundam GGeneration Advance (Korean).ss4')
 colors=raster.palette_rgb(st[0x9A0:0x9C0]);o=u32(cur,badges.TABLE)-0x8000000
 a=status.lzss_decompress(cur[o+4:o+4+(u32(cur,o)&65535)])
 items=[];maps=[]
 for n in range(1,69):
  m=sem.parse_map(cur,u32(cur,badges.TABLE+n*4))
  if m:
   items.append((str(n),raster.render_canvas(sem.stitch(a,m),colors)))
   maps.append({'index':n,**m})
 gallery(items,OUT/'status_family.png',4)
 gallery([p for p in items if int(p[0])>=59],OUT/'status_tail.png',6)
 (OUT/'status_maps.json').write_text(json.dumps(maps),encoding='utf-8')
 from PIL import Image,ImageDraw
 terrain=[x for x in rows if 0x18cf19<=int(x.get('target_file_offset','0'),16)<0x18d004]
 extra=[x for x in rows if x['record_id'] in ('GGA-TEXT-001C88A3','GGA-TEXT-001C8851','GGA-TEXT-0017C18E')]
 selected=terrain+extra
 im=Image.new('L',(240,len(selected)*24));dr=ImageDraw.Draw(im)
 for i,row in enumerate(selected):
  dr.text((0,i*24),row['record_id'][-6:],fill=150)
  sl=expand_to_slots(read_tokens(bytes.fromhex(row['raw_hex']),0)[0],d)
  for j,s in enumerate(sl):
   off=base.fontops.FONT_8X16_BASE+s*32
   im.paste(base.fontops.unpack_8x16(r[off:off+32]),(48+j*8,i*24))
 im.resize((720,im.height*3),Image.Resampling.NEAREST).save(OUT/'original_words.png')
 selected=[x for x in rows if x.get('semantic_category')=='id_command_name' and x.get('translation_status')=='pending']
 im=Image.new('L',(290,len(selected)*24));dr=ImageDraw.Draw(im)
 for i,row in enumerate(selected):
  dr.text((0,i*24),row['record_id'][-6:],fill=150)
  for j,s in enumerate(expand_to_slots(read_tokens(bytes.fromhex(row['raw_hex']),0)[0],d)):
   off=base.fontops.FONT_8X16_BASE+s*32
   im.paste(base.fontops.unpack_8x16(r[off:off+32]),(48+j*8,i*24))
 im.resize((1160,im.height*4),Image.Resampling.NEAREST).save(OUT/'pending_id_names.png')
if __name__=='__main__':
 sys.stdout.reconfigure(encoding='utf-8');main()
