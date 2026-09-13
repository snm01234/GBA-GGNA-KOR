"""Bind refreshed SS2/SS5 to ROM owners and build a reviewable fix."""
from ggen_ss_tiles_common_20260905 import *
import analyze_ggen_advance_intermission_cycle_states_20260830 as bg
import build_ggen_ss1_ss4_tiles_ko_20260905 as paintutil
import build_ggen_advance_status_ui_tile_overlay_poc as compression
import render_ggen_ss_tiles_20260905 as renderer
from ggen_advance_project_paths import MAIN_TIP_ROM, MAIN_TIP_MANIFEST, ORIGINAL_ROM, FONT_ZIP
from zipfile import ZipFile
from collections import Counter
import hashlib, json

DEST=ROOT/'outputs/20260909_ss2_ss5_diagnosis'
def sha(b):return hashlib.sha256(b).hexdigest()

def render_affine_banner(st):
 frame=renderer.render(st)
 for i in range(127,-1,-1):
  e=statefmt.parse_oam_entry(st[0xc00:0x1000],i)
  a0=int(e['attr0'],16);a1=int(e['attr1'],16)
  if not a0&0x100:continue
  assert not a0&0x2000
  w,h=e['width'],e['height'];dw=w*(2 if a0&0x200 else 1);dh=h*(2 if a0&0x200 else 1)
  matrix=(a1>>9)&31
  pa,pb,pc,pd=[struct.unpack_from('<h',st,0xc00+matrix*32+6+j*8)[0] for j in range(4)]
  for y in range(dh):
   for x in range(dw):
    sx=((pa*(x-dw//2)+pb*(y-dh//2))>>8)+w//2
    sy=((pc*(x-dw//2)+pd*(y-dh//2))>>8)+h//2
    px=e['x']+x;py=e['y']+y
    if not(0<=sx<w and 0<=sy<h and 0<=px<240 and 0<=py<160):continue
    tid=e['tile']+(sy//8)*(w//8)+sx//8
    b=st[0x11000+tid*32+(sy%8)*4+(sx%8)//2];v=(b>>(4*(sx&1)))&15
    if v:frame.putpixel((px,py),bg.rgb555(u16(st,0xa00+e['palette_bank']*32+v*2)))
 return frame

def main():
 DEST.mkdir(exist_ok=True)
 parent=MAIN_TIP_ROM.read_bytes();jp=ORIGINAL_ROM.read_bytes()
 assert sha(parent)==json.loads(MAIN_TIP_MANIFEST.read_text(encoding='utf8'))['sha256']
 states={n:statefmt.parse_png_state(ROOT/f'SD Gundam GGeneration Advance (Korean).ss{n}')[0] for n in (2,5)}
 candidate=bytearray(parent)
 # Animation palette lists, not header word +4, determine the extent.
 turn=u32(parent,0x1a248)-0x8000000;assert turn==0x1f62000
 palette=turn+u32(parent,turn+12);native=0x165044+u32(jp,0x165050)
 selectors=[]
 for i in range(u32(parent,turn+16)):
  entry=turn+20+i*4;desc=entry+(u32(parent,entry)&~3)
  selectors.append(list(parent[desc+8:desc+8+u16(parent,desc+6)]))
 assert selectors==[[0,2,1],[3,4,1],[5,6,1],[7,8,1]]
 assert parent[palette:palette+192]==jp[native:native+192]
 assert not any(parent[palette+192:palette+288])
 candidate[palette+192:palette+288]=jp[native+192:native+288]
 assert candidate[palette:palette+288]==jp[native:native+288]
 s5=states[5];assert s5[0xaa0:0xae0]==bytes(64)
 fixed5=bytearray(s5)
 for i,src in enumerate(selectors[3]):fixed5[0xaa0+i*32:0xac0+i*32]=candidate[palette+src*32:palette+(src+1)*32]
 # Verify the visible banner really uses the translated graphics.
 gfx=parent[turn+u32(parent,turn+8):palette]
 banner=s5[0x11000+256*32:0x11000+384*32]
 lookup={gfx[i:i+32] for i in range(0,len(gfx),32)}
 assert all(banner[i:i+32] in lookup for i in range(0,len(banner),32))
 # SS2's BG1 warning: all live tiles bind exactly to the current atlas.
 s2=states[2];info=bg.bg_info(s2,1);assert info['scroll_x']==info['scroll_y']==info['char_base']==0
 atlasoff=u32(parent,0xdab70)-0x8000000
 old=sem.lzss_decompress(parent[atlasoff+4:atlasoff+4+(u32(parent,atlasoff)&65535)])
 atlas=bytearray(old);cells=[];bindings=[]
 for y in range(10,15):
  for x in range(15,25):
   cell=bg.map_entry(s2[0x1000:0x19000],info['screen_base'],info['size'],x,y)
   assert not cell&0xc00
   tid=cell&1023;raw=s2[0x1000+tid*32:0x1000+(tid+1)*32]
   hits=[i//32 for i in range(0,len(old),32) if old[i:i+32]==raw]
   assert hits,(x,y,tid)
   cells.append(hits[0]);bindings.append((tid,hits[0],cell>>12))
 m={'width':10,'height':5,'cells':cells};before=sem.stitch(old,m);after=[row[:] for row in before]
 # Preserve warning icon and border. The native text face/outline are 10/5.
 for x0,y0,x1,y1 in [(22,5,77,21),(6,21,78,35)]:
  for y in range(y0,y1):
   for x in range(x0,x1):
    if after[y][x] in (5,10):after[y][x]=7 if y<11 or y>=32 else (6 if y<13 or y>=30 else 8)
 with ZipFile(FONT_ZIP) as z:font=paintutil.fontpair.load_bdf(z,'Galmuri11.bdf')
 paintutil.paint(after,'L사이즈',26,7,font,10,5)
 paintutil.paint(after,'스택 불가',16,23,font,10,5)
 updates=paintutil.tile_updates(before,after,m)
 changed={tid:raw for tid,raw in updates.items() if raw!=old[tid*32:(tid+1)*32]}
 for tid,raw in changed.items():atlas[tid*32:(tid+1)*32]=raw
 map_effects={}
 for i in range(2,25):
  other=sem.parse_map(parent,u32(parent,0xdab70+i*4))
  shared=sorted(set(c&1023 for c in other['cells'])&set(changed))
  if shared:map_effects[i]=shared
  else:assert sem.stitch(old,other)==sem.stitch(atlas,other)
 assert set(map_effects)=={13,14},map_effects
 blob=compression.literal_only_compress(bytes(atlas));assert len(blob)==4+(u32(parent,atlasoff)&65535)
 assert sem.lzss_decompress(blob[4:])==atlas
 candidate[atlasoff:atlasoff+len(blob)]=blob
 fixed2=bytearray(s2)
 for tid,sid,_ in bindings:
  if sid in changed:fixed2[0x1000+tid*32:0x1000+(tid+1)*32]=changed[sid]
 allowed=[(atlasoff,atlasoff+len(blob)),(palette+192,palette+288)]
 diffs=[i for i,(a,b) in enumerate(zip(parent,candidate)) if a!=b]
 assert all(any(lo<=i<hi for lo,hi in allowed) for i in diffs)
 result=DEST/'ggen_advance_stack_warning_support_palette_candidate_20260909.gba';result.write_bytes(candidate)
 renderer.OUT=DEST
 for n,st in [(2,fixed2),(5,fixed5)]:render_affine_banner(bytes(st)).resize((960,640),Image.Resampling.NEAREST).save(DEST/f'ss{n}_after_static.png')
 render_affine_banner(s5).resize((960,640),Image.Resampling.NEAREST).save(DEST/'ss5_before_reconstructed.png')
 colors=raster.palette_rgb(s2[0x800+bindings[0][2]*32:0x820+bindings[0][2]*32])
 gallery([(name,raster.render_canvas(c,colors)) for name,c in [('before',before),('after',after)]],DEST/'warning_before_after.png',5)
 report={'parent':{'sha256':sha(parent)},'output':{'path':str(result.relative_to(ROOT)),'sha256':sha(candidate),'size':len(candidate)},'states':{str(n):sha((ROOT/f'SD Gundam GGeneration Advance (Korean).ss{n}').read_bytes()) for n in states},'ss2':{'layer':'BG1','atlas_offset':hex(atlasoff),'translation':['L사이즈','스택 불가'],'changed_source_tiles':sorted(changed),'live_tile_bindings':bindings},'ss5':{'cause':'Prior resource_blob builder truncated palette data at six banks; animations reference banks 6, 7 and 8 as well. Missing clone data is zero, causing black OBJ banks 5/6 for support banner.','animation_palette_selectors':selectors,'restored_range':[hex(palette+192),hex(palette+288)],'original_range':[hex(native+192),hex(native+288)],'live_banner_tiles_match':True},'allowed_ranges':[[hex(a),hex(b)] for a,b in allowed],'verification':{'result':'PASS','changed_bytes':len(diffs),'outside_allowed_ranges_unchanged':True,'compression_roundtrip':True,'full_nine_palettes_original_exact':True,'runtime_emulator':'not run; reconstructed supplied state graphics for visual review'}}
 report['ss2']['affected_map_ids']=map_effects
 (DEST/'manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
 print(json.dumps({k:v for k,v in report.items() if k!='ss2'},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
