"""Local all-clear profile/BGM investigation; supplied states remain read-only."""
import sys,struct,json,os,subprocess,time
from pathlib import Path
from verify_ggen_ss_tiles_runtime_20260905 import GDB
import analyze_ggen_advance_unit_list_sprite_state_20260830 as sf
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs/20260911_allclear_profiles'
def main():
 env=os.environ.copy();env.update(SDL_VIDEODRIVER='dummy',SDL_AUDIODRIVER='dummy')
 with (OUT/'probe.log').open('w') as log:
  p=subprocess.Popen([str(ROOT/'mGBA-0.10.5-win64/mgba-sdl.exe'),'-g','-C','videoRenderer=0','-t',str(ROOT/'SD Gundam GGeneration Advance (Korean)_allclear.ss2'),str(ROOT/'SD Gundam GGeneration Advance (Korean).gba')],env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
  try:
   g=GDB();print(g.cmd('?'));g.packet(b'c');time.sleep(.2);g.s.sendall(b'\x03');print(g.recv());regs=bytes.fromhex(g.cmd('g').decode());vals=struct.unpack_from('<16I',regs);print([hex(x) for x in vals]);print(g.mem(vals[13],128).hex());g.s.close()
  finally:p.terminate();p.wait(timeout=5)
if __name__=='__main__':main()
