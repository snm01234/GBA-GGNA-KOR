"""Complete the normal Korean action labels' 8-neighbour one-pixel outline."""
import json,struct
from pathlib import Path
from PIL import Image
import analyze_ggen_advance_ss9_action_menu_redraw_20260912 as audit
import build_ggen_advance_action_menu_ko_followup as action
import analyze_ggen_advance_ss9_action_menu_flash_20260912 as labels
import build_ggen_allclear_profiles_ko_20260912 as assets
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs/20260913_normal_shadow'
EXPECTED='c3f145c2e6b1511643b2b832275bcfeb1587a73bc92dfbb43e7802216deff6c3'
def main():
 OUT.mkdir(parents=True,exist_ok=True);parent=(ROOT/'SD Gundam GGeneration Advance (Korean).gba').read_bytes();assert assets.sha(parent)==EXPECTED
 table,atlas,maps=audit.load_maps(parent);maps.pop(0,None);ao=audit.u32(parent,table)-0x8000000
 new=bytearray(atlas);writes={};expected={};jobs=[];previews=[]
 for i in action.TRANSLATIONS:
  old=action.stitch_map(atlas,maps[18+i]);focus=action.stitch_map(atlas,maps[30+i]);ink={(x,y) for y in range(16) for x in range(32) if focus[y][x]==12}
  assert all(old[y][x]==11 for x,y in ink)
  ring={(x+dx,y+dy) for x,y in ink for dx in (-1,0,1) for dy in (-1,0,1) if 0<=x+dx<32 and 0<=y+dy<16}-ink
  missing=[(x,y) for x,y in ring if old[y][x]!=5];assert all(old[y][x]==9 for x,y in missing)
  target=[line[:] for line in old]
  for x,y in ring:target[y][x]=5
  assert all(target[y][x]==5 for x,y in ring);assert all(target[y][x]==11 for x,y in ink)
  for cell,raw in zip(maps[18+i]['cells'],action.rendered_payloads_for_map(target,maps[18+i])):
   tid=cell&1023
   if raw==atlas[tid*32:(tid+1)*32]:continue
   assert tid not in writes or writes[tid]==raw;writes[tid]=raw
  expected[18+i]=target;jobs.append(dict(resource=18+i,label=labels.LABELS[i],added_shadow_pixels=len(missing),missing_pixels=missing));previews.append((old,target,focus))
 for tid,raw in writes.items():new[tid*32:(tid+1)*32]=raw
 changedmaps=[]
 for idx,m in maps.items():
  old=action.stitch_map(atlas,m);want=expected.get(idx,[line[:] for line in old])
  if idx not in expected:
   # Whole/individual submenu labels also occur inside 11-column frame maps.
   for sub in (28,29):
    src=action.stitch_map(atlas,maps[sub])
    for y in range(0,len(old)-15,8):
     for x in range(0,len(old[0])-31,8):
      if all(old[y+yy][x:x+32]==src[yy] for yy in range(16)):
       for yy in range(16):want[y+yy][x:x+32]=expected[sub][yy]
  actual=action.stitch_map(new,m);assert actual==want,('unintended tile alias',idx)
  if actual!=old:changedmaps.append(idx)
 assert all(action.stitch_map(atlas,maps[i])==action.stitch_map(new,maps[i]) for i in range(30,44))
 body=action.literal_only_lzss_body(bytes(new));assert len(body)==(audit.u32(parent,ao)&65535)
 cand=bytearray(parent);cand[ao+4:ao+4+len(body)]=body
 assert audit.scan.lzss_decompress(body)==new and len(new)==239*32
 assert all(a==b or ao+4<=i<ao+4+len(body) for i,(a,b) in enumerate(zip(parent,cand)))
 statepath=ROOT/'SD Gundam GGeneration Advance (Korean).ss1';sh=assets.sha(statepath.read_bytes());st,_=audit.statefmt.parse_png_state(statepath);inf=audit.bgutil.bg_info(st,0)
 vram=st[0x1000:0x19000];cell=audit.bgutil.map_entry(vram,inf['screen_base'],inf['size'],4,5);tilebase=(cell&1023)-(maps[18]['cells'][0]&1023);off=0x1000+inf['char_base']+tilebase*32
 assert st[off:off+len(atlas)]==atlas,('captured atlas mismatch',hex(off))
 runtime=bytearray(st);runtime[off:off+len(new)]=new;audit.renderer.OUT=OUT
 after=audit.renderer.render(runtime);after.resize((960,640),Image.Resampling.NEAREST).save(OUT/'after_reconstructed.png')
 # Preview uses the captured normal palette; focus is shown with its own bank.
 normalbank=cell>>12;fc=audit.bgutil.map_entry(vram,inf['screen_base'],inf['size'],4,11);focusbank=fc>>12
 np=assets.raster.palette_rgb(st[0x800+normalbank*32:0x800+(normalbank+1)*32]);fp=assets.raster.palette_rgb(st[0x800+focusbank*32:0x800+(focusbank+1)*32])
 sheet=Image.new('RGB',(384,len(previews)*64))
 for i,(a,b,f) in enumerate(previews):
  for col,(pixels,pal) in enumerate([(a,np),(b,np),(f,fp)]):sheet.paste(assets.raster.render_canvas(pixels,pal).resize((128,64),Image.Resampling.NEAREST),(col*128,i*64))
 sheet.save(OUT/'normal_before_after_focus.png');assert assets.sha(statepath.read_bytes())==sh
 out=OUT/'ggen_normal_action_shadow_20260913.gba';out.write_bytes(cand)
 report=dict(parent_sha256=EXPECTED,output=dict(path=out.relative_to(ROOT).as_posix(),size=len(cand),sha256=assets.sha(cand)),jobs=jobs,changed_maps=changedmaps,changed_tiles=len(writes),atlas_offset=hex(ao),source_state_sha256=sh,verification=dict(result='PASS',all_korean_normal_outlines_complete=True,face_pixels_preserved=True,focus_and_disabled_maps_unchanged=True,frame_changes_only_whole_individual_labels=True,atlas_tiles=239,compressed_roundtrip=True,captured_atlas_exact=True,savestate_unchanged=True,runtime='ROM and captured VRAM reconstruction; not live emulator playback'))
 (OUT/'manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(report,ensure_ascii=True))
if __name__=='__main__':main()
