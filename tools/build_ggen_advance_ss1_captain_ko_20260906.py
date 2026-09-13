"""Translate E0518 map 6 艦長 to 함장, proven against current ss1 BG3."""
import json
import struct
from zipfile import ZipFile
from PIL import Image, ImageDraw
import build_ggen_advance_anim3_round_caps_20260906 as common
import build_ggen_advance_status_ui_tile_overlay_poc as status
import analyze_ggen_advance_intermission_cycle_states_20260830 as bg

base = common.base
OUT = common.ROOT / 'outputs/20260906_ggen_advance_ss1_captain_ko'
RESULT = OUT / 'ggen_advance_ss1_captain_ko_20260906.gba'
MANIFEST = OUT / 'manifest.json'
TILES = list(range(0x8D,0x95))


def stitch(atlas):
    canvas = []
    for ty in range(2):
        tiles = [status.decode_tile(atlas,t) for t in TILES[ty*4:ty*4+4]]
        canvas.extend([sum((tile[y] for tile in tiles),[]) for y in range(8)])
    return canvas


def main():
    parent = base.MAIN_TIP_ROM.read_bytes()
    assert common.sha(parent) == json.loads(base.MAIN_TIP_MANIFEST.read_text(encoding='utf-8'))['sha256']
    off = struct.unpack_from('<I',parent,0xE0518)[0]-0x08000000
    length = struct.unpack_from('<I',parent,off)[0]&0xFFFF
    old_blob = parent[off:off+length+4]
    original = status.lzss_decompress(old_blob[4:])
    assert status.literal_only_compress(original) == old_blob
    m = common.stateutil.sem.parse_map(parent,struct.unpack_from('<I',parent,0xE0518+6*4)[0])
    assert (m['width'],m['height']) == (4,2) and [c&1023 for c in m['cells']] == TILES
    state_path = common.ROOT / 'SD Gundam GGeneration Advance (Korean).ss1'
    state,_ = common.stateutil.statefmt.parse_png_state(state_path)
    info = bg.bg_info(state,3)
    vram = state[0x1000:0x19000]
    live = []
    for i,t in enumerate(TILES):
        x,y = 200+i%4*8,56+i//4*8
        e = bg.map_entry(vram,info['screen_base'],info['size'],(x+info['scroll_x'])//8,(y+info['scroll_y'])//8)
        start = info['char_base']+(e&1023)*32
        assert not e&0xC00
        assert vram[start:start+32] == original[t*32:t*32+32]
        live.append({'screen':[x,y],'vram_tile':e&1023,'atlas_tile':t})
    before = stitch(original)
    # The leftmost column is the clean same-row gradient: 6,9,A,B...,A,9,6.
    canvas = [[row[0]]*32 for row in before]
    assert [row[0] for row in canvas] == [6,9,10]+[11]*10+[10,9,6]
    with ZipFile(base.FONT_ZIP) as archive:
        font = base.fontpair.load_bdf(archive,'Galmuri11.bdf')
    paint = base.paint_text(canvas,(0,0,32,16),'함장',font)
    assert canvas[0] == before[0] and canvas[15] == before[15]
    atlas = bytearray(original)
    for i,t in enumerate(TILES):
        tile = [row[i%4*8:i%4*8+8] for row in canvas[i//4*8:i//4*8+8]]
        status.encode_tile(atlas,t,tile)
    assert stitch(atlas) == canvas
    assert all(a==b or i//32 in TILES for i,(a,b) in enumerate(zip(original,atlas)))
    blob = status.literal_only_compress(atlas)
    assert len(blob) == len(old_blob)
    assert status.lzss_decompress(blob[4:]) == atlas
    output = bytearray(parent)
    output[off:off+len(blob)] = blob
    assert output[:off] == parent[:off] and output[off+len(blob):] == parent[off+len(blob):]
    OUT.mkdir(parents=True,exist_ok=True)
    RESULT.write_bytes(output)
    palette = state[0x800+11*32:0x800+12*32]
    sheet = Image.new('RGB',(528,150),(28,28,28))
    draw = ImageDraw.Draw(sheet)
    for i,(tag,pixels) in enumerate((('BEFORE',before),('AFTER',canvas))):
        im = base.animutil.canvas_image(pixels,palette,0,8)
        draw.text((i*272+4,4),tag,fill='white')
        sheet.paste(im,(i*272,22))
    sheet.save(OUT/'before_after.png')
    report = {'parent':{'path':base.advance_relative(base.MAIN_TIP_ROM),'sha256':common.sha(parent)},
        'output':{'path':base.advance_relative(RESULT),'size':len(output),'sha256':common.sha(output)},
        'state':{'path':base.advance_relative(state_path),'sha256':common.sha(state_path.read_bytes())},
        'resource':{'table':'0xE0518','map':6,'atlas_offset':hex(off),'tiles':TILES},
        'translation':{'source':'艦長','korean':'함장','font':'Galmuri11','paint':paint},
        'live_bg3_matches':live,
        'verification':{'result':'PASS','eight_live_tiles_match_current_atlas':True,
            'only_target_atlas_tiles_changed':True,'native_gradient_restored':True,
            'compression_roundtrip':True,'compressed_size_unchanged':True,
            'outside_atlas_resource_byte_exact':True,'runtime_emulator':'not run; decoded ROM preview only'}}
    assert base.MAIN_TIP_ROM.read_bytes()==parent
    MANIFEST.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=True,indent=2))


if __name__ == '__main__':
    main()
