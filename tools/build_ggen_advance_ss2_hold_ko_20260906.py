"""Translate the four direct BG hold variants proven by the current ss2."""
import json
import struct
from zipfile import ZipFile
from PIL import Image, ImageDraw
import build_ggen_advance_anim3_round_caps_20260906 as common
import analyze_ggen_advance_intermission_cycle_states_20260830 as bg

base = common.base
OUT = common.ROOT / 'outputs/20260906_ggen_advance_ss2_hold_ko'
RESULT = OUT / 'ggen_advance_ss2_hold_ko_20260906.gba'
MANIFEST = OUT / 'manifest.json'
DESCRIPTORS = (0xC43238, 0xC433F0, 0xC434CC, 0xC435A8)


def render_descriptor(rom, off):
    w,h = rom[off+2:off+4]
    gr = struct.unpack_from('<H',rom,off+8)[0]
    ids = struct.unpack_from(f'<{w*h}H',rom,off+16)
    canvas = [[0]*(w*8) for _ in range(h*8)]
    for i,t in enumerate(ids):
        start = off+gr+(t&1023)*32
        tile = base.ss12.spr.decode_tile(rom[start:start+32])
        if t&2048:
            tile = tile[::-1]
        if t&1024:
            tile = [row[::-1] for row in tile]
        for y,row in enumerate(tile):
            canvas[i//w*8+y][i%w*8:i%w*8+8] = row
    return canvas


def main():
    parent = base.MAIN_TIP_ROM.read_bytes()
    assert common.sha(parent) == json.loads(base.MAIN_TIP_MANIFEST.read_text(encoding='utf-8'))['sha256']
    state_path = common.ROOT / 'SD Gundam GGeneration Advance (Korean).ss2'
    state,_ = common.stateutil.statefmt.parse_png_state(state_path)
    info = bg.bg_info(state,0)
    vram = state[0x1000:0x19000]
    live = []
    for y,off in ((120,0xC43274),(128,0xC432D4)):
        e = bg.map_entry(vram,info['screen_base'],info['size'],
                         (160+info['scroll_x'])//8,(y+info['scroll_y'])//8)
        assert not e&0xC00
        start = info['char_base']+(e&1023)*32
        assert vram[start:start+32] == parent[off:off+32]
        live.append({'screen': [160,y], 'bg':0, 'tile':e&1023, 'palette':e>>12, 'rom_offset':hex(off)})
    old = parent[0xC43274:0xC43294]+parent[0xC432D4:0xC432F4]
    before = base.ss12.spr.decode_tile(old[:32])+base.ss12.spr.decode_tile(old[32:])
    canvas = [[7]*8 for _ in range(16)]
    canvas[0],canvas[15] = before[0][:],before[15][:]
    with ZipFile(base.FONT_ZIP) as archive:
        font = base.fontpair.load_bdf(archive,'Galmuri9.bdf')
    ink,w,h = base.raster.native_ink(font,'지')
    assert (w,h) == (8,9)
    ink = {(x,y+3) for x,y in ink}
    outline = {(x+dx,y+dy) for x,y in ink for dx,dy in ((1,0),(-1,0),(0,1),(0,-1))}-ink
    outline = {(x,y) for x,y in outline if 0<=x<8 and 1<=y<15}
    for x,y in outline:
        canvas[y][x] = base.CONTOUR
    for x,y in ink:
        canvas[y][x] = base.INK
    new = base.ss12.tileops.encode_tile(canvas[:8])+base.ss12.tileops.encode_tile(canvas[8:])
    assert new != old
    output = bytearray(parent)
    allowed = set()
    reports = []
    for desc in DESCRIPTORS:
        assert parent[desc:desc+4] == bytes((10,0,3,2))
        assert struct.unpack_from('<H',parent,desc+8)[0] == 28
        top,bottom = desc+60,desc+156
        assert parent[top:top+32]+parent[bottom:bottom+32] == old
        for off,raw in ((top,new[:32]),(bottom,new[32:])):
            output[off:off+32] = raw
            allowed.update(range(off,off+32))
        a,b = render_descriptor(parent,desc),render_descriptor(output,desc)
        assert [r[8:16] for r in b] == canvas
        assert all(a[y][x] == b[y][x] for y in range(16) for x in range(24) if not 8<=x<16)
        reports.append({'descriptor':hex(desc),'upper':hex(top),'lower':hex(bottom)})
    assert all(i in allowed for i,(a,b) in enumerate(zip(parent,output)) if a!=b)
    assert all(canvas[y][x]==7 for y in range(1,15) for x in range(8) if (x,y) not in ink|outline)
    OUT.mkdir(parents=True,exist_ok=True)
    RESULT.write_bytes(output)
    palette = state[0x800+11*32:0x800+12*32]
    sheet = Image.new('RGB',(430,4*144+24),(28,28,28))
    draw = ImageDraw.Draw(sheet)
    draw.text((8,5),'BEFORE                         AFTER / SS2 palette',fill='white')
    for i,desc in enumerate(DESCRIPTORS):
        for col,rom in enumerate((parent,output)):
            im = base.animutil.canvas_image(render_descriptor(rom,desc),palette,0,8)
            sheet.paste(im,(col*216,i*144+24))
    sheet.save(OUT/'before_after.png')
    report = {'parent':{'path':base.advance_relative(base.MAIN_TIP_ROM),'sha256':common.sha(parent)},
        'output':{'path':base.advance_relative(RESULT),'size':len(output),'sha256':common.sha(output)},
        'state':{'path':base.advance_relative(state_path),'sha256':common.sha(state_path.read_bytes())},
        'live_tile_matches':live,'variants':reports,'font':'Galmuri9, ink 10 / cardinal outline 5',
        'verification':{'result':'PASS','live_bg0_payloads_match_current_rom':True,
            'four_variants_translated':True,'neighbor_grade_and_frame_preserved':True,
            'only_eight_target_tiles_changed':True,'anim3_unchanged':True,
            'runtime_emulator':'not run; decoded ROM previews only'}}
    assert base.MAIN_TIP_ROM.read_bytes()==parent
    MANIFEST.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__ == '__main__':
    main()
