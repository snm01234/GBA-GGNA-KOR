"""Cover direct waits in list redraw and fade-in; retain pre-wait success."""
from pathlib import Path
import sys
import json
import struct
import hashlib
sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_ggen_advance_owned_count_ab_candidates_20260903 as asm
import build_ggen_advance_sort_popup_state6_candidate_20260903 as sort
from ggen_advance_project_paths import ADVANCE_ROOT, advance_relative

ROOT = ADVANCE_ROOT
PARENT = ROOT / 'outputs/20260905_ggen_advance_owned_sort_pre_wait/ggen_advance_owned_sort_pre_wait_candidate_20260905.gba'
STEM = 'ggen_advance_owned_sort_direct_wait_candidate_20260905'
OUT = ROOT / 'outputs/20260905_ggen_advance_owned_sort_direct_wait'
PURE_SORT = 0x080C5C00
WRAPPER = 0x080C5E00
PURE_OWNED = 0x09F20240

def gate(ok, text):
    if not ok:
        raise SystemExit(text)

def sha(b):
    return hashlib.sha256(b).hexdigest()

def main():
    parent = PARENT.read_bytes()
    gate(sha(parent) == '3f05793cb1a32c940c0889c11bd7b5dfaef02a5127b3ad0e95b06ff4b084a442', 'parent drift')
    # Original sort stub is internally PC-relative; retain literals, table
    # pointers, gate and return, remove its three frame-operation calls.
    pure = bytearray(sort.STUB)
    pure[2:0x14] = bytes.fromhex('c046') * 9
    gate(len(pure) < WRAPPER - PURE_SORT, 'pure sort overlaps wrapper')
    t = asm.Thumb(WRAPPER)
    t.h(0xB500)
    t.h(0xB4FF)
    t.ldr_pc(3, 'sort')
    t.bl_abs(WRAPPER + 0x18)
    t.ldr_pc(3, 'owned')
    t.bl_abs(WRAPPER + 0x18)
    t.h(0xBCFF)
    t.bl_abs(0x08001928)
    t.h(0xBD00)
    t.h(0x4718)
    t.align4()
    t.word('sort', PURE_SORT | 1)
    t.word('owned', PURE_OWNED | 1)
    wrapper = t.build()
    gate(wrapper[0x18:0x1a] == bytes.fromhex('1847'), 'thunk offset drift')
    child = bytearray(parent)
    edits = []
    def put(address, payload):
        off = address - 0x08000000
        child[off:off + len(payload)] = payload
        edits.append((off, len(payload)))
    for address, blob in [(PURE_SORT, pure), (WRAPPER, wrapper)]:
        off = address - 0x08000000
        gate(not any(parent[off:off + len(blob)]), 'cave not empty')
        put(address, blob)
    for site in [0x080771E6, 0x08012788]:
        gate(asm.thumb_bl_target(parent, site) == 0x08001928, 'direct wait drift')
        put(site, asm.encode_thumb_bl(site, WRAPPER))
        gate(asm.thumb_bl_target(child, site) == WRAPPER, 'hook target drift')
    allowed = {i for off, size in edits for i in range(off, off + size)}
    diff = [i for i, (a, b) in enumerate(zip(parent, child)) if a != b]
    gate(set(diff) <= allowed, 'diff escape')
    gate(child[sort.STUB_FILE:sort.ALLOCATION_END] == parent[sort.STUB_FILE:sort.ALLOCATION_END], 'successful pre-wait patch changed')
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    dis = list(md.disasm(wrapper[:0x1a], WRAPPER))
    targets = [int(i.op_str.lstrip('#'),16) for i in dis if i.mnemonic == 'bl']
    gate(targets == [WRAPPER + 0x18, WRAPPER + 0x18, 0x08001928], 'wrapper call ordering drift')
    OUT.mkdir(parents=True, exist_ok=True)
    rom, sav = OUT / (STEM + '.gba'), OUT / (STEM + '.sav')
    save_data = PARENT.with_suffix('.sav').read_bytes()
    gate(not sav.exists() or sav.read_bytes() == save_data, 'output SAV has user changes')
    rom.write_bytes(child)
    sav.write_bytes(save_data)
    gate(rom.read_bytes() == child and sav.read_bytes() == save_data, 'readback failed')
    report = dict(kind=STEM, parent_sha256=sha(parent), output=advance_relative(rom), sha256=sha(child),
        sav=advance_relative(sav), static='PASS', runtime='PENDING', changed_bytes=len(diff),
        hooks={'0x080771E6':'list redraw direct wait', '0x08012788':'fade-in direct wait'},
        order=['pure sort correction', 'pure owned correction', 'original 1928 once'],
        preserved='pre-wait common frame patch, all translated payloads and actual controller hooks',
        notes='Fade-in helper is shared; corrections retain existing screen gates. Direct wait bypass is proven statically, but disappearance of the remaining flashes requires runtime confirmation.',
        disassembly=[f'{i.address:08X}: {i.mnemonic} {i.op_str}' for i in dis])
    (ROOT / 'analysis' / (STEM + '.json')).write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))

if __name__ == '__main__':
    main()
