"""Execute the original credit-list renderer on an ARM CPU with captured RAM.

This is a bounded ROM-code test with immediate DMA modeled, not full-game playback.
"""
import sys,json,struct
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs/20260912_ss123_credits'
sys.path.insert(0,str(OUT/'deps'))
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_THUMB,UC_HOOK_CODE,UC_HOOK_MEM_WRITE
from unicorn.arm_const import *
from analyze_ggen_advance_unit_list_sprite_state_20260830 import parse_png_state
from analyze_ggen_advance_jp_ko_ss1_n_tile_owned_count_20260903 import render_bg_native
from PIL import Image,ImageDraw
def composite(state):
 # Text-plane diagnostics only. Captured OBJ layers can occlude a synthetic
 # redraw at a different credit phase; do not present it as game playback.
 im=Image.new('RGBA',(240,160),(0,0,24,255))
 return Image.alpha_composite(im,render_bg_native(state,0)).convert('RGB')
REGIONS=[(0x02000000,0x21000,0x40000),(0x03000000,0x19000,0x8000),(0x04000000,0x400,0x400),(0x05000000,0x800,0x400),(0x06000000,0x1000,0x18000),(0x07000000,0xc00,0x400)]

def run(st,rom,calls):
 u=Uc(UC_ARCH_ARM,UC_MODE_THUMB)
 for a,size in [(0x2000000,0x40000),(0x3000000,0x8000),(0x4000000,0x1000),(0x5000000,0x1000),(0x6000000,0x20000),(0x7000000,0x1000),(0x8000000,0x2000000)]:u.mem_map(a,size)
 for a,o,size in REGIONS:u.mem_write(a,bytes(st[o:o+size]))
 u.mem_write(0x8000000,rom)
 pending=[];draws=[];dma=[]
 def write(uc,access,a,size,value,_):
  if a==0x40000dc and size==4 and value&0x80000000:pending.append(value)
 def step(uc,a,size,_):
  while pending:
   ctl=pending.pop(0);src,dst=struct.unpack('<II',uc.mem_read(0x40000d4,8));count=ctl&65535 or 65536;unit=4 if ctl&(1<<26) else 2
   sm=(ctl>>23)&3;dm=(ctl>>21)&3;assert sm in (0,2) and dm==0
   data=bytes(uc.mem_read(src,count*unit)) if sm==0 else bytes(uc.mem_read(src,unit))*count
   uc.mem_write(dst,data);uc.mem_write(0x40000dc,struct.pack('<I',ctl&0x7fffffff));dma.append([src,dst,len(data)])
  if a==0x8000ca0:draws.append(dict(x=uc.reg_read(UC_ARM_REG_R1),y=uc.reg_read(UC_ARM_REG_R2),pointer=uc.reg_read(UC_ARM_REG_R3)))
 u.hook_add(UC_HOOK_MEM_WRITE,write);u.hook_add(UC_HOOK_CODE,step)
 for call in calls:
  index,x,y=call[:3]
  if len(call)==4:u.mem_write(0x200a0de,struct.pack('<H',call[3]))
  for reg,v in zip([UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3],[x,y,0x7fff,index]):u.reg_write(reg,v)
  u.reg_write(UC_ARM_REG_SP,0x3007000);u.reg_write(UC_ARM_REG_LR,0x8000101)
  try:u.emu_start(0x80116c5,0x8000100,count=3000000)
  except Exception:print('failed',index,hex(u.reg_read(UC_ARM_REG_PC)));raise
  assert u.reg_read(UC_ARM_REG_PC)==0x8000100
 out=bytearray(st)
 for a,o,size in REGIONS:out[o:o+size]=u.mem_read(a,size)
 return out,draws,dma

