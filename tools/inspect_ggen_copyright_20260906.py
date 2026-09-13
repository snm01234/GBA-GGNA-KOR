import sys, os, subprocess, time, struct
from verify_ggen_ss_tiles_runtime_20260905 import GDB, ROOT
out=ROOT/'outputs/20260906_ggen_copyright'
env=os.environ.copy();env.update(SDL_VIDEODRIVER='dummy',SDL_AUDIODRIVER='dummy')
with open(out/'trace.log','w') as log:
 p=subprocess.Popen([str(ROOT/'mGBA-0.10.5-win64/mgba-sdl.exe'),'-g','-C','videoRenderer=0',str(out/'debug.gba')],env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
 try:
  time.sleep(1);g=GDB();print(g.cmd('?'),flush=True);print(g.cmd('Z2,6000020,4'),flush=True)
  for i in range(12):
   g.packet(b'c');print(g.recv(),flush=True)
   regs=g.cmd('g');print([hex(x) for x in struct.unpack('<'+str(len(regs)//8)+'I',bytes.fromhex(regs.decode()))],flush=True)
 finally:p.terminate();p.wait()

