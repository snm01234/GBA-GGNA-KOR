"""Repair only anim3 cap pixels on the current main ROM; preserve shared tiles."""
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

from PIL import Image, ImageDraw

import build_ggen_advance_remodel_anim3_followup_20260905 as base
import ggen_ss_tiles_common_20260905 as stateutil

ROOT = base.ADVANCE_ROOT
OUT = ROOT / 'outputs/20260906_ggen_advance_anim3_round_caps'
RESULT = OUT / 'ggen_advance_anim3_round_caps_20260906.gba'
MANIFEST = OUT / 'manifest.json'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def rebuild(parent, canvas):
    h = base.ss12.spr.parse_resource_header(parent, base.KO_RES)
    _, records = base.ss12.animrec.animation_records(parent, base.KO_RES)
    parsed, ids, lookup = base.ss12.parse_animation_cross(records, 3)
    objects = parsed['objects']
    minx = min(int(o['x']) for o in objects)
    miny = min(int(o['y']) for o in objects)
    graphics = bytearray(h['graphics'])
    original_graphics = bytes(graphics)
    prefix = bytearray(parent[h['offset']:h['offset'] + h['graphics_rel']])
    cache = {bytes(graphics[t:t+32]): t//32 for t in range(0, len(graphics), 32)}
    cursor = 0
    writes = {}
    for obj in objects:
        wt, ht = [int(v)//8 for v in obj['size_px']]
        for ty in range(ht):
            for tx in range(wt):
                index = cursor + ty*wt + tx
                x = int(obj['x']) - minx + tx*8
                y = int(obj['y']) - miny + ty*8
                payload = base.ss12.tileops.encode_tile([row[x:x+8] for row in canvas[y:y+8]])
                old = ids[index]
                if payload == original_graphics[old*32:old*32+32]:
                    continue
                if payload not in cache:
                    cache[payload] = len(graphics)//32
                    graphics.extend(payload)
                rel = lookup - h['offset'] + index*2
                new = cache[payload]
                assert rel not in writes or writes[rel] == new
                writes[rel] = new
                struct.pack_into('<H', prefix, rel, new)
        cursor += wt*ht
    assert graphics[:len(original_graphics)] == original_graphics
    struct.pack_into('<I', prefix, 12, len(prefix) + len(graphics))
    blob = prefix + graphics + h['palettes']
    off = h['offset']
    assert off + len(blob) <= base.ALLOC_END
    assert not any(parent[off+h['resource_bytes']:off+len(blob)])
    output = bytearray(parent)
    output[off:off+len(blob)] = blob
    assert output[:off] == parent[:off] and output[off+len(blob):] == parent[off+len(blob):]
    # Verify every other animation's pixels and palette after lookup relocation.
    for animation in range(h['animation_count']):
        a, p, bank = base.ss12.resource_canvas(parent, base.KO_RES, animation)
        b, q, next_bank = base.ss12.resource_canvas(output, base.KO_RES, animation)
        assert p == q and bank == next_bank
        assert b == (canvas if animation == 3 else a), animation
    return bytes(output), len(writes), (len(graphics)-len(original_graphics))//32


def main():
    parent = base.MAIN_TIP_ROM.read_bytes()
    assert sha(parent) == json.loads(base.MAIN_TIP_MANIFEST.read_text(encoding='utf-8'))['sha256']
    state_path = ROOT / 'SD Gundam GGeneration Advance (Korean).ss1'
    state, _ = stateutil.statefmt.parse_png_state(state_path)
    slots = base.ss12.spr.list_slots(state[0x19000:0x21000])
    assert any(s['resource'] == '0x092D8000' and s['anim'] == 3 for s in slots)
    before, _, _ = base.ss12.resource_canvas(parent, base.KO_RES, 3)
    canvas = [row[:] for row in before]
    # Four available columns before the existing Korean outline. The native
    # motion rim supplies the actual corner steps and red/orange/amber ramp.
    profile = [row[125:129] for row in before[24:40]]
    assert profile[3] == [6, 7, 8, 9]
    # HP uses a broader orange band. Keep identical curvature, increasing the
    # orange dwell from one to two columns, followed by a light-orange step.
    hold_profile = [[{8: 7, 9: 8}.get(v, v) for v in row] for row in profile]
    changes = []
    allowed = set()
    for label, rect, ramp in [('move', base.RECT_MOVE, profile),
                              ('armor', base.RECT_ARMOR, profile),
                              ('hold', base.RECT_HOLD, hold_profile)]:
        x, y, _, bottom = rect
        for dy, row in enumerate(ramp):
            canvas[y+dy][x:x+4] = row
            allowed.update((x+dx, y+dy) for dx in range(4))
        assert all(v not in (4, 5) for row in ramp for v in row)
        changes.append({'label': label, 'rect': [x, y, x+4, bottom],
                        'profile': ramp, 'changed_pixels': sum(before[yy][xx] != canvas[yy][xx]
                        for yy in range(y,bottom) for xx in range(x,x+4))})
    assert all((x,y) in allowed for y,row in enumerate(canvas) for x,v in enumerate(row) if v != before[y][x])
    output, lookups, tiles = rebuild(parent, canvas)
    OUT.mkdir(parents=True, exist_ok=True)
    RESULT.write_bytes(output)
    # Render with the supplied state's warm OBJ palette, rather than the
    # resource's default blue variant. This is a decoded-asset preview.
    palettes = state[0xA00:0xC00]
    panels = []
    for tag, src in [('BEFORE', before), ('AFTER', canvas)]:
        im = base.animutil.canvas_image([row[48:224] for row in src[20:76]], palettes, 1, 4)
        panels.append(im)
        im.save(OUT / f'{tag.lower()}.png')
    preview = Image.new('RGB', (panels[0].width, 2*(panels[0].height+22)), (28,28,28))
    draw = ImageDraw.Draw(preview)
    for i, (tag, im) in enumerate(zip(('BEFORE', 'AFTER'), panels)):
        y = i*(im.height+22)
        draw.text((5,y+4), tag + ' / SS1 palette - decoded ROM preview', fill='white')
        preview.paste(im,(0,y+22))
    preview.save(OUT/'before_after.png')
    manifest = {'parent': {'path': base.advance_relative(base.MAIN_TIP_ROM), 'sha256': sha(parent)},
                'output': {'path': base.advance_relative(RESULT), 'size': len(output), 'sha256': sha(output)},
                'state': {'path': base.advance_relative(state_path), 'sha256': sha(state_path.read_bytes())},
                'changes': changes, 'private_tiles_appended': tiles, 'changed_lookup_entries': lookups,
                'verification': {'result': 'PASS', 'all_other_animations_pixel_exact': True,
                    'only_three_left_4px_caps_changed': True, 'korean_glyphs_preserved': True,
                    'existing_shared_tiles_preserved': True, 'outside_resource_byte_exact': True,
                    'ss1_active_resource_confirmed': True, 'runtime_emulator': 'not run; decoded ROM preview only'}}
    assert base.MAIN_TIP_ROM.read_bytes() == parent
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(manifest, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
