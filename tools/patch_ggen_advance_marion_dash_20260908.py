#!/usr/bin/env python3
"""Fix Marion's two dash glyphs without changing the live 값 glyph or saves."""
import json
import struct
from pathlib import Path

from PIL import Image
import build_ggen_advance_ko_poc as fontops
import build_ggen_advance_unified_rom_poc as unified
import ggen_advance_painted_glyph_identity as glyph
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
from ggen_advance_project_paths import MAIN_TIP_ROM, MAIN_TIP_MANIFEST, ORIGINAL_ROM, TRANSLATION_MERGED_JSON, advance_relative
from patch_ggen_advance_map_script_inline_poc import load_identified_12x12, encode_map_korean_line
from patch_ggen_advance_intermission_text_consumers_20260904 import gate, sha256, payload_at

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs/20260908_ggen_advance_marion_dash'
ROM = OUT / 'ggen_advance_marion_dash_candidate_20260908.gba'
MANIFEST = OUT / 'manifest.json'
OLD, NEW = 0x00E5, 0x07B9


def main():
    current = MAIN_TIP_ROM.read_bytes()
    japan = ORIGINAL_ROM.read_bytes()
    meta = json.loads(MAIN_TIP_MANIFEST.read_text(encoding='utf-8'))
    gate(sha256(current) == meta['sha256'], 'main TIP identity drift')
    candidate = bytearray(current)
    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding='utf-8'))
    row = next(r for r in merged['records'] if r['record_id'] == 'GGA-MAPSCRIPT-00F54325')
    text = row['translation_ko']
    gate(text == '「――난폭한 사람은싫어……」', 'Marion translation drift')
    font = glyph.load_galmuri12()
    stride = fontops.FONT_12X12_STRIDE
    old_glyph = glyph.slot_raw(current, glyph.FONT12_RELOCATED, OLD, stride)
    gate(old_glyph == glyph.packed_12x12('값', font), 'expected dash/값 collision missing')
    live8, live12 = unified.collect_live_slots(japan, merged['records'])
    gate(NEW not in live8 | live12, 'destination has live original text consumers')
    gate(glyph.slot_raw(current, glyph.FONT12_RELOCATED, NEW, stride) ==
         glyph.slot_raw(japan, fontops.FONT_12X12_BASE, NEW, stride), 'destination already painted')
    dash = glyph.slot_raw(japan, fontops.FONT_12X12_BASE, OLD, stride)
    font_at = glyph.FONT12_RELOCATED + NEW * stride
    candidate[font_at:font_at + stride] = dash
    allowed = set(range(font_at, font_at + stride))

    recovered = glyph.recover_unique_12x12_slots(current, font, {c for c in text if '가' <= c <= '힣'})
    old_map = load_identified_12x12()
    old_map['―'] = OLD
    before, missing = encode_map_korean_line(text, recovered, old_map)
    gate(before is not None and not missing, 'old payload encoding failed')
    after, missing = encode_map_korean_line(text, recovered, load_identified_12x12())
    gate(after is not None and not missing and len(after) == len(before), 'new payload framing drift')
    encoded, missing = unified.encode_korean_text(text, recovered,
        verified_charmap=unified.load_verified_charmap(unified.CHARMAP_12X12_PATH), strict_punctuation=True)
    gate(encoded == after and not missing, 'map/cutin encoders disagree')

    cutin = struct.unpack_from('<I', current, 0x228604)[0]
    gate(current[cutin - 0x08000000:cutin - 0x08000000 + 6] == bytes.fromhex('00 05 75 00 06 CE'), 'cutin header drift')
    state_path = ROOT / 'SD Gundam GGeneration Advance (Korean).ss1'
    state, _ = statefmt.parse_png_state(state_path)
    gate(struct.pack('<I', cutin) in state, 'updated state does not reference Marion cutin')
    targets = {cutin + 6}
    key = struct.pack('<I', 0x08F54325)
    cursor = 0
    lookups = []
    while True:
        pos = current.find(key, cursor)
        if pos < 0:
            break
        cursor = pos + 1
        orig, neu, end = struct.unpack_from('<III', current, pos)
        if 0x09000000 <= neu < 0x0A000000 and end == 0x08F54334:
            targets.add(neu)
            lookups.append(hex(pos))
    gate(lookups, 'parallel map-script lookup missing')
    for address in sorted(targets):
        gate(payload_at(current, address) == before, f'live payload drift at {address:#x}')
        at = address - 0x08000000
        candidate[at:at + len(after)] = after
        allowed.update(range(at, at + len(after)))
    changes = {i for i, (a, b) in enumerate(zip(current, candidate)) if a != b}
    gate(changes <= allowed, 'unrelated ROM change')
    gate(glyph.slot_raw(candidate, glyph.FONT12_RELOCATED, OLD, stride) == old_glyph, '값 glyph changed')
    gate(glyph.slot_raw(candidate, glyph.FONT12_RELOCATED, NEW, stride) == dash, 'dash raster mismatch')
    gate(all(payload_at(candidate, a) == after for a in targets), 'payload verification failed')
    gate(candidate[0xF00000:0xFC0000] == current[0xF00000:0xFC0000], 'original script bank changed')

    OUT.mkdir(parents=True, exist_ok=True)
    ROM.write_bytes(candidate)
    # This is a static glyph preview from actual ROM bytes, not an emulator capture.
    preview = Image.new('L', (len(text) * 12, 30), 0)
    for line, (data, mapping) in enumerate(((current, old_map), (candidate, load_identified_12x12()))):
        for index, char in enumerate(text):
            slot = recovered.get(char, mapping.get(char))
            gate(slot is not None, f'preview slot missing for {char}')
            raw = glyph.slot_raw(data, glyph.FONT12_RELOCATED, slot, stride)
            preview.paste(fontops.unpack_12x12(raw), (index * 12, line * 16))
    preview.resize((preview.width * 3, preview.height * 3), Image.Resampling.NEAREST).save(OUT / 'glyph_before_after.png')
    report = {
        'kind': 'ggen_advance_marion_dash_20260908',
        'parent': {'path': advance_relative(MAIN_TIP_ROM), 'sha256': sha256(current)},
        'output': {'path': advance_relative(ROM), 'sha256': sha256(candidate), 'size': len(candidate)},
        'state': {'path': advance_relative(state_path), 'sha256': sha256(state_path.read_bytes()), 'cutin_pointer_present': hex(cutin)},
        'cause': 'Native dash token E005 uses slot 00E5 painted as 값; two dashes render 값값.',
        'fix': {'old_slot_preserved': hex(OLD), 'dash_copy_slot': hex(NEW), 'targets': [hex(a) for a in sorted(targets)], 'map_lookup_offsets': lookups, 'before_hex': before.hex(), 'after_hex': after.hex()},
        'verification': {'result': 'PASS', 'changed_bytes': len(changes), 'unchanged_gap_glyph': True, 'original_map_bank_unchanged': True, 'encoder_agreement': True, 'runtime_emulator': 'not run; supplied state pointer and static ROM glyph/payload verification'},
    }
    MANIFEST.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
