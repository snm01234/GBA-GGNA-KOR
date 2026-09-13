"""Translate the boot copyright graphic identified from the user's ss1.

The boot routine at 0802835C loads resource 08CCF59C through 08001C50.
Resource flag 0x10 selects custom LZSS; the relocated resource uses the
same loader's raw DMA path, keeping its dimensions and palette unchanged.
"""
from ggen_ss_tiles_common_20260905 import *
from ggen_advance_project_paths import FONT_ZIP, MAIN_TIP_ROM, MAIN_TIP_MANIFEST
from zipfile import ZipFile
import test_ggen_advance_font_pair as fp
import hashlib, json

DEST = ROOT/'outputs/20260906_ggen_copyright'
SOURCE = 0xCCF59C
OWNER = 0x283BC
TARGET = 0x1FB0000
TEXTS = ['소츠 에이전시 · 선라이즈', '소츠 에이전시 · 선라이즈 · 마이니치 방송']

def sha(data):
 return hashlib.sha256(data).hexdigest()

def preview(canvas, colors, path):
 im=Image.new('RGB',(240,160));pixels=im.load()
 for y,row in enumerate(canvas):
  for x,v in enumerate(row):pixels[x,y]=colors[v]
 im.resize((960,640),Image.Resampling.NEAREST).save(path)

def main():
 DEST.mkdir(exist_ok=True)
 parent=MAIN_TIP_ROM.read_bytes()
 assert sha(parent)==json.loads(MAIN_TIP_MANIFEST.read_text(encoding='utf-8'))['sha256']
 state_path=ROOT/'SD Gundam GGeneration Advance (Korean).ss1'
 state,_=statefmt.parse_png_state(state_path)
 assert parent[SOURCE:SOURCE+16].hex()=='12001e141000b004c004c20384082000'
 assert u32(parent,OWNER)==0x08000000+SOURCE
 assert raster.pointer_hits(parent,SOURCE+0x08000000)==[OWNER]
 graphics=sem.lzss_decompress(parent[SOURCE+0x4C0:SOURCE+0x882])
 assert len(graphics)==117*32
 assert state[0x1000:0x1000+len(graphics)]==graphics
 cells=list(struct.unpack_from('<600H',parent,SOURCE+16))
 for y in range(20):
  assert list(struct.unpack_from('<30H',state,0x7000+y*64))==cells[y*30:(y+1)*30]
 before=sem.stitch(graphics,{'width':30,'height':20,'cells':cells})
 colors=raster.palette_rgb(parent[SOURCE+0x884:SOURCE+0x8A4])
 assert parent[SOURCE+0x884:SOURCE+0x8A4]==state[0x800:0x820]
 after=[row[:] for row in before]
 # Original copyright symbol, including its antialiasing, is reused.
 symbol=[row[44:55] for row in before[35:46]]
 layout=[]
 with ZipFile(FONT_ZIP) as z:font=fp.load_bdf(z,'Galmuri11.bdf')
 for text,y in zip(TEXTS,[35,75]):
  for yy in range(y-3,y+14):after[yy]=[1]*240
  ink=set();cursor=0
  for ch in text:
   if ch==' ':cursor+=4;continue
   if ch=='·':
    ink.add((cursor,5));cursor+=3;continue
   pts,w,h=raster.native_ink(font,ch)
   ink|={(cursor+x,yy) for x,yy in pts};cursor+=w+1
  width=cursor-1;total=11+6+width;x=(240-total)//2
  assert x>=0 and total<=240
  for yy,row in enumerate(symbol):after[y+yy][x:x+11]=row
  for xx,yy in ink:after[y+yy][x+17+xx]=2
  layout.append({'text':text,'x':x,'y':y,'width':total})
 assert after[100:]==before[100:]
 tiles=[];lookup={};newcells=[]
 for ty in range(20):
  for tx in range(30):
   tile=raster.encode_tile([row[tx*8:tx*8+8] for row in after[ty*8:ty*8+8]])
   if tile not in lookup:lookup[tile]=len(tiles);tiles.append(tile)
   newcells.append(lookup[tile])
 raw=b''.join(tiles);assert len(raw)<0x6000
 blob=bytearray(parent[SOURCE:SOURCE+16]);struct.pack_into('<H',blob,0,2)
 struct.pack_into('<H',blob,10,len(raw));struct.pack_into('<H',blob,12,0x4C0+len(raw))
 blob.extend(struct.pack('<600H',*newcells));blob.extend(raw);blob.extend(parent[SOURCE+0x884:SOURCE+0x8A4])
 assert len(blob)==0x4C0+len(raw)+32
 assert all(v==0 for v in parent[TARGET:TARGET+len(blob)])
 candidate=bytearray(parent);candidate[TARGET:TARGET+len(blob)]=blob
 struct.pack_into('<I',candidate,OWNER,TARGET+0x08000000)
 assert candidate[:OWNER]==parent[:OWNER]
 assert candidate[OWNER+4:TARGET]==parent[OWNER+4:TARGET]
 assert candidate[TARGET+len(blob):]==parent[TARGET+len(blob):]
 decoded=canvas_direct(candidate,direct(candidate,TARGET));assert decoded==after
 result=DEST/'ggen_copyright_ko_20260906.gba';result.write_bytes(candidate)
 derived=bytearray(state);derived[0x1000:0x1000+len(raw)]=raw
 for y in range(20):struct.pack_into('<30H',derived,0x7000+y*64,*newcells[y*30:(y+1)*30])
 result.with_suffix('.ss1').write_bytes(raster.replace_state_chunk(state_path,derived))
 preview(before,colors,DEST/'before.png');preview(decoded,colors,DEST/'after.png')
 manifest={'parent_sha256':sha(parent),'reference_state_sha256':sha(state_path.read_bytes()),
  'output':{'path':str(result.relative_to(ROOT)),'size':len(candidate),'sha256':sha(candidate)},
  'source_resource':hex(SOURCE),'new_resource':hex(TARGET),'pointer_offset':hex(OWNER),
  'layout':layout,'font':'Galmuri11.bdf','unique_tiles':len(tiles),
  'verification':{'result':'PASS','original_rom_graphic_matches_user_state':True,
   'new_resource_roundtrip':True,'only_private_resource_and_boot_pointer_changed':True,
   'bandai_2003_unchanged':True,'original_state_unchanged':True,
   'emulator_runtime':'Not verified: local mGBA GDB connection timed out. Preview reconstructed from ROM resource.',
   'test_state':'Separate derived ss1 provided; original ss1 retains its old VRAM.'}}
 (DEST/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(manifest,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
