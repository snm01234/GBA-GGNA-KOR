"""Execute actual ROM renderer on ARM CPU with captured state and immediate DMA.

This is a bounded renderer test, not a full-game mGBA replay. GBA DMA copies
are modeled; text parsing, font drawing, hooks and tile transfers run ROM code.
"""
import sys
import json
import struct
from pathlib import Path
from build_ggen_instant_dialogue_15_20260910 import ROOT, OUT, ROM, sha, ICON_SOURCE, ICON_CLONE, ICON_SIZE, compact_tile
sys.path.insert(0,str(OUT/'deps'))
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn.arm_const import *
from analyze_ggen_advance_unit_list_sprite_state_20260830 import parse_png_state
from analyze_ggen_advance_owned_count_ec0c_trace_runtime_20260904 import composite


def run_case(n,x,rom,label):
    st,_=parse_png_state(ROOT/f'SD Gundam GGeneration Advance (Korean).ss{n}')
    u=Uc(UC_ARCH_ARM,UC_MODE_THUMB)
    for a,size in [(0x02000000,0x40000),(0x03000000,0x8000),(0x04000000,0x1000),
                   (0x05000000,0x1000),(0x06000000,0x20000),(0x07000000,0x1000),
                   (0x08000000,0x2000000)]:u.mem_map(a,size)
    regions=[(0x02000000,0x21000,0x40000),(0x03000000,0x19000,0x8000),
             (0x04000000,0x400,0x400),(0x05000000,0x800,0x400),
             (0x06000000,0x1000,0x18000),(0x07000000,0xc00,0x400)]
    for a,off,size in regions:u.mem_write(a,st[off:off+size])
    u.mem_write(0x08000000,rom)
    start=[0x08f7fad4,0x08f7f766,0x08f7f7c3,0x08f7f875][n-1]
    regs=[UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2]
    for reg,v in zip(regs,[start,x,104]):u.reg_write(reg,v)
    u.reg_write(UC_ARM_REG_SP,0x03007000)
    u.reg_write(UC_ARM_REG_LR,0x08000101)
    pending=[];draws=[];contexts=[];dma=[]
    def write(uc,access,a,size,value,_):
        if a==0x040000dc and size==4 and value&0x80000000:pending.append(value)
    def step(uc,a,size,_):
        while pending:
            ctl=pending.pop(0)
            src,dst=struct.unpack('<II',uc.mem_read(0x040000d4,8))
            count=ctl&65535 or 65536;unit=4 if ctl&(1<<26) else 2
            sm=(ctl>>23)&3;dm=(ctl>>21)&3
            assert sm in (0,2) and dm==0,(hex(ctl),sm,dm)
            data=bytes(uc.mem_read(src,count*unit)) if sm==0 else bytes(uc.mem_read(src,unit))*count
            uc.mem_write(dst,data)
            uc.mem_write(0x040000dc,struct.pack('<I',ctl&0x7fffffff))
            dma.append({'src':hex(src),'dst':hex(dst),'bytes':len(data)})
        if a==0x0800d7b4:
            ctx=uc.reg_read(UC_ARM_REG_R0);contexts.append(ctx)
            draws.append({'x':uc.reg_read(UC_ARM_REG_R1),'y':uc.reg_read(UC_ARM_REG_R2),
                          'limit':int.from_bytes(uc.mem_read(uc.reg_read(UC_ARM_REG_SP),4),'little')})
    u.hook_add(UC_HOOK_MEM_WRITE,write)
    u.hook_add(UC_HOOK_CODE,step)
    u.emu_start(0x0800d6e1,0x08000100,count=3000000)
    assert u.reg_read(UC_ARM_REG_PC)==0x08000100,hex(u.reg_read(UC_ARM_REG_PC))
    assert u.reg_read(UC_ARM_REG_SP)==0x03007000
    assert u.reg_read(UC_ARM_REG_R0)==int.from_bytes(st[0x2b0c0:0x2b0c4],'little')
    assert len(draws)==2
    count=int.from_bytes(u.mem_read(contexts[-1]+0x18,2),'little')
    updated=bytearray(st)
    for a,off,size in regions:updated[off:off+size]=u.mem_read(a,size)
    (OUT/f'{label}.bin').write_bytes(updated)
    composite(updated).resize((960,640)).save(OUT/f'{label}.png')
    if struct.unpack_from('<I',rom,0x11198)[0]==0x08000000+ICON_CLONE:
        # A state saved while waiting retains the old sprite. Reconstruct the
        # new private asset at the same captured animation phase for visual QA.
        preview=bytearray(updated)
        tiles=set()
        for index in range(128):
            off=0xc00+index*8
            a,b,c=struct.unpack_from('<3H',preview,off)
            if (b&511)!=223 or (a&255)<120 or (a>>8)&3==2:continue
            assert c>>12==11
            shape=a>>14;size=b>>14
            assert (shape,size) in [(0,0),(2,0)]
            struct.pack_into('<H',preview,off+2,(b&~511)|228)
            for tile in range(c&1023,(c&1023)+(2 if shape==2 else 1)):tiles.add(tile)
        for tile in tiles:
            off=0x11000+tile*32
            raw=bytes(preview[off:off+32])
            # Verify that each live old sprite tile really belongs to this resource.
            assert raw in rom[ICON_SOURCE+0x390:ICON_SOURCE+0x5f0]
            preview[off:off+32]=compact_tile(raw)
        composite(preview).resize((960,640)).save(OUT/f'{label}_icon_preview.png')
        (OUT/f'{label}_icon_preview.bin').write_bytes(preview)
    result={'case':label,'draws':draws,'final_count':count,'stack_restored':True,
            'script_end_preserved':True,'dma_transfers':dma}
    print(json.dumps({k:v for k,v in result.items() if k!='dma_transfers'}),flush=True)
    return result


