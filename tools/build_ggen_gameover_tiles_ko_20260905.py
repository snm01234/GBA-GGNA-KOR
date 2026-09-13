from ggen_ss_tiles_common_20260905 import *
from ggen_advance_project_paths import FONT_ZIP
import test_ggen_advance_font_pair as fp
from zipfile import ZipFile
import hashlib,json

DEST=ROOT/'outputs/20260905_ggen_gameover_tiles'
def sha(b):return hashlib.sha256(b).hexdigest()
def main():
 parent=(ROOT/'SD Gundam GGeneration Advance (Korean).gba').read_bytes()
 st,_=statefmt.parse_png_state(ROOT/'SD Gundam GGeneration Advance (Korean)_allclear.ss1')
 source=0x177adc;g=u32(parent,source+8);pal=u32(parent,source+12)
 old=parent[source+g:source+pal];assert len(old)==68*32
 spans=[(0,64,256),(64,64,288),(128,64,320),(192,32,352),(224,16,368)]
 before=[[0]*240 for _ in range(32)]
 live=[]
 for x,w,t in spans:
  for ty in range(4):
   for tx in range(w//8):
    raw=st[0x11000+(t+ty*w//8+tx)*32:0x11000+(t+ty*w//8+tx+1)*32]
    assert any(old[i:i+32]==raw for i in range(0,len(old),32))
    live.append(raw)
    for yy,row in enumerate(raster.decode_tile(raw)):before[ty*8+yy][x+tx*8:x+tx*8+8]=row
 clean=[[row[0]]*240 for row in before];new=[r[:] for r in clean]
 assert all(row[0]==row[-1] for row in before)
 with ZipFile(FONT_ZIP) as z:font=fp.load_bdf(z,'Galmuri11.bdf')
 pts=set();cursor=0
 for ch in '게임오버':
  ink,w,h=raster.native_ink(font,ch)
  pts|={(cursor+x*3+dx,y*2+dy) for x,y in ink for dx in range(3) for dy in range(2)}
  cursor+=w*3+5
 width=cursor-5;pts={(x+(240-width)//2,y+4) for x,y in pts}
 body=pts|{(x+2,y+2) for x,y in pts}|{(x+1,y+1) for x,y in pts}
 for x,y in raster.dilate(body,240,32):new[y][x]=15
 for x,y in body:new[y][x]=1
 for x,y in pts:new[y][x]=7 if y<10 else 8 if y<14 else 6 if y<20 else 4
 # Upper/left bevel uses the original muted highlight, with a dark extrusion.
 for x,y in pts:
  if (x,y-1) not in pts:new[y][x]=9
  elif (x-1,y) not in pts:new[y][x]=5
 payload=[]
 for x,w,t in spans:
  for ty in range(4):
   for tx in range(w//8):payload.append(raster.encode_tile([row[x+tx*8:x+tx*8+8] for row in new[ty*8:ty*8+8]]))
 blob=bytearray(parent[source:source+g]);rec=0x18
 assert u16(blob,rec+4)==21
 for i in range(21):
  q=rec+0x18+i*4;f=q+u32(blob,q)
  assert u16(blob,f+6)==5 and u16(blob,f+10)==120
  lookup=f+u16(blob,f+12)
  ids=[u16(blob,lookup+j*2) for j in range(120)]
  assert [old[k*32:(k+1)*32] for k in ids]==live
  for j in range(120):struct.pack_into('<H',blob,lookup+j*2,j)
 blob.extend(b''.join(payload));struct.pack_into('<I',blob,12,len(blob));blob.extend(parent[source+pal:source+pal+32])
 target=0x1f98000;assert all(v==0 for v in parent[target:target+len(blob)])
 out=bytearray(parent);out[target:target+len(blob)]=blob
 hits=raster.pointer_hits(parent,source+0x8000000);assert hits==[107484]
 for p in hits:struct.pack_into('<I',out,p,target+0x8000000)
 result=DEST/'ggen_gameover_tiles_ko_20260905.gba';result.write_bytes(out)
 derived=bytearray(st);derived[0x13000:0x13f00]=b''.join(payload)
 (result.with_suffix('.ss1')).write_bytes(raster.replace_state_chunk(ROOT/'SD Gundam GGeneration Advance (Korean)_allclear.ss1',derived))
 colors=raster.palette_rgb(st[0xaa0:0xac0])
 gallery([(name,raster.render_canvas(c,colors)) for name,c in [('Original',before),('Restored gradient',clean),('Korean',new)]],DEST/'comparison.png',3)
 raster.render_canvas(new,colors).resize((960,128),Image.Resampling.NEAREST).save(DEST/'korean_banner.png')
 assert out[source:source+pal+32]==parent[source:source+pal+32]
 manifest={'parent_sha256':sha(parent),'output':{'path':str(result.relative_to(ROOT)),'size':len(out),'sha256':sha(out)},'verification':{'result':'PASS','animation_frames':21,'tiles':120,'original_preserved':True,'runtime':'pending user test'},'source_resource':hex(source),'relocated_resource':hex(target),'text':'게임오버'}
 (DEST/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(manifest,ensure_ascii=False))
if __name__=='__main__':main()
