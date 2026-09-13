import json,pickle,struct
from pathlib import Path
from PIL import Image
import patch_ggen_profile_followup2_20260912 as f2
import build_ggen_advance_unified_rom_poc as u
import build_ggen_advance_ko_poc as fo
import ggen_advance_text_codec as c
import analyze_ggen_advance_develop_menu_buttons_images_20260901 as cat
import build_ggen_advance_develop_menu_buttons_ko_image_20260901 as btn
from analyze_ggen_advance_ui_matrix_expansion import FIXED16_MATRIX,FIXED40_MATRIX
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs/20260913_ss1_ss9_followup'
def main():
 import sys;sys.stdout.reconfigure(encoding='utf-8');OUT.mkdir(parents=True,exist_ok=True)
 rom=(ROOT/'SD Gundam GGeneration Advance (Korean).gba').read_bytes();jp=(ROOT/'SD Gundam GGeneration Advance (Japan).gba').read_bytes()
 maps={};hang={};ds={}
 for mode,path,b,e in [(8,u.CHARMAP_8X16_PATH,c.DICT_8X16_BASE,c.DICT_8X16_END),(12,u.CHARMAP_12X12_PATH,c.DICT_12X12_BASE,c.DICT_12X12_END)]:
  hang[mode]=f2.hangul_slot_map(rom,mode=mode);maps[mode]=f2.slot_to_char_map(u.load_verified_charmap(path),{},hang[mode]);ds[mode]=c.load_dictionary(rom,b,e)
 pickle.dump((maps,hang,ds),(OUT/'maps.pkl').open('wb'))
 for kind,spec in [('char',FIXED16_MATRIX),('unit',FIXED40_MATRIX)]:
  for i in range(spec['count']):
   for s in range(spec['selector_count']):
    owner=spec['base_file']+i*spec['stride']+s*4
    if not c.ROM_BASE<=f2.u32(rom,owner)<c.ROM_BASE+len(rom):continue
    t=f2.decode_text(rom,f2.u32(rom,owner),ds[12],maps[12])
    if any(x in t for x in ['명경지술','넬 아르','발 바르']):print(kind,i,s,hex(owner),t)
 d8=c.load_dictionary(jp,c.DICT_8X16_BASE,c.DICT_8X16_END)
 im=Image.new('RGB',(800,192),'white')
 for j,off in enumerate([0x18d2fd,0x18d31f,0x1be9ec]):
  slots=c.expand_to_slots(c.read_tokens(jp,off)[0],d8)
  for i,s in enumerate(slots):
   mask=fo.unpack_8x16(jp[fo.FONT_8X16_BASE+s*32:fo.FONT_8X16_BASE+(s+1)*32]);im.paste('black',(i*32,j*64,i*32+32,j*64+64),mask.resize((32,64)))
 im.save(OUT/'stage_jp.png')
 rows=cat.enumerate_buttons(jp);allcan=[]
 for spec in cat.PACKAGES:
  addr=c.ROM_BASE+btn.CLONES[spec['name']];header=btn.analysis.parse_resource_header(rom,addr);_,records=btn.sprite.animation_records(rom,addr)
  for r in rows:
   if r['package']!=spec['name'] or r['kind']!='64' or r['face']!=12:continue
   parsed,ids,_=cat.parse_anim(records,r['anim']);canvas=btn.analysis.stitch(header['graphics'],parsed,ids,list(r['objects']))
   allcan.append((r,canvas,header['palettes']))
   if r['ko']=='캔슬' and spec['name']=='develop':
    print('cancel',r['anim']);print('\n'.join(''.join(format(v,'x') for v in line) for line in canvas))
 image=Image.new('RGB',(512,len(allcan)*64),'black')
 for i,(r,canvas,pal) in enumerate(allcan): image.paste(cat.canvas_image(canvas,pal,r['bank'],4),(0,i*64))
 image.save(OUT/'focus_before.png');pickle.dump(allcan,(OUT/'buttons.pkl').open('wb'))
if __name__=='__main__':main()
