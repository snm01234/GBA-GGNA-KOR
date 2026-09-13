"""Reconstruct mode-0 BG/OBJ layers from GBA graphics memory for review."""
from ggen_ss_tiles_common_20260905 import *
import analyze_ggen_advance_intermission_cycle_states_20260830 as bg
def render(st):
 pal=st[0x800:0xc00];dispcnt=u16(st,0x400);frame=Image.new('RGBA',(240,160),(*bg.rgb555(u16(pal,0)),255));layers=[]
 for l in range(4):
  if dispcnt&(0x100<<l):
   info=bg.bg_info(st,l);path=OUT/f'_render_bg{l}.png';bg.render_bg(st,info,path);layers.append((info['priority'],l+1,Image.open(path).resize((240,160),Image.Resampling.NEAREST)))
 if dispcnt&0x1000:
  for i in range(127,-1,-1):
   e=statefmt.parse_oam_entry(st[0xc00:0x1000],i);a0=int(e['attr0'],16);a1=int(e['attr1'],16)
   if a0&0x300==0x200:continue
   if a0&0x100:continue # none of the edited text objects is affine
   im=Image.new('RGBA',(240,160));pix=im.load();w=e['width'];h=e['height']
   for y in range(h):
    for x in range(w):
     px=e['x']+x;py=e['y']+y
     if not(0<=px<240 and 0<=py<160):continue
     sx=w-1-x if a1&0x1000 else x;sy=h-1-y if a1&0x2000 else y
     tid=e['tile']+(sy//8)*(w//8 if dispcnt&0x40 else 32)+sx//8
     b=st[0x11000+tid*32+(sy%8)*4+(sx%8)//2];v=(b>>(4*(sx&1)))&15
     if v:pix[px,py]=(*bg.rgb555(u16(pal,512+e['palette_bank']*32+v*2)),255)
   layers.append((e['priority'],-(128-i)/128,im))
 for _,_,im in sorted(layers,key=lambda a:(a[0],a[1]),reverse=True):frame.alpha_composite(im)
 return frame.convert('RGB')
if __name__=='__main__':
 panels=[]
 for n in range(1,5):
  src=ROOT/f'SD Gundam GGeneration Advance (Korean).ss{n}';dst=OUT/f'ggen_ss1_ss4_tiles_ko_20260905.ss{n}'
  old,_=statefmt.parse_png_state(src);new,_=statefmt.parse_png_state(dst)
  a=render(old);b=render(new);b.resize((960,640),Image.Resampling.NEAREST).save(OUT/f'ss{n}_after.png')
  panel=Image.new('RGB',(480,160));panel.paste(a,(0,0));panel.paste(b,(240,0));panels.append(panel)
 sheet=Image.new('RGB',(960,1280))
 for i,p in enumerate(panels):sheet.paste(p.resize((960,320),Image.Resampling.NEAREST),(0,i*320))
 sheet.save(OUT/'four_states_before_after.png')
