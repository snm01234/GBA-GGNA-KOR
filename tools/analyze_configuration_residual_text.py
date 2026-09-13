#!/usr/bin/env python3
import argparse, hashlib, json, struct
from pathlib import Path

EXPECTED_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"
BASE = 0x08000000
DRAW = 0x08000CA0

STATIC_NEW = {
    0x08060594: 0x081BEB0E,
    0x080605CC: 0x081BEB27,
    0x080605E8: 0x081BEB3C,
    0x080605F6: 0x081BEB46,
}
STATUS_CALL = 0x08060A36
STATUS_TARGET = 0x081BEB6C


def u16(rom, addr): return struct.unpack_from('<H', rom, addr - BASE)[0]
def u32(rom, addr): return struct.unpack_from('<I', rom, addr - BASE)[0]


def decode_bl(rom, addr):
    h1, h2 = u16(rom, addr), u16(rom, addr + 2)
    assert h1 & 0xF800 == 0xF000 and h2 & 0xF800 == 0xF800, (hex(addr), hex(h1), hex(h2))
    hi = h1 & 0x07FF
    lo = h2 & 0x07FF
    off = (hi << 12) | (lo << 1)
    if hi & 0x400:
        off -= 1 << 23
    return ((addr + 4 + off) & 0xFFFFFFFF)


def pc_ldr_r3_target(rom, call_addr):
    # direct_pc_literal family rule: nearest valid LDR r3,[pc,#imm] in preceding 12 bytes.
    for a in range(call_addr - 2, call_addr - 14, -2):
        h = u16(rom, a)
        if h & 0xF800 == 0x4800 and ((h >> 8) & 7) == 3:
            lit = ((a + 4) & ~3) + ((h & 0xFF) << 2)
            return u32(rom, lit)
    raise AssertionError(f"no pc-relative r3 writer before {call_addr:#x}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('rom')
    args = ap.parse_args()
    rom = Path(args.rom).read_bytes()
    sha = hashlib.sha256(rom).hexdigest()
    assert sha == EXPECTED_SHA256, sha

    # 0x08060544 is a 9-row submenu renderer. 0x08060784 redraws it after selection movement.
    assert decode_bl(rom, 0x08060784) == 0x08060544
    all_rows = [0x08060586,0x08060594,0x080605A2,0x080605B0,0x080605BE,
                0x080605CC,0x080605DA,0x080605E8,0x080605F6]
    row_targets = []
    for c in all_rows:
        assert decode_bl(rom, c) == DRAW
        row_targets.append(pc_ldr_r3_target(rom, c))
    for c, t in STATIC_NEW.items():
        assert pc_ldr_r3_target(rom, c) == t

    # 0x080609B0 draws character names and conditionally adds a single icon at x=0x68.
    # The icon draw is guarded by a per-character bit test at 0x08060A22-0x08060A2A.
    assert decode_bl(rom, STATUS_CALL) == DRAW
    assert pc_ldr_r3_target(rom, STATUS_CALL) == STATUS_TARGET
    assert u16(rom, 0x08060A22) == 0x8801  # ldrh r1,[r0]
    assert u16(rom, 0x08060A28) == 0x2800  # cmp r0,#0
    assert u16(rom, 0x08060A2A) & 0xFF00 == 0xD000  # beq skips marker draw
    assert u16(rom, 0x08060A30) == 0x2168  # x = 0x68

    out = {
        'schema_version': 1,
        'rom_sha256': sha,
        'semantic_review_status': 'reviewed',
        'clusters': {
            'unit_configuration_submenu_label': {
                'new_records': 4,
                'targets': [f'0x{x:08X}' for x in STATIC_NEW.values()],
                'renderer': '0x08060544',
                'redraw_call': '0x08060784',
                'physical_rows': 9,
                'all_row_targets': [f'0x{x:08X}' for x in row_targets],
                'reason': 'All four residual identities are fixed rows of the same 9-row submenu inside the already-closed unit configuration flow.'
            },
            'character_list_state_marker': {
                'new_records': 1,
                'target': f'0x{STATUS_TARGET:08X}',
                'renderer': '0x080609B0',
                'draw_call': f'0x{STATUS_CALL:08X}',
                'reason': 'Character names are drawn row-by-row; a per-character bit test conditionally draws this one-glyph status marker at the right side of the row.'
            }
        },
        'promotion': {
            'unique_records_promoted': 5,
            'direct_pc_records_remaining_partial': 14
        },
        'conclusion': 'The five configuration-adjacent residual direct-PC identities have closed UI roles: four fixed submenu labels and one conditional character-list status marker.'
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