def main():
    parent=(ROOT/'SD Gundam GGeneration Advance (Korean).gba').read_bytes()
    candidate=ROM.read_bytes();results=[]
    # ss2-4 use the historical ROM + the identical patch, preserving old glyphs.
    old=(ROOT/'integrated/main_tip/backups/20260910T105844Z_user_requested_aina_overflow_honorific_20260910/SD Gundam GGeneration Advance (Korean).gba').read_bytes()
    oldcandidate=bytearray(old)
    for i,(a,b) in enumerate(zip(parent,candidate)):
        if a!=b:
            assert old[i]==a
            oldcandidate[i]=b
    for n in range(1,5):
        before=parent if n==1 else old
        after=candidate if n==1 else bytes(oldcandidate)
        for x in (48,60):
            for version,r,limit in [('before',before,14),('after',after,15 if x==48 else 14)]:
                result=run_case(n,x,r,f'arm_ss{n}_x{x}_{version}');results.append(result)
                assert all(d['limit']==limit for d in result['draws'])
                assert result['final_count']==limit
            if x==60:
                assert (OUT/f'arm_ss{n}_x{x}_before.bin').read_bytes()[0x400:0x19000]==(OUT/f'arm_ss{n}_x{x}_after.bin').read_bytes()[0x400:0x19000]
    (OUT/'arm_runtime.json').write_text(json.dumps(results,indent=2)+'\n',encoding='utf-8')
    # All nontransparent sprite pixels stay in the 4px gutter, outside the
    # full 15th glyph cell (216..227) and inside the border at x=232.
    icon=candidate[ICON_CLONE:ICON_CLONE+ICON_SIZE]
    for off in range(0x390,0x5f0,32):
        for y in range(8):assert icon[off+y*4+2:off+y*4+4]==b'\x00\x00'
    for i in range(14):
        e=0x30+i*4;f=e+struct.unpack_from('<I',icon,e)[0]
        for j in range(struct.unpack_from('<H',icon,f+6)[0]):
            assert struct.unpack_from('<H',icon,f+0x12+8*j)[0]&511==508


if __name__=='__main__':main()
