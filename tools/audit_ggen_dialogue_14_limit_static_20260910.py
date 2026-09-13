"""Read-only ROM/state audit: immediate dialogue draws 14, gradual draws length.

No screenshots, emulator execution, ROM writes, or state writes are used.
Outputs are confined to analysis/dialogue_14_limit_static_20260910.
"""
from pathlib import Path
import hashlib
import json
import struct
import sys

from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
from analyze_ggen_advance_unit_list_sprite_state_20260830 import parse_png_state
from patch_ggen_advance_apsaras_zentetsu_20260908 import find_lookups
from patch_ggen_advance_intermission_text_consumers_20260904 import payload_at
from patch_ggen_advance_dialogue_idcmd_fit_20260909 import read_tokens

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'analysis/dialogue_14_limit_static_20260910'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def u16(data, off):
    return struct.unpack_from('<H', data, off)[0]


def u32(data, off):
    return struct.unpack_from('<I', data, off)[0]


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    ko = (ROOT / 'SD Gundam GGeneration Advance (Korean).gba').read_bytes()
    jp = (ROOT / 'SD Gundam GGeneration Advance (Japan).gba').read_bytes()
    rows = json.loads((ROOT / 'integrated/translation/ggen_advance_translation_merged.json').read_text(encoding='utf-8'))['records']
    oldrows = json.loads((ROOT / 'analysis/ggen_advance_translation_merged_20260909_creuset_names.json').read_text(encoding='utf-8'))['records']
    oldpath = ROOT / 'integrated/main_tip/backups/20260910T105844Z_user_requested_aina_overflow_honorific_20260910/SD Gundam GGeneration Advance (Korean).gba'
    old = oldpath.read_bytes()
    assert ko[0xd7a8:0xd7ac] == jp[0xd7a8:0xd7ac] == bytes.fromhex('0e200090')
    assert u32(ko, 0xd2ec) == 0x0200d038
    assert ko[0xd2d0:0xd82a] == jp[0xd2d0:0xd82a]
    assert ko[0x648:0x708] == jp[0x648:0x708]
    ids = ['00F7FAD4', '00F7F766', '00F7F7C3', '00F7F875']
    states = []
    for n, suffix in enumerate(ids, 1):
        path = ROOT / f'SD Gundam GGeneration Advance (Korean).ss{n}'
        statebytes = path.read_bytes()
        s, _ = parse_png_state(path)
        pc = u32(s, 0x21000 + 0xa0c0)
        flags = u32(s, 0x21000 + 0xa0cc)
        entry = {'state': path.name, 'sha256': sha(statebytes), 'script_next': hex(pc),
                 'delay_0200D038': s[0x21000 + 0xd038], 'dialogue_flags': hex(flags),
                 'x_argument': 60 if flags & 4 else 48, 'versions': []}
        assert entry['delay_0200D038'] == 0
        for label, rom, records in [('current', ko, rows), ('before_aina_fix', old, oldrows)]:
            row = next(r for r in records if r['record_id'] == 'GGA-MAPSCRIPT-' + suffix)
            cursor = int(row['target_file_offset'], 16)
            lines = []
            for seg, text in zip(row['segments'], row['translation_segments']):
                raw = bytes.fromhex(seg['raw_hex'])
                lookups = find_lookups(rom, 0x08000000 + cursor, 0x08000000 + cursor + len(raw) - 1)
                assert lookups and len(set(hit[1] for hit in lookups)) == 1
                ptr = lookups[0][1]
                payload = payload_at(rom, ptr)
                tokens = read_tokens(payload)
                assert all(len(t) == 1 or t[0] < 0xf0 for t in tokens)
                slots = [((int.from_bytes(t, 'big') + 0x20e0) & 0xffff) if len(t) == 2 else t[0] for t in tokens]
                assert len(tokens) == len(text)
                matches = []
                if len(slots) >= 14:
                    needle = struct.pack('<14H', *slots[:14])
                    pos = s.find(needle, 0x19000, 0x21000)
                    while pos >= 0:
                        ctx = pos - 0x1a
                        matches.append({'context_address': hex(0x03000000 + ctx - 0x19000),
                                        'draw_count_at_plus_18': u16(s, ctx + 0x18),
                                        'buffer_slots': [hex(u16(s, pos + 2*i)) for i in range(len(slots))],
                                        'full_decoded_slots_match': s[pos:pos+2*len(slots)] == struct.pack('<'+'H'*len(slots), *slots)})
                        pos = s.find(needle, pos+2, 0x21000)
                lines.append({'text': text, 'characters': len(text), 'tokens': len(tokens),
                              'payload_address': hex(ptr), 'payload_hex': payload.hex(),
                              'immediate_visible_prefix': text[:14], 'immediate_omitted_suffix': text[14:],
                              'iwram_matches': matches})
                cursor += len(raw)
            assert cursor + 0x08000000 == pc
            entry['versions'].append({'version': label, 'record_id': row['record_id'], 'lines': lines})
        states.append(entry)
        saved_line = entry['versions'][0 if n == 1 else 1]['lines'][1]
        assert len(saved_line['text']) == 15
        assert any(m['draw_count_at_plus_18'] == 14 and m['full_decoded_slots_match']
                   for m in saved_line['iwram_matches'])
    ss1line = states[0]['versions'][0]['lines'][1]
    assert ss1line['characters'] == 15
    assert any(m['draw_count_at_plus_18'] == 14 and m['full_decoded_slots_match'] for m in ss1line['iwram_matches'])
    report = {'result': 'PASS', 'method': 'ROM disassembly and serialized RAM, no image inference',
              'rom_sha256': {'current': sha(ko), 'japan': sha(jp), 'before_aina_fix': sha(old)},
              'original_code_unchanged': True, 'states': states,
              'limits': {'instant': 14, 'gradual': 'decoded string length / reveal budget'},
              'important': 'Both rows share the immediate cap. Old states retain historical RAM/VRAM. Current ss1 is a different record from the earlier Aina ss1.'}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'evidence.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    dis = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    ranges = [(0xd2d0,0xd2f0),(0xd3ca,0xd3e2),(0xd622,0xd63c),
              (0xd4c8,0xd51a),(0xd538,0xd598),(0xd772,0xd786),(0xd798,0xd7e0),
              (0x648,0x6bc),(0x6c0,0x708),(0x1200,0x1230),(0x1238,0x126e),
              (0x211c0,0x211f6),(0x212a0,0x212cc)]
    lines = []
    for a,b in ranges:
        lines.append(f'\nROM offset {a:#x}..{b:#x}')
        for ins in dis.disasm(ko[a:b], 0x08000000+a):
            lines.append(f'{ins.address:08X}  {ins.bytes.hex():10} {ins.mnemonic} {ins.op_str}')
    (OUT / 'disassembly.txt').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    for entry in states:
        print(entry['state'], 'delay=', entry['delay_0200D038'])
        for version in entry['versions']:
            print(version['version'], [(l['text'],l['characters'],l['immediate_omitted_suffix'],len(l['iwram_matches'])) for l in version['lines']])
    print('PASS:', OUT)


if __name__ == '__main__':
    main()
