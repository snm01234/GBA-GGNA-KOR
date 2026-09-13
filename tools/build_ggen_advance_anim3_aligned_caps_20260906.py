"""Align move/hold rims with HP, and give the hold glyph an orange field."""
import json
from zipfile import ZipFile
from PIL import Image, ImageDraw
import build_ggen_advance_anim3_round_caps_20260906 as prev

base = prev.base
OUT = prev.ROOT / 'outputs/20260906_ggen_advance_anim3_aligned_caps'
RESULT = OUT / 'ggen_advance_anim3_aligned_caps_20260906.gba'
MANIFEST = OUT / 'manifest.json'


def main():
    parent = base.MAIN_TIP_ROM.read_bytes()
    assert prev.sha(parent) == json.loads(base.MAIN_TIP_MANIFEST.read_text(encoding='utf-8'))['sha256']
    before, _, _ = base.ss12.resource_canvas(parent, base.KO_RES, 3)
    original, _, _ = base.ss12.resource_canvas(base.ORIGINAL_ROM.read_bytes(), base.JP_RES, 3)
    canvas = [r[:] for r in before]
    # Restore the native frame columns, including the exterior background.
    # The straight red rim is at x=58, as on HP; only the old shadow at x=59
    # becomes orange. Do not widen the silhouette to x=56 again.
    for rect in (base.RECT_MOVE, base.RECT_HOLD):
        x, y, _, bottom = rect
        for yy in range(y, bottom):
            canvas[yy][x:x+4] = [7 if v in (4, 5) else v for v in original[yy][x:x+4]]
        assert all(canvas[yy][58] == 6 for yy in range(y+3, y+13))
        assert all(canvas[yy][56:58] == original[yy][56:58] for yy in range(y,bottom))
    assert all(before[yy][58] == 6 for yy in range(27,37))

    # Build the exact existing Galmuri9 mask, distinguishing yellow glyph ink
    # from yellow background. Colour replacement alone cannot do this safely.
    with ZipFile(base.FONT_ZIP) as archive:
        font = base.fontpair.load_bdf(archive, 'Galmuri9.bdf')
    local_ink, _, _ = base.raster.native_ink(font, '지')
    ink = {(61+x, 59+y) for x,y in local_ink}
    outline = {(x+dx,y+dy) for x,y in ink for dx,dy in ((1,0),(-1,0),(0,1),(0,-1))} - ink
    assert all(before[y][x] == base.INK for x,y in ink)
    assert all(before[y][x] == base.CONTOUR for x,y in outline)
    # Orange fills the entire glyph footprint, including counters and the
    # former yellow flecks; two columns at the right blend into the panel.
    for y in range(57,71):
        for x in range(60,72):
            canvas[y][x] = 7 if x < 70 else (8 if x == 70 else 9)
    for x,y in outline:
        canvas[y][x] = base.CONTOUR
    for x,y in ink:
        canvas[y][x] = base.INK
    assert all(canvas[y][x] == before[y][x] for x,y in ink | outline)
    assert all(canvas[y][x] == 7 for y in range(57,71) for x in range(60,70) if (x,y) not in ink | outline)
    allowed = lambda x,y: (56 <= x < 60 and 40 <= y < 56) or (56 <= x < 72 and 56 <= y < 72)
    changes = [(x,y) for y,r in enumerate(canvas) for x,v in enumerate(r) if v != before[y][x]]
    assert all(allowed(x,y) for x,y in changes)
    output, lookups, tiles = prev.rebuild(parent, canvas)
    OUT.mkdir(parents=True, exist_ok=True)
    RESULT.write_bytes(output)
    state_path = prev.ROOT / 'SD Gundam GGeneration Advance (Korean).ss1'
    state, _ = prev.stateutil.statefmt.parse_png_state(state_path)
    palettes = state[0xA00:0xC00]
    sheet = Image.new('RGB', (704,492), (28,28,28))
    draw = ImageDraw.Draw(sheet)
    for i,(name,src) in enumerate((('BEFORE',before),('AFTER',canvas))):
        im = base.animutil.canvas_image([r[48:224] for r in src[20:76]],palettes,1,4)
        im.save(OUT / (name.lower()+'.png'))
        draw.text((4,i*246+4),name+' / SS1 palette - decoded ROM preview',fill='white')
        sheet.paste(im,(0,i*246+22))
    sheet.save(OUT/'before_after.png')
    manifest = {
        'parent': {'path': base.advance_relative(base.MAIN_TIP_ROM), 'sha256': prev.sha(parent)},
        'output': {'path': base.advance_relative(RESULT), 'size': len(output), 'sha256': prev.sha(output)},
        'changed_pixels': len(changes), 'private_tiles_appended': tiles, 'changed_lookup_entries': lookups,
        'verification': {'result': 'PASS', 'hp_move_hold_straight_rim_x': 58,
            'native_exterior_columns_restored': True, 'hold_glyph_and_outline_exact': True,
            'hold_background_uniform_orange': True, 'armor_unchanged': True,
            'other_animations_pixel_exact': True, 'shared_tiles_preserved': True,
            'outside_resource_byte_exact': True, 'runtime_emulator': 'not run; decoded ROM preview only'}}
    MANIFEST.write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(manifest,indent=2))


if __name__ == '__main__':
    main()
