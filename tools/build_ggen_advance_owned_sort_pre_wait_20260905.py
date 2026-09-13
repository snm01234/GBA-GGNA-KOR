"""Move gated sort/owned corrections before the common frame wait.

Starts from the user-tested supply candidate (76685...), retains its actual
controller hooks, and changes the common sort frame stub's ordering. The pure
owned helper is a relocated copy with its nested frame call removed: it must
never recurse into 63194. Original palettes, maps and Korean payloads remain.
"""
from pathlib import Path
import hashlib
import json
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_ggen_advance_owned_count_ab_candidates_20260903 as asm
import build_ggen_advance_owned_count_live_overlay_candidate_20260904 as owned
import build_ggen_advance_sort_popup_state6_candidate_20260903 as sort
from ggen_advance_project_paths import ADVANCE_ROOT, MAIN_TIP_ROM, advance_relative

PARENT = ADVANCE_ROOT / 'outputs/20260905_ggen_advance_owned_count_actual_paths/ggen_advance_owned_count_actual_paths_candidate_20260905.gba'
EXPECTED = '76685ae91ce90ac1c90703e0892b1624c10f0763ff70948e42bcd49e05b9c0f0'
MAIN_HASH = 'f4ec36f115ea03af0b8f40f84686a5f6f5b2b5526e5d857b84703a3bcc8c3db4'
OUT = ADVANCE_ROOT / 'outputs/20260905_ggen_advance_owned_sort_pre_wait'
STEM = 'ggen_advance_owned_sort_pre_wait_candidate_20260905'
TAIL = 0x09F20200
PURE = 0x09F20240
BASE = 0x08000000


def sha(data):
    return hashlib.sha256(data).hexdigest()


def gate(ok, message):
    if not ok:
        raise SystemExit(message)


