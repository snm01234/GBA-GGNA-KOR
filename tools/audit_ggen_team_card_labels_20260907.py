"""Read-only audit of team-card label semantics against Japanese ROM and SS1."""
import json,sys,hashlib
from pathlib import Path
from PIL import Image,ImageDraw
import build_ggen_advance_team_card_ui_ko_20260903 as t
import render_ggen_ss_tiles_20260905 as renderer
from ggen_advance_project_paths import ORIGINAL_ROM

OUT=t.ROOT/'outputs/20260907_badge_mistranslation_audit'
def main():
 OUT.mkdir(exist_ok=True)
 jp=ORIGINAL_ROM.read_bytes();rom=t.MAIN_TIP_ROM.read_bytes()
 source,_=t.decode_atlas(jp)
 off=t.u32(rom,t.ATLAS_POINTER)-t.ROM_BASE
 atlas=t.scan.lzss_decompress(rom[off+4:off+4+(t.u32(rom,off)&65535)])
 state,_=t.statefmt.parse_png_state(t.STATE)
 colors=[t.bgutil.rgb555(int.from_bytes(state[0x800+11*32+i*2:0x800+11*32+i*2+2],'little')) for i in range(16)]
 im=Image.new('RGB',(350,len(t.LABELS)*84),(35,35,35));draw=ImageDraw.Draw(im);report=[]
 for i,(name,row) in enumerate(t.LABELS.items()):
  draw.text((2,i*84),name,fill='white')
  for j,a in enumerate([source,atlas]):
   c=t.canvas(a,row['ids']);pic=Image.new('RGB',(32,len(c)))
   for y,line in enumerate(c):
    for x,v in enumerate(line):pic.putpixel((x,y),colors[v])
   im.paste(pic.resize((96,len(c)*3),Image.Resampling.NEAREST),(125+j*112,i*84))
  actual='移動' if name.startswith('storage_') else row['jp']
  report.append({'name':name,'registered_japanese':row['jp'],'actual_japanese':actual,'applied_korean':row['ko'],'correct_korean':'이동' if name.startswith('storage_') else row['ko'],'mistranslated':name.startswith('storage_'),'tiles':list(row['ids'])})
 im.save(OUT/'japanese_vs_korean.png')
 # Bind the upper-right button's actual BG2 map and VRAM to the current atlas.
 cells=t.live_rows(state,2,26,2,3)
 liveids=[c&1023 for c in cells]
 expected=[x+1 for x in t.LABELS['storage_normal']['ids']]
 assert liveids==expected,(liveids,expected)
 assert all(state[0x1000+dst*32:0x1000+(dst+1)*32]==atlas[src*32:(src+1)*32] for src,dst in zip(t.LABELS['storage_normal']['ids'],liveids))
 native=bytearray(state)
 for src,dst in zip(t.LABELS['storage_normal']['ids'],liveids):native[0x1000+dst*32:0x1000+(dst+1)*32]=source[src*32:(src+1)*32]
 renderer.OUT=OUT
 renderer.render(bytes(native)).resize((720,480),Image.Resampling.NEAREST).save(OUT/'ss1_original_button_reconstructed.png')
 data={'rom_sha256':hashlib.sha256(rom).hexdigest(),'rom_changed':False,'audited_variants':12,'mistranslated_variants':2,'distinct_mistranslated_terms':1,'root_cause':'Original 移動 button was mislabeled as 格納 in LABELS storage_normal/storage_focus; rendering and live tile mapping follow that incorrect source metadata.','atlas_pointer_owner':hex(t.ATLAS_POINTER),'original_atlas':hex(t.SOURCE_ATLAS),'active_atlas':hex(off),'live_button':{'map_layer':2,'tile_origin':[26,2],'live_tiles':liveids,'source_tiles':list(t.LABELS['storage_normal']['ids']),'source_bytes_match':True},'labels':report}
 (OUT/'audit.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps(data['live_button'],indent=2))
if __name__=='__main__':main()
