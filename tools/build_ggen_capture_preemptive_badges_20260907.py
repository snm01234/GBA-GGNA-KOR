"""User-confirmed stat badges: resource20 포획, resource22 선제.

Reuse six private body slots per badge and the approved hit arrow caps.
Never grow the atlas into the portrait's VRAM allocation.
"""
from ggen_ss_tiles_common_20260905 import *
import build_ggen_advance_ss4_stat_badges_ko_20260905 as b
import build_ggen_advance_status_ui_tile_overlay_poc as status
from ggen_advance_project_paths import MAIN_TIP_ROM,MAIN_TIP_MANIFEST,ORIGINAL_ROM,FONT_ZIP
from zipfile import ZipFile
import hashlib,json
DEST=ROOT/'outputs/20260907_ggen_capture_preemptive_badges'
def sha(x):return hashlib.sha256(x).hexdigest()
def main():
 DEST.mkdir(exist_ok=True)
 parent=MAIN_TIP_ROM.read_bytes();jp=ORIGINAL_ROM.read_bytes()
 assert sha(parent)==json.loads(MAIN_TIP_MANIFEST.read_text(encoding='utf8'))['sha256']
 off=u32(parent,b.TABLE)-0x8000000;length=u32(parent,off)&65535
 atlas=status.lzss_decompress(parent[off+4:off+4+length]);assert len(atlas)==519*32
 assert status.literal_only_compress(atlas)==parent[off:off+4+length]
 jo=u32(jp,b.TABLE)-0x8000000;ja=status.lzss_decompress(jp[jo+4:jo+4+(u32(jp,jo)&65535)])
 clean,_=b.build_common_background(b.stitch(ja,b.parse_map(jp,24)))
 with ZipFile(FONT_ZIP) as z:font=b.fontpair.load_bdf(z,'Galmuri11.bdf')
 check=[r[:] for r in clean];b.paint(check,'명중',font,(1,2))
 assert check==b.stitch(atlas,b.parse_map(parent,24))
 newatlas=bytearray(atlas);candidate=bytearray(parent);reports=[];allowed=[];bodyids=set();previews=[]
 hit=b.parse_map(parent,24)
 for index,text,target in [(20,'포획',0x1FD4020),(22,'선제',0x1FD4040)]:
  m=b.parse_map(parent,index);before=b.stitch(atlas,m);after=[r[:] for r in clean]
  painting=b.paint(after,text,font,(1,2))
  own={c&1023 for i,c in enumerate(m['cells']) if i not in (3,7)}
  for n in range(1,69):
   other=sem.parse_map(parent,u32(parent,b.TABLE+n*4))
   if n!=index and other:assert not own&{c&1023 for c in other['cells']}
  cells=[]
  for n,c in enumerate(m['cells']):
   tid=(hit['cells'][n] if n in (3,7) else c)&1023
   payload=raster.encode_tile([row[n%4*8:n%4*8+8] for row in after[n//4*8:n//4*8+8]])
   if n in (3,7):assert atlas[tid*32:tid*32+32]==payload
   else:newatlas[tid*32:tid*32+32]=payload
   cells.append((c&0xf000)|tid)
  assert max(c&1023 for c in cells)+1<0x200
  newmap=bytearray(parent[m['offset']:m['offset']+20]);struct.pack_into('<8H',newmap,4,*cells)
  assert not any(parent[target:target+20])
  candidate[target:target+20]=newmap;struct.pack_into('<I',candidate,b.TABLE+index*4,target+0x8000000)
  allowed.extend([(target,target+20),(b.TABLE+index*4,b.TABLE+index*4+4)])
  bodyids|=own
  reports.append({'resource':index,'korean':text,'translation_authority':'explicit user instruction','map':hex(target),'tiles':[hex(c&1023) for c in cells],'paint':painting})
  previews.append((before,after))
 blob=status.literal_only_compress(newatlas);assert len(blob)==length+4
 candidate[off:off+len(blob)]=blob;allowed.append((off,off+len(blob)))
 assert all(a==z or i//32 in bodyids for i,(a,z) in enumerate(zip(atlas,newatlas)))
 for n in range(20,29):
  if n not in (20,22):assert b.stitch(atlas,b.parse_map(parent,n))==b.stitch(newatlas,b.parse_map(candidate,n))
 for (index,_,_),(_,after) in zip([(20,'',0),(22,'',0)],previews):assert b.stitch(newatlas,b.parse_map(candidate,index))==after
 cursor=0
 for start,end in sorted(allowed):
  assert candidate[cursor:start]==parent[cursor:start];cursor=end
 assert candidate[cursor:]==parent[cursor:]
 result=DEST/'ggen_capture_preemptive_badges_ko_20260907.gba';result.write_bytes(candidate)
 st,_=statefmt.parse_png_state(ROOT/'SD Gundam GGeneration Advance (Korean).ss1');colors=raster.palette_rgb(st[0x9A0:0x9C0])
 im=Image.new('RGB',(64,32));px=im.load()
 for row,(before,after) in enumerate(previews):
  for col,canvas in enumerate((before,after)):
   for y,line in enumerate(canvas):
    for x,v in enumerate(line):px[col*32+x,row*16+y]=colors[v]
 im.resize((512,256),Image.Resampling.NEAREST).save(DEST/'before_after.png')
 report={'parent_sha256':sha(parent),'output':{'path':str(result.relative_to(ROOT)),'size':len(candidate),'sha256':sha(candidate)},'translations':reports,
  'verification':{'result':'PASS','same_approved_background_font_and_gradient':True,'original_atlas_size_519_tiles_preserved':True,'all_used_tiles_below_portrait_region':True,'body_slots_not_shared':True,'shared_arrow_caps_unchanged':True,'other_badges_pixel_exact':True,'only_two_badges_and_their_map_pointers_changed':True,'runtime':'ROM resource roundtrip and preview verified; live display of these two badges not yet captured'}}
 (DEST/'manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