def main():
    parent = PARENT.read_bytes()
    main_rom = MAIN_TIP_ROM.read_bytes()
    gate(sha(parent) == EXPECTED and sha(main_rom) == MAIN_HASH, 'parent/main hash drift')
    gate(parent[sort.STUB_FILE:sort.STUB_FILE + len(sort.STUB)] == sort.STUB, 'sort stub drift')
    original_owned = owned.build_stub_clean()
    gate(parent[owned.STUB_FILE:owned.STUB_FILE + len(original_owned)] == original_owned, 'owned stub drift')
    gate(not any(parent[TAIL - BASE:0x1F20400]), 'new helper allocation not empty')
    for site in (0x0806E0AE, 0x0806E6F0, 0x0806EB3E):
        gate(asm.thumb_bl_target(parent, site) == owned.STUB_ADDR, 'tested controller hook missing')

    # All branches and PC-relative literals in this helper are internal. Both
    # origins are word aligned. Removing the only BL leaves it relocatable.
    pure = bytearray(original_owned)
    gate(asm.thumb_bl_target(parent, owned.STUB_ADDR + 2) == 0x08063194, 'nested frame call drift')
    pure[2:6] = bytes.fromhex('c046c046')

    # On entry the original caller LR remains stacked by the sort frame stub.
    # Preserve r0-r7 around the pure overlay, call the original wait exactly
    # once, then use the original pop-r0/bx-r0 return convention.
    t = asm.Thumb(TAIL)
    t.h(0xB4FF)
    t.ldr_pc(3, 'pure')
    t.bl_abs(TAIL + 0x18)
    t.h(0xBCFF)
    t.ldr_pc(3, 'wait')
    t.bl_abs(TAIL + 0x18)
    t.h(0xBC01)
    t.h(0x4700)
    t.h(0x46C0)
    t.h(0x46C0)
    t.h(0x4718)  # +0x18 bx r3, ARMv4T interworking call thunk
    t.align4()
    t.word('pure', PURE | 1)
    t.word('wait', 0x08001929)
    tail = t.build()
    gate(tail[0x18:0x1A] == bytes.fromhex('1847'), 'call thunk offset drift')
    gate(len(tail) <= PURE - TAIL, 'tail overlaps pure helper')

    child = bytearray(parent)
    edits = []
    def put(off, data, reason):
        edits.append(dict(offset=f'0x{off:08X}', bytes=len(data), reason=reason))
        child[off:off + len(data)] = data

    # Remove the old third call (1928). Keep its harmless LDR and old literal.
    put(sort.STUB_FILE + 0x10, bytes.fromhex('c046c046'), 'defer frame wait until both corrections complete')
    delta = (TAIL - (0x09F200CC + 4)) // 2
    gate(-1024 <= delta < 1024, 'tail B out of range')
    put(sort.STUB_FILE + 0xCC, struct.pack('<HH', 0xE000 | (delta & 0x7FF), 0x46C0), 'all sort gate exits reach owned correction and wait')
    put(TAIL - BASE, tail, 'owned correction then one original wait')
    put(PURE - BASE, pure, 'pure gated owned copy, no nested frame call')
    allowed = set()
    for edit in edits:
        off = int(edit['offset'], 16)
        allowed.update(range(off, off + edit['bytes']))
    diff = [i for i, (a, b) in enumerate(zip(parent, child)) if a != b]
    gate(set(diff) <= allowed, 'diff escapes patch allocation')
    gate(child[sort.TABLE_FILE:sort.ALLOCATION_END] == parent[sort.TABLE_FILE:sort.ALLOCATION_END], 'sort payload changed')
    gate(child[owned.STUB_FILE:owned.PAYLOAD_FILE + 320] == parent[owned.STUB_FILE:owned.PAYLOAD_FILE + 320], 'approved owned payload/stub changed')
    # Disassemble executable regions; verify interworking and absence of
    # frame recursion independently of the byte assembler.
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    instructions = list(md.disasm(tail[:0x1A], TAIL))
    gate(sum(i.mnemonic == 'bl' for i in instructions) == 2, 'tail call count drift')
    gate(all(int(i.op_str.lstrip('#'), 16) == TAIL + 0x18 for i in instructions if i.mnemonic == 'bl'), 'tail call target drift')
    gate(not any(i.mnemonic == 'bl' for i in md.disasm(pure[:0x60], PURE)), 'pure helper recurses')
    OUT.mkdir(parents=True, exist_ok=True)
    rom_path, sav_path = OUT / (STEM + '.gba'), OUT / (STEM + '.sav')
    sav = PARENT.with_suffix('.sav').read_bytes()
    gate(not sav_path.exists() or sav_path.read_bytes() == sav, 'existing output SAV changed by user')
    rom_path.write_bytes(child)
    sav_path.write_bytes(sav)
    gate(rom_path.read_bytes() == child and sav_path.read_bytes() == sav, 'readback mismatch')
    gate(MAIN_TIP_ROM.read_bytes() == main_rom, 'canonical main changed')
    report = dict(kind=STEM, status='candidate_not_promoted',
        parent=dict(path=advance_relative(PARENT), sha256=sha(parent), supply_stable_label='user PASS'),
        output=dict(path=advance_relative(rom_path), sha256=sha(child), sav=advance_relative(sav_path)),
        edits=edits, changed_bytes_vs_tested_candidate=len(diff),
        order_before=['1322C', '13544', '1928 / VBlankIntrWait', 'sort correction', 'return', 'owned correction on hooked controllers'],
        order_after=['1322C', '13544', 'sort correction', 'owned correction', '1928 / VBlankIntrWait', 'return'],
        tail_disassembly=[f'{i.address:08X}: {i.mnemonic} {i.op_str}' for i in instructions],
        verification=dict(static='PASS', runtime='PENDING', payloads_unchanged=True, no_recursive_frame_call=True,
                          frame_wait_calls_per_common_frame=1, canonical_unchanged=True),
        limitation='First-visible-frame timing still requires emulator measurement; later IRQ writes or gates not yet satisfied can require further tracing.',
        checkpoints=['Fresh boot from companion SAV; supply and disposal entry: stable 소유수 and no Japanese flash.',
                     'Sort: move repeatedly between level/name/deployed and ascending/descending; inspect normal and focus tiles.',
                     'Check menus outside these screens and absence of frame/input regressions.'])
    (ADVANCE_ROOT / 'analysis' / (STEM + '.json')).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
