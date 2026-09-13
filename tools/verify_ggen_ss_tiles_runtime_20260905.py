"""Headless local mGBA GDB readback, without touching the user's emulator."""
from ggen_ss_tiles_common_20260905 import *
import os,socket,subprocess,time,json
class GDB:
 def __init__(self):
  for attempt in range(15):
   try:self.s=socket.create_connection(('127.0.0.1',2345),timeout=1);break
   except OSError:
    if attempt==14:raise
    time.sleep(0.5)
  self.s.settimeout(5)
 def packet(self,p):self.s.sendall(b'$'+p+b'#'+f'{sum(p)%256:02x}'.encode())
 def recv(self):
  c=self.s.recv(1)
  while c!=b'$':c=self.s.recv(1)
  b=b'';c=self.s.recv(1)
  while c!=b'#':b+=c;c=self.s.recv(1)
  self.s.recv(2);self.s.sendall(b'+');return b
 def cmd(self,p):self.packet(p.encode());return self.recv()
 def mem(self,addr,size):
  result=b''
  for i in range(0,size,512):result+=bytes.fromhex(self.cmd(f'm{addr+i:x},{min(512,size-i):x}').decode())
  return result
def main():
 env=os.environ.copy();env['SDL_VIDEODRIVER']='dummy';env['SDL_AUDIODRIVER']='dummy'
 rom=OUT/'ggen_ss1_ss4_tiles_ko_20260905.gba'
 results=[]
 for n in range(1,5):
  log=open(OUT/f'emu_ss{n}.log','w')
  p=subprocess.Popen([str(ROOT/'mGBA-0.10.5-win64/mgba-sdl.exe'),'-g','-C','videoRenderer=0','-t',str(rom.with_suffix(f'.ss{n}')),str(rom)],env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
  try:
   time.sleep(1)
   if p.poll() is not None:raise RuntimeError((OUT/f'emu_ss{n}.log').read_text())
   g=GDB();print(n,g.cmd('?'),flush=True);g.packet(b'c');time.sleep(1);g.s.sendall(b'\x03');print(g.recv(),flush=True)
   st,_=statefmt.parse_png_state(rom.with_suffix(f'.ss{n}'));updated=bytearray(st)
   for addr,off,size in [(0x04000000,0x400,0x400),(0x05000000,0x800,0x400),(0x07000000,0xc00,0x400),(0x06000000,0x1000,0x18000)]:updated[off:off+size]=g.mem(addr,size)
   (OUT/f'runtime_ss{n}.bin').write_bytes(updated);g.s.close();results.append({'state':n,'ran_seconds':1})
  finally:p.terminate();p.wait(timeout=5);log.close()
 (OUT/'runtime_report.json').write_text(json.dumps(results,indent=2))
if __name__=='__main__':main()

