"""Translate battle-row direct 万/間 pairs, separate from the status atlas."""
import json
from zipfile import ZipFile
from PIL import Image, ImageDraw
import build_ggen_advance_anim3_round_caps_20260906 as common
import build_ggen_advance_battle_weapon_fixed_graphics_galmuri7_poc as fixed

base = common.base
OUT = common.ROOT / 'outputs/20260906_ggen_advance_battle_range_badges'
RESULT = OUT / 'ggen_advance_battle_range_badges_20260906.gba'
MANIFEST = OUT / 'manifest.json'
TARGETS = [('万','만',(0xA8DD50,0xA8DDC4)),('間','간',(0xA8DE38,0xA8DEAC))]


def pair(rom, offsets):
    left,right = [fixed.decode_8x16(rom[d+20:d+84]) for d in offsets]
    return [a+b for a,b in zip(left,right)]


def main():
    parent = base.MAIN_TIP_ROM.read_bytes()
    jp = base.ORIGINAL_ROM.read_bytes()
    assert common.sha(parent) == json.loads(base.MAIN_TIP_MANIFEST.read_text(encoding='utf-8'))['sha256']
    state_path = common.ROOT / 'SD Gundam GGeneration Advance (Korean).ss1'
    state,_ = common.stateutil.statefmt.parse_png_state(state_path)
    # Selected row: OAM 13 at (200,64), 32x16, tiles 104..111.
    # Its second and third columns form the 間 badge at screen (208,64).
    live = []
    for dest,off in ((105,0xA8DE4C),(106,0xA8DEC0),(109,0xA8DE6C),(110,0xA8DEE0)):
        assert state[0x11000+dest*32:0x11000+(dest+1)*32] == parent[off:off+32]
        live.append({'obj_tile':dest,'rom_offset':hex(off)})
    donor = pair(jp,(fixed.BACKGROUND_RESOURCES['middle'],fixed.BACKGROUND_RESOURCES['right']))
    output = bytearray(parent)
    allowed = set()
    reports = []
    with ZipFile(base.FONT_ZIP) as archive:
        font = base.fontpair.load_bdf(archive,'Galmuri7.bdf')
    for source,text,offsets in TARGETS:
        before = pair(parent,offsets)
        assert before == pair(jp,offsets)
        for d in offsets:
            assert parent[d:d+20] == fixed.RESOURCE_HEADER
        # Restore both bright Japanese ink and the dark shadow, using the
        # glyph-free same-family background, retaining structural cap pixels.
        pixels = [[donor[y][x] if v in fixed.SOURCE_GLYPH_INDICES else v
                   for x,v in enumerate(row)] for y,row in enumerate(before)]
        clean = [row[:] for row in pixels]
        g = font.glyphs[ord(text)]
        assert (g.width,g.height) == (7,7)
        glyph = font.render(text,7,7)
        ink = {(x+4,y+4) for y in range(7) for x in range(7) if glyph.getpixel((x,y))}
        contour = {(x+dx,y+dy) for x,y in ink for dy in (-1,0,1) for dx in (-1,0,1)}-ink
        for x,y in contour:
            pixels[y][x] = 4
        for x,y in ink:
            pixels[y][x] = 15
        assert all(pixels[y][x]==clean[y][x] for y in range(16) for x in range(16) if (x,y) not in ink|contour)
        for col,d in enumerate(offsets):
            raw = fixed.encode_8x16([row[col*8:col*8+8] for row in pixels])
            output[d+20:d+84] = raw
            allowed.update(range(d+20,d+84))
            assert output[d:d+20] == parent[d:d+20]
            assert output[d+84:d+116] == parent[d+84:d+116]
        assert pair(output,offsets) == pixels
        reports.append({'source':source,'translation':text,'descriptors':[hex(d) for d in offsets],
                        'ink_pixels':len(ink),'contour_pixels':len(contour)})
    assert all(i in allowed for i,(a,b) in enumerate(zip(parent,output)) if a!=b)
    OUT.mkdir(parents=True,exist_ok=True)
    RESULT.write_bytes(output)
    # Show actual selected and disabled row palettes; all variants use the
    # same changed payload, with their original palettes retained.
    sheet = Image.new('RGB',(540,4*150+22),(28,28,28))
    draw = ImageDraw.Draw(sheet)
    draw.text((4,4),'BEFORE                     AFTER / current SS1 OBJ palettes',fill='white')
    for row,(bank,target) in enumerate((b,t) for b in (9,8) for t in TARGETS):
        source,text,offsets = target
        palette = state[0xA00+bank*32:0xA00+(bank+1)*32]
        for col,rom in enumerate((parent,output)):
            im = base.animutil.canvas_image(pair(rom,offsets),palette,0,8)
            sheet.paste(im,(col*270+65,row*150+40))
        draw.text((4,row*150+24),f'{source.encode("unicode_escape").decode()} / palette {bank}',fill='white')
    sheet.save(OUT/'before_after.png')
    report = {'parent':{'path':base.advance_relative(base.MAIN_TIP_ROM),'sha256':common.sha(parent)},
        'output':{'path':base.advance_relative(RESULT),'size':len(output),'sha256':common.sha(output)},
        'state':{'path':base.advance_relative(state_path),'sha256':common.sha(state_path.read_bytes())},
        'live_matches':live,'translations':reports,'font':'Galmuri7 native 7x7, 8-neighbor outline',
        'verification':{'result':'PASS','live_interval_payload_match':True,
            'both_source_pairs_japanese_before':True,'only_four_graphic_payloads_changed':True,
            'headers_palettes_and_existing_korean_badges_preserved':True,
            'runtime_emulator':'not run; decoded ROM preview only'}}
    assert base.MAIN_TIP_ROM.read_bytes()==parent
    MANIFEST.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=True,indent=2))


if __name__ == '__main__':
    main()