def main():
 report=json.loads((OUT/'manifest.json').read_text(encoding='utf-8'));rom=(ROOT/report['output']['path']).read_bytes()
 st,_=parse_png_state(ROOT/'SD Gundam GGeneration Advance (Korean).ss3')
 # Remove the captured text layer, retaining other graphics and palettes.
 st=bytearray(st);st[0xefe0:0xf000]=bytes(32);st[0xf000:0x10000]=struct.pack('<H',0xb2ff)*2048
 # Isolate the tested text plane: the late-credit background shares VRAM
 # with earlier six-line pages and is not valid for those synthetic cases.
 struct.pack_into('<H',st,0x400,0x100)
 proofs=[];panels=[];regressions=[]
 parent=(ROOT/'SD Gundam GGeneration Advance (Korean).gba').read_bytes()
 import hashlib
 if hashlib.sha256(parent).hexdigest()!=report['parent_sha256']:
  tip=json.loads((ROOT/'integrated/main_tip/ggen_advance_main_tip_manifest.json').read_text(encoding='utf-8'))
  parent=(ROOT/tip['previous_main_tip_backup']['path']).read_bytes()
 assert hashlib.sha256(parent).hexdigest()==report['parent_sha256']
 for index in (53,67,98):
  _,old_draws,_=run(st,parent,[(index,16,16)])
  _,new_draws,_=run(st,rom,[(index,16,16)])
  assert len(old_draws)==2 and len(new_draws)==1
  regressions.append(dict(index=index,before_lines=2,after_lines=1))
 for g in report['groups']:
  out,draws,dma=run(st,rom,[(g['index'],16,16)])
  assert len(draws)==g['original_line_count'],(g['index'],draws)
  assert [d['pointer'] for d in draws]==[l['pointer'] for l in g['lines']]
  assert [d['y'] for d in draws]==[16+16*i for i in range(len(draws))]
  proofs.append(dict(index=g['index'],draws=draws,dma_transfers=len(dma)))
  im=composite(out);panels.append((g['index'],im))
  if g['index'] in (53,54,67,68,98,99):im.resize((960,640),Image.Resampling.NEAREST).save(OUT/f'arm_group_{g["index"]}.png')
 sheet=Image.new('RGB',(960,((len(panels)+3)//4)*176))
 d=ImageDraw.Draw(sheet)
 for i,(index,im) in enumerate(panels):x=i%4*240;y=i//4*176;sheet.paste(im,(x,y+16));d.text((x,y),str(index),fill='white')
 sheet.save(OUT/'all_credits_arm.png')
 previews=[]
 for n,calls in [(1,[(51,60,88),(52,60,104),(53,4,120),(54,4,136)]),(2,[(65,16,32),(66,144,32),(67,16,112),(68,144,112)]),(3,[(98,54,42),(99,90,74)])]:
  orig,_=parse_png_state(ROOT/f'SD Gundam GGeneration Advance (Korean).ss{n}')
  clean=bytearray(orig);clean[0xefe0:0xf000]=bytes(32);clean[0xf000:0x10000]=struct.pack('<H',0xb2ff)*2048
  # Use the native start of the text tile pool for this redrawn page.
  struct.pack_into('<H',clean,0x2b0de,0x400)
  out,draws,dma=run(clean,rom,calls)
  im=composite(out);im.resize((960,640),Image.Resampling.NEAREST).save(OUT/f'ss{n}_arm_redraw.png');previews.append(im)
 sheet=Image.new('RGB',(960,1920))
 for i,im in enumerate(previews):sheet.paste(im.resize((960,640),Image.Resampling.NEAREST),(0,i*640))
 sheet.save(OUT/'ss123_arm_redraw.png')
 report['verification'].update(runtime='Unicorn ARM: actual 0x080116C4 credit renderer, captured RAM, immediate DMA model; not full mGBA playback',arm_all_71_containers=proofs,regressions=regressions,preview='ss123_arm_redraw.png (isolated text-plane diagnostic at explicit coordinates; not a complete game screenshot; original savestates unmodified)')
 (OUT/'manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print('PASS: 71 credit containers / actual ARM renderer / exact line pointers and Y increments')
if __name__=='__main__':main()
