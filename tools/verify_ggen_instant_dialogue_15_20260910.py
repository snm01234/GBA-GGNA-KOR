"""Run the real immediate renderer in isolated headless mGBA with captured RAM."""
import json
import os
import socket
import struct
import subprocess
import time
from pathlib import Path
from build_ggen_instant_dialogue_15_20260910 import ROOT, OUT, ROM, sha
from analyze_ggen_advance_unit_list_sprite_state_20260830 import parse_png_state
from analyze_ggen_advance_owned_count_ec0c_trace_runtime_20260904 import composite


class GDB:
    def __init__(self):
        for attempt in range(20):
            try:
                self.s = socket.create_connection(('127.0.0.1',2345),timeout=1)
                break
            except OSError:
                if attempt==19:raise
                time.sleep(0.3)
        self.s.settimeout(15)
    def cmd(self,text):
        p=text.encode();self.s.sendall(b'$'+p+b'#'+f'{sum(p)%256:02x}'.encode())
        while self.s.recv(1)!=b'$':pass
        p=b''
        while True:
            c=self.s.recv(1)
            if c==b'#':break
            p+=c
        self.s.recv(2);self.s.sendall(b'+');return p.decode()
    def mem(self,addr,size):
        return b''.join(bytes.fromhex(self.cmd(f'm{addr+i:x},{min(512,size-i):x}')) for i in range(0,size,512))
    def registers(self):return bytearray.fromhex(self.cmd('g'))
    def setregs(self,values):
        r=self.registers()
        for idx,value in values.items():struct.pack_into('<I',r,idx*4,value)
        assert self.cmd('G'+r.hex())=='OK'


def run_case(state_number,x,rom=ROM,label=None):
    label=label or f'ss{state_number}_x{x}'
    statepath=ROOT/f'SD Gundam GGeneration Advance (Korean).ss{state_number}'
    st,_=parse_png_state(statepath)
    env=os.environ.copy();env['SDL_VIDEODRIVER']='dummy';env['SDL_AUDIODRIVER']='dummy'
    log=(OUT/f'{label}.log').open('w')
    proc=subprocess.Popen([str(ROOT/'mGBA-0.10.5-win64/mgba-sdl.exe'),'-g','-C','videoRenderer=0','-t',str(statepath),str(rom)],env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        time.sleep(1)
        assert proc.poll() is None
        g=GDB();g.cmd('?')
        # Re-enter a bounded renderer call using the captured environment.
        # No user emulator, original state, original SAV, or original ROM is written.
        start=[0x08f7fad4,0x08f7f766,0x08f7f7c3,0x08f7f875][state_number-1]
        assert g.mem(0x0200a0c0,4)==st[0x2b0c0:0x2b0c4]
        regs=g.registers(); sp=struct.unpack_from('<I',regs,13*4)[0]
        g.setregs({0:start,1:x,2:104,14:0x08000101,15:0x0800d6e0})
        assert g.cmd('Z0,800d7b4,2')=='OK'
        assert g.cmd('Z0,8000100,2')=='OK'
        draws=[]
        for _ in range(2):
            g.cmd('c')
            rr=g.registers();pc=struct.unpack_from('<I',rr,60)[0]
            assert pc==0x0800d7b4,hex(pc)
            r0,r1,r2,r3=struct.unpack_from('<4I',rr)
            stack=struct.unpack_from('<I',rr,52)[0]
            limit=int.from_bytes(g.mem(stack,4),'little')
            draws.append({'x':r1,'y':r2,'limit':limit,'text_pointer':hex(r3),'context':hex(r0)})
            # Advance past BL once (single step enters the called function).
            g.cmd('s')
        assert g.cmd('z0,800d7b4,2')=='OK'
        g.cmd('c')
        rr=g.registers();assert struct.unpack_from('<I',rr,60)[0]==0x08000100
        assert struct.unpack_from('<I',rr,52)[0]==sp
        returned=struct.unpack_from('<I',rr)[0]
        assert returned==int.from_bytes(st[0x2b0c0:0x2b0c4],'little')
        finalctx=g.mem(int(draws[-1]['context'],16),0x68)
        finalcount=struct.unpack_from('<H',finalctx,0x18)[0]
        updated=bytearray(st)
        for addr,off,size in [(0x04000000,0x400,0x400),(0x05000000,0x800,0x400),(0x07000000,0xc00,0x400),(0x06000000,0x1000,0x18000)]:
            updated[off:off+size]=g.mem(addr,size)
        (OUT/f'{label}.bin').write_bytes(updated)
        composite(updated).resize((960,640)).save(OUT/f'{label}.png')
        g.s.close()
        return {'case':label,'draws':draws,'final_count':finalcount,'returned_script':hex(returned),'stack_restored':True}
    finally:
        proc.terminate();proc.wait(timeout=5);log.close()


def main():
    results=[]
    for n,x in [(1,48),(1,60),(2,48),(3,48),(4,48)]:
        result=run_case(n,x);results.append(result);print(json.dumps(result),flush=True)
        assert all(d['limit']==(15 if x==48 else 14) for d in result['draws'])
        assert result['final_count']==(15 if x==48 else 14)
    (OUT/'runtime.json').write_text(json.dumps(results,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':main()
