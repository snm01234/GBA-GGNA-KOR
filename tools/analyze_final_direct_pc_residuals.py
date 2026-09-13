#!/usr/bin/env python3
import argparse, hashlib, json, struct
from collections import defaultdict
from pathlib import Path

EXPECTED_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"
BASE = 0x08000000
DRAW = 0x08000CA0

CONFIRM = {
    0x08011FD8: 0x081BE7BE,
    0x08011FE6: 0x081BE7C7,
    0x08011FF4: 0x081BE7CA,
}
ID_FALLBACK = 0x081BE74E
EMPTY_SELECTION = 0x081BE7A3
SHARED_LIST_HEADING = 0x081BEA75
ORPHAN_ROWS = {
    0x08026798: 0x081BEA51,
    0x080267A6: 0x081BEA5E,
    0x080267B4: 0x081BEA67,
    0x080267C2: 0x081BEA75,
    0x080267D0: 0x081BEB6F,
    0x080267DE: 0x081BEBC5,
    0x080267EC: 0x081BEE68,
    0x080267FA: 0x081BEE6F,
    0x08026808: 0x081BEE7A,
}
ORPHAN_ONLY = set(ORPHAN_ROWS.values()) - {SHARED_LIST_HEADING}


def u16(rom, addr): return struct.unpack_from('<H', rom, addr - BASE)[0]
def u32(rom, addr): return struct.unpack_from('<I', rom, addr - BASE)[0]


def decode_bl(rom, addr):
    h1, h2 = u16(rom, addr), u16(rom, addr + 2)
    assert h1 & 0xF800 == 0xF000 and h2 & 0xF800 == 0xF800, (hex(addr), hex(h1), hex(h2))
    hi, lo = h1 & 0x7FF, h2 & 0x7FF
    rel = (hi << 12) | (lo << 1)
    if hi & 0x400: rel -= 1 << 23
    return (addr + 4 + rel) & 0xFFFFFFFF


def pc_ldr_r3_target(rom, call_addr):
    for a in range(call_addr - 2, call_addr - 14, -2):
        h = u16(rom, a)
        if h & 0xF800 == 0x4800 and ((h >> 8) & 7) == 3:
            lit = ((a + 4) & ~3) + ((h & 0xFF) << 2)
            return u32(rom, lit)
    raise AssertionError(f'no r3 literal before {call_addr:#x}')


def scan_bl_hits(rom, target):
    hits = []
    for off in range(0, len(rom) - 4, 2):
        h1, h2 = struct.unpack_from('<HH', rom, off)
        if h1 & 0xF800 != 0xF000 or h2 & 0xF800 != 0xF800: continue
        hi, lo = h1 & 0x7FF, h2 & 0x7FF
        rel = (hi << 12) | (lo << 1)
        if hi & 0x400: rel -= 1 << 23
        if ((BASE + off + 4 + rel) & 0xFFFFFFFF) == target:
            hits.append(BASE + off)
    return hits


def scan_b16_hits(rom, target):
    hits = []
    for off in range(0, len(rom) - 2, 2):
        h = struct.unpack_from('<H', rom, off)[0]
        if h & 0xF800 != 0xE000: continue
        imm = h & 0x7FF
        rel = imm << 1
        if imm & 0x400: rel -= 1 << 12
        if BASE + off + 4 + rel == target:
            hits.append(BASE + off)
    return hits


