"""Build a guarded 15-cell immediate-dialogue candidate, without promotion."""
import json
import hashlib
import shutil
import struct
from pathlib import Path
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
from patch_ggen_advance_map_script_inline_poc import _Thumb

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs/20260910_instant_dialogue_15'
ROM = OUT / 'ggen_instant_dialogue_15.gba'
CAVE = 0x012B4000
ICON_SOURCE = 0x000CAFF4
ICON_CLONE = 0x012B4100
ICON_SIZE = 0x610


def compact_tile(raw):
    out=bytearray(32)
    for y in range(8):
        for x,sx in enumerate((1,3,4,6)):
            v=(raw[y*4+sx//2]>>(4*(sx%2)))&15
            out[y*4+x//2] |= v << (4*(x%2))
    return bytes(out)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parent = (ROOT / 'SD Gundam GGeneration Advance (Korean).gba').read_bytes()
    meta = json.loads((ROOT/'integrated/main_tip/ggen_advance_main_tip_manifest.json').read_text(encoding='utf-8'))
    assert sha(parent) == meta['sha256']
    assert parent[0xd7a8:0xd7b0] == bytes.fromhex('0e20009003a85346')
    assert not any(parent[CAVE:CAVE+64])
    assert not any(parent[ICON_CLONE:ICON_CLONE+ICON_SIZE])
    assert struct.unpack_from('<I',parent,0x11198)[0] == 0x08000000+ICON_SOURCE
    t = _Thumb(0x08000000+CAVE)
    t.h(0x4650)  # mov r0, sl (X << 16)
    t.h(0x0C00)  # lsrs r0, r0, #16
    t.h(0x2830)  # cmp r0, #48
    t.b('narrow', 1)  # bne: preserve all other callers
    t.h(0x200F)
    t.b('store')
    t.label('narrow')
    t.h(0x200E)
    t.label('store')
    t.h(0x9000)  # str r0, [sp]
    t.h(0xA803)  # add r0, sp, #12
    t.h(0x4653)  # mov r3, sl
    t.ldr_pc(1, 'return')  # r1 is overwritten immediately on return
    t.h(0x4708)
    t.align4()
    t.word('return', 0x0800D7B1)
    code = t.build()
    candidate = bytearray(parent)
    candidate[CAVE:CAVE+len(code)] = code
    candidate[0xd7a8:0xd7b0] = struct.pack('<HHI', 0x4800, 0x4700, 0x08000001+CAVE)
    icon=bytearray(parent[ICON_SOURCE:ICON_SOURCE+ICON_SIZE])
    assert struct.unpack_from('<II',icon,8)==(0x390,0x5f0)
    frames=[]
    for i in range(14):
        entry=0x30+4*i
        frame=entry+struct.unpack_from('<I',icon,entry)[0]
        count=struct.unpack_from('<H',icon,frame+6)[0]
        assert count in (1,2)
        for j in range(count):
            pos=frame+0x10+8*j+2
            attr=struct.unpack_from('<H',icon,pos)[0]
            assert attr&511==503  # -9, base X=232 -> 223
            struct.pack_into('<H',icon,pos,(attr&~511)|508)  # -4 -> 228
        frames.append({'frame':i,'pieces':count,'visible_x':[228,231]})
    for off in range(0x390,0x5f0,32):icon[off:off+32]=compact_tile(icon[off:off+32])
    candidate[ICON_CLONE:ICON_CLONE+ICON_SIZE]=icon
    struct.pack_into('<I',candidate,0x11198,0x08000000+ICON_CLONE)
    diff = [i for i,(a,b) in enumerate(zip(parent,candidate)) if a != b]
    allowed=set(range(0xd7a8,0xd7b0)) | set(range(CAVE,CAVE+len(code))) | set(range(ICON_CLONE,ICON_CLONE+ICON_SIZE)) | set(range(0x11198,0x1119c))
    assert set(diff) <= allowed
    assert candidate[ICON_SOURCE:ICON_SOURCE+ICON_SIZE]==parent[ICON_SOURCE:ICON_SOURCE+ICON_SIZE]
    assert candidate[0xf00000:0xfc0000] == parent[0xf00000:0xfc0000]
    OUT.mkdir(parents=True,exist_ok=True)
    ROM.write_bytes(candidate)
    shutil.copy2(ROOT/'SD Gundam GGeneration Advance (Korean).sav', ROM.with_suffix('.sav'))
    manifest = {'kind':'instant_dialogue_15_guarded','parent':{'sha256':sha(parent)},
                'output':{'path':str(ROM.relative_to(ROOT)), 'size':len(candidate),'sha256':sha(candidate)},
                'patch':{'site':'0x0800D7A8','cave':hex(0x08000000+CAVE),'code_hex':code.hex(),
                         'changed_bytes':len(diff),'x48_limit':15,'other_x_limit':14,
                         'wait_icon_private_clone':hex(0x08000000+ICON_CLONE),
                         'wait_icon_frames':frames,'original_icon_resource_preserved':True},
                'verification':{'result':'PENDING','static_diff':'PASS'}}
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    dis=Cs(CS_ARCH_ARM,CS_MODE_THUMB)
    (OUT/'hook.txt').write_text('\n'.join(f'{i.address:08X} {i.mnemonic} {i.op_str}' for i in dis.disasm(code,0x08000000+CAVE)),encoding='utf-8')
    print(json.dumps(manifest,indent=2))


if __name__ == '__main__':main()
