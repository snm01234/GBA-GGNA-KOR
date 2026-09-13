"""Run the candidate in an isolated headless mGBA process."""
import os, subprocess, time, json, struct
from pathlib import Path
from verify_ggen_ss_tiles_runtime_20260905 import GDB
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs/20260911_stage_title_tiles'
def main():
    env=os.environ.copy();env['SDL_VIDEODRIVER']='dummy';env['SDL_AUDIODRIVER']='dummy'
    with (OUT/'emulator.log').open('w') as log:
        p=subprocess.Popen([str(ROOT/'mGBA-0.10.5-win64/mgba-sdl.exe'),'-g','-C','videoRenderer=0','-t',str(ROOT/'SD Gundam GGeneration Advance (Korean).ss1'),str(OUT/'ggen_special_stage_tiles_ko_20260911.gba')],env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            g=GDB();print(g.cmd('?'),flush=True)
            g.packet(b'c');time.sleep(.2);g.s.sendall(b'\x03');print(g.recv(),flush=True)
            live=g.mem(0x6010000,116*32);expected=(OUT/'ss1_vram_reconstruction.bin').read_bytes()[0x11000:0x11000+116*32]
            print('initial runtime match',live==expected,flush=True)
            print('registers',g.cmd('g').decode(),flush=True)
            (OUT/'runtime_initial_obj.bin').write_bytes(live)
            g.s.close()
        finally:p.terminate();p.wait(timeout=5)
if __name__=='__main__':main()