def direct_pc_calls(rom):
    out = defaultdict(list)
    for off in range(0, len(rom) - 4, 2):
        addr = BASE + off
        h1, h2 = struct.unpack_from('<HH', rom, off)
        if h1 & 0xF800 != 0xF000 or h2 & 0xF800 != 0xF800: continue
        try: target = decode_bl(rom, addr)
        except AssertionError: continue
        if target != DRAW: continue
        try: text = pc_ldr_r3_target(rom, addr)
        except AssertionError: continue
        if BASE <= text < BASE + len(rom): out[text].append(addr)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('rom')
    args = ap.parse_args()
    rom = Path(args.rom).read_bytes()
    sha = hashlib.sha256(rom).hexdigest()
    assert sha == EXPECTED_SHA256, sha
    calls = direct_pc_calls(rom)

    # A three-string dialog: heading plus two vertically stacked choices.
    assert decode_bl(rom, 0x08012054) == 0x08011F6C
    coords = [(0x48,0x30),(0x68,0x48),(0x68,0x60)]
    for (c,t),(x,y) in zip(CONFIRM.items(), coords):
        assert decode_bl(rom,c) == DRAW and pc_ldr_r3_target(rom,c) == t
        # movs r1,#x / movs r2,#y immediately precede draw sequence.
        assert u16(rom,c-4) == 0x2100 | x
        assert u16(rom,c-2) == 0x2200 | y
    # Parent state 0 invokes the dialog; state transition then uses menu-selection helpers.
    assert u16(rom,0x08012040) == 0x2D00  # cmp r5,#0
    assert decode_bl(rom,0x08012074) == 0x08012B04

    # ID-command row fallback: both sites are in rows that first query 7974/7994/79B8 accessors.
    for site in (0x0801F3EA,0x0806C454):
        assert decode_bl(rom,site) == DRAW and pc_ldr_r3_target(rom,site) == ID_FALLBACK
    for site in (0x0801F370,0x0806C3D0): assert decode_bl(rom,site) == 0x08007974
    for site in (0x0801F390,0x0806C3F2): assert decode_bl(rom,site) == 0x08007994
    for site in (0x0801F3AA,0x0806C40C): assert decode_bl(rom,site) == 0x080079B8

    # Selector empty-state/fallback message: only drawn when 0x8077ED4 returns zero.
    assert decode_bl(rom,0x08079EFE) == 0x08077ED4
    assert u16(rom,0x08079F04) == 0x2800  # cmp r0,#0
    assert (u16(rom,0x08079F06) & 0xFF00) == 0xD100  # bne skips message path
    assert decode_bl(rom,0x08079F2A) == DRAW
    assert pc_ldr_r3_target(rom,0x08079F2A) == EMPTY_SELECTION

    # Shared heading is used before row loops in two live list renderers, plus the orphan-like renderer.
    heading_sites = sorted(calls[SHARED_LIST_HEADING])
    assert heading_sites == [0x080267C2,0x0805F846,0x08060FEE], heading_sites
    assert decode_bl(rom,0x0805F846) == DRAW and decode_bl(rom,0x08060FEE) == DRAW
    # Following code iterates rows (5F854 dynamic pointer; 61000 struct8 pointer).
    assert u16(rom,0x0805F856) == 0x682B  # ldr r3,[r5]
    assert u16(rom,0x08061000) == 0x683B  # ldr r3,[r7]

    # 0x08026754 renders exactly nine fixed rows and a generic cursor marker afterwards.
    for c,t in ORPHAN_ROWS.items():
        assert decode_bl(rom,c) == DRAW and pc_ldr_r3_target(rom,c) == t
    # No ordinary inbound static edge to the renderer: no BL, no short B, no absolute ARM/Thumb pointer.
    assert not scan_bl_hits(rom,0x08026754)
    assert not scan_b16_hits(rom,0x08026754)
    assert rom.find(struct.pack('<I',0x08026754)) < 0
    assert rom.find(struct.pack('<I',0x08026755)) < 0
    # Eight identities occur only in this renderer; BEA75 is separately live via the two list renderers above.
    for t in ORPHAN_ONLY:
        assert calls[t] == [next(c for c,v in ORPHAN_ROWS.items() if v == t)], (hex(t), calls[t])

    promoted = 3 + 1 + 1 + 1 + len(ORPHAN_ONLY)
    assert promoted == 14
    result = {
        'schema_version': 1,
        'rom_sha256': sha,
        'semantic_review_status': 'reviewed',
        'clusters': {
            'two_choice_confirmation_dialog_text': {
                'records': 3,
                'targets': [f'0x{x:08X}' for x in CONFIRM.values()],
                'renderer': '0x08011F6C',
                'parent_state_machine': '0x08012028'
            },
            'id_command_row_fallback': {
                'records': 1,
                'target': f'0x{ID_FALLBACK:08X}',
                'draw_calls': ['0x0801F3EA','0x0806C454']
            },
            'selector_empty_state_message': {
                'records': 1,
                'target': f'0x{EMPTY_SELECTION:08X}',
                'draw_call': '0x08079F2A'
            },
            'shared_list_heading': {
                'records': 1,
                'target': f'0x{SHARED_LIST_HEADING:08X}',
                'live_draw_calls': ['0x0805F846','0x08060FEE'],
                'other_draw_call': '0x080267C2'
            },
            'statically_unreferenced_nine_row_menu_labels': {
                'records': 8,
                'renderer': '0x08026754',
                'targets': [f'0x{x:08X}' for x in sorted(ORPHAN_ONLY)],
                'inbound_static_edges': {'bl':0,'b16':0,'absolute_pointer':0},
                'note': 'No claim is made that arbitrary computed control flow is impossible; the static ROM has no ordinary inbound edge, and these eight targets have no other direct-PC consumer.'
            }
        },
        'promotion': {
            'unique_records_promoted': promoted,
            'direct_pc_records_remaining_partial': 0
        },
        'conclusion': 'All final direct-PC residual identities now have a closed static role or a documented statically-unreferenced renderer classification. No direct-PC semantic record remains partial.'
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == '__main__': main()
