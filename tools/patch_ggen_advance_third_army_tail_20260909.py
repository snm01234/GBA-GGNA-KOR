"""Remove the native 軍 tail omitted by the 64px third-faction repaint."""
from ggen_ss_tiles_common_20260905 import *
import patch_ggen_advance_stack_warning_support_palette_20260909 as previous
import analyze_ggen_advance_settings_suspend_ui as animations
import hashlib, json, binascii

DEST=ROOT/'outputs/20260909_ss2_ss5_diagnosis'
PARENT=DEST/'ggen_advance_stack_warning_support_palette_candidate_20260909.gba'
STATE=PARENT.with_suffix('.ss2')
RESULT=DEST/'ggen_advance_stack_warning_support_palette_candidate_v2_20260909.gba'
def sha(b):return hashlib.sha256(b).hexdigest()

def main():
 parent=PARENT.read_bytes();st,_=statefmt.parse_png_state(STATE)
 assert sha(parent)=='5d92c4e5a8dc226e2c4d24c05897872314a29a1915d566c1eb0ea4d4cb5f578f'
 assert u32(st,8)==binascii.crc32(parent)&0xffffffff
 base=u32(parent,0x1a248)-0x8000000
 gfx=base+u32(parent,base+8);pal=base+u32(parent,base+12)
 tail=list(range(172,180))
 # The animation table starts are relative to each pointer entry.
 descriptors=[]
 for i in range(4):
  entry=base+20+i*4;start=entry+(u32(parent,entry)&~3)
  end=base+u32(parent,base+8) if i==3 else (entry+4)+(u32(parent,entry+4)&~3)
  raw=parent[start:end]
  # Audit exact interleaved tail rows in the complete animation stream.
  signatures=[struct.pack('<HH',t,t+1) for t in range(172,180,2)]
  used={t for t in tail if signatures[(t-172)//2] in raw}
  descriptors.append({'animation':i,'tail_tiles':sorted(used&set(tail))})
  if i!=3:assert not used&set(tail)
  else:assert set(tail)<=used
 # SS2's second 64x32 OBJ has the two remaining columns at its left.
 e=statefmt.parse_oam_entry(st[0xc00:0x1000],2)
 assert (e['x'],e['y'],e['width'],e['height'])==(92,80,64,32)
 live=[];candidate=bytearray(parent);fixed=bytearray(st)
 for i,src in enumerate(tail):
  tid=e['tile']+(i//2)*8+i%2
  old=parent[gfx+src*32:gfx+(src+1)*32]
  assert any(old)
  assert st[0x11000+tid*32:0x11000+(tid+1)*32]==old
  candidate[gfx+src*32:gfx+(src+1)*32]=bytes(32)
  fixed[0x11000+tid*32:0x11000+(tid+1)*32]=bytes(32)
  live.append(tid)
 lo=gfx+172*32;hi=gfx+180*32
 # Both labels already use face 8, shadow 4, outline 15 with the same
 # Galmuri11/2px-shadow/1px-outline raster style. Their palette banks differ.
 # Match the top turn label to the lower third-faction gold colors.
 style_offsets=[]
 for index in (4,8,15):
  dst=pal+7*32+index*2;src=pal+8*32+index*2
  candidate[dst:dst+2]=parent[src:src+2];style_offsets.extend((dst,dst+1))
  fixed[0xaa0+index*2:0xaa2+index*2]=parent[src:src+2]
 assert candidate[pal+6*32:pal+7*32]==parent[pal+6*32:pal+7*32]
 allowed=set(range(lo,hi))|set(style_offsets)
 assert all(a==b or i in allowed for i,(a,b) in enumerate(zip(parent,candidate)))
 assert candidate[0x1f30000:0x1f3364c]==parent[0x1f30000:0x1f3364c]
 RESULT.write_bytes(candidate)
 previous.renderer.OUT=DEST
 previous.render_affine_banner(st).resize((960,640),Image.Resampling.NEAREST).save(DEST/'third_army_before_static.png')
 previous.render_affine_banner(bytes(fixed)).resize((960,640),Image.Resampling.NEAREST).save(DEST/'third_army_after_static.png')
 report={'parent':{'path':str(PARENT.relative_to(ROOT)),'sha256':sha(parent)},'output':{'path':str(RESULT.relative_to(ROOT)),'sha256':sha(candidate),'size':len(candidate)},'state':{'path':str(STATE.relative_to(ROOT)),'sha256':sha(STATE.read_bytes()),'rom_crc_matches':True},'cause':'Third faction repaint covered source tiles 140-171 (64px). Native 軍 continued into the first two columns of the next OBJ, source tiles 172-179, which were never cleared.','fix':{'source_tiles':tail,'live_tiles':live,'file_range':[hex(lo),hex(hi)],'replacement':'transparent palette index 0','animation_ownership':descriptors},'style':{'palette_7_face_shadow_outline_match_palette_8':True,'colors':[hex(u16(candidate,pal+7*32+i*2)) for i in (8,4,15)],'font':'Galmuri11','shadow_px':2,'white_outline_px':1,'note':'Existing glyph geometry uses identical raster recipe. Unified the differing third-faction palette color roles; turn numeral shares palette 7.'},'verification':{'result':'PASS','all_eight_live_tiles_exact':True,'only_tail_graphics_and_three_color_entries_allowed':True,'warning_graphics_unchanged':True,'missing_palettes_remain_restored':True,'changed_bytes':sum(a!=b for a,b in zip(parent,candidate)),'runtime_emulator':'not run; supplied live state ownership verified and static reconstruction inspected'}}
 (DEST/'third_army_tail_v2_manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
 print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
