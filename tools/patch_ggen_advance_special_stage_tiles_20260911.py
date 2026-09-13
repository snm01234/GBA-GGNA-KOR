"""Translate all three white-background stage title metasprites in place."""
import hashlib
import json
import struct
from collections import Counter
from pathlib import Path
from zipfile import ZipFile
from PIL import Image
import analyze_ggen_advance_cd9250_warning_family_20260905 as fam
import build_ggen_advance_turn_ability_overlays_20260905 as tiles
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
from test_ggen_advance_font_pair import BdfFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs/20260911_stage_title_tiles'
ADDRESS = 0x08D51674
JOBS = [('extra4','裁かれし者','심판받은 자','엑스트라 세션'),
        ('16th','光る宇宙','빛나는 우주','세션'),
        ('last','妄執、果てる時','망집이 끝날 때','라스트 세션')]
def sha(b): return hashlib.sha256(b).hexdigest()
def as_image(canvas):
    im=Image.new('L',(len(canvas[0]),len(canvas)));im.putdata([v for row in canvas for v in row]);return im
def main():
    OUT.mkdir(exist_ok=True)
    path=ROOT/'SD Gundam GGeneration Advance (Korean).gba'
    parent=path.read_bytes(); jp=(ROOT/'SD Gundam GGeneration Advance (Japan).gba').read_bytes()
    assert sha(parent)==json.loads((ROOT/'integrated/main_tip/ggen_advance_main_tip_manifest.json').read_text())['sha256']
    hdr,blob=tiles.resource_blob(parent,ADDRESS); _,original=tiles.resource_blob(jp,ADDRESS)
    assert blob==original, 'target already edited'
    graphics=blob[hdr['gfx_rel']:hdr['pal_rel']]
    palette=tiles.palette_rgb(blob[hdr['pal_rel']:hdr['pal_rel']+32])
    white=palette.index((255,255,255));black=palette.index((0,0,0))
    assert white!=0 and black!=0
    with ZipFile(ROOT/'assets/fonts/Galmuri.zip') as z:font=BdfFont.from_bytes(z.read('Galmuri11.bdf'),'Galmuri11 Regular')
    def paint(im,text,box):
        x0,y0,x1,y1=box;im.paste(white,box)
        width=sum(6 if c==' ' else 12 for c in text);assert width<=x1-x0
        x=x0+(x1-x0-width)//2;y=y0+(y1-y0-12)//2
        for c in text:
            if c!=' ':
                mask=font.render(c,12,12);assert mask.getbbox();im.paste(black,(x,y,x+12,y+12),mask)
            x+=6 if c==' ' else 12
    rebuilt=bytearray(blob);bank=[];index={};reports=[];previews=[];allowed=set()
    st,_=statefmt.parse_png_state(path.with_suffix('.ss1'))
    source_ss_hash=sha(path.with_suffix('.ss1').read_bytes())
    runtime=bytearray(st)
    for n,(session,japanese,korean,header) in enumerate(JOBS):
        parsed,ids,by,lookup,gr=fam.parse_anim(parent,ADDRESS,n)
        objects=parsed['objects'];x0=min(o['x'] for o in objects);y0=min(o['y'] for o in objects)
        before=as_image(fam.analysis.stitch(graphics,parsed,ids,list(range(len(objects)))));after=before.copy()
        title_objs=[o for o in objects if o['y'] in (-80,-64)]
        def bounds(objs):return (min(o['x'] for o in objs)-x0,min(o['y'] for o in objs)-y0,max(o['x']+o['size_px'][0] for o in objs)-x0,max(o['y']+o['size_px'][1] for o in objs)-y0)
        titlebox=bounds(title_objs);paint(after,korean,titlebox)
        head_objs=[o for o in objects if o['y']==-112]
        hb=list(bounds(head_objs))
        if n==0:
            numberbox=(hb[2]-16,hb[1],hb[2],hb[3]) if n==0 else (hb[0],hb[1],hb[0]+32,hb[3])
            number=before.crop(numberbox)
            textwidth=sum(6 if c==' ' else 12 for c in header)
            combined=textwidth+8+number.width
            left=hb[0]+(hb[2]-hb[0]-combined)//2
            after.paste(white,tuple(hb))
            if n==0:
                paint(after,header,(left,hb[1],left+textwidth,hb[3]));nx=left+textwidth+8
            else:
                nx=left;paint(after,header,(left+number.width+8,hb[1],left+combined,hb[3]))
            after.paste(number,(nx,hb[1]))
            assert after.crop((nx,hb[1],nx+number.width,hb[3])).tobytes()==number.tobytes()
        elif n==1:
            hb[0]+=40;paint(after,header,tuple(hb))
        else:paint(after,header,tuple(hb))
        # Every pixel outside the two Japanese regions, including English and digits, is identical.
        for y in range(before.height):
            for x in range(before.width):
                if not any(a<=x<c and b<=y<d for a,b,c,d in (titlebox,hb)):
                    assert before.getpixel((x,y))==after.getpixel((x,y))
        newids=[]
        for obj in objects:
            w,h=obj['size_px'];ox=obj['x']-x0;oy=obj['y']-y0
            for ty in range(h//8):
                for tx in range(w//8):
                    raw=tiles.encode_tile([[after.getpixel((ox+tx*8+x,oy+ty*8+y)) for x in range(8)] for y in range(8)])
                    if raw not in index:index[raw]=len(bank);bank.append(raw)
                    newids.append(index[raw])
        struct.pack_into(f'<{len(newids)}H',rebuilt,lookup,*newids)
        allowed.update(range(hdr['off']+lookup,hdr['off']+lookup+len(newids)*2))
        if n==0:
            for dest,src in enumerate(ids):
                assert st[0x11000+dest*32:0x11000+(dest+1)*32]==graphics[src*32:(src+1)*32], 'supplied state source mismatch'
            for dest,src in enumerate(newids):runtime[0x11000+dest*32:0x11000+(dest+1)*32]=bank[src]
        reports.append(dict(session=session,japanese=japanese,korean=korean,header=header,live_tiles=len(ids) if n==0 else None))
        previews.append((before,after,parsed,newids))
    assert len(bank)<=hdr['tiles'], (len(bank),hdr['tiles'])
    newgfx=b''.join(bank).ljust(len(graphics),b'\0')
    rebuilt[hdr['gfx_rel']:hdr['pal_rel']]=newgfx
    allowed.update(range(hdr['off']+hdr['gfx_rel'],hdr['off']+hdr['pal_rel']))
    sheet=Image.new('RGB',(720,320),'white')
    for n,(before,after,parsed,newids) in enumerate(previews):
        decoded=as_image(fam.analysis.stitch(newgfx,parsed,newids,list(range(len(parsed['objects'])))))
        assert decoded.tobytes()==after.tobytes(), 'metasprite roundtrip'
        for row,im in enumerate((before,after)):
            rgb=Image.new('RGB',im.size);rgb.putdata([palette[v] if v else (255,255,255) for v in im.getdata()])
            sheet.paste(rgb,(n*240+(240-im.width)//2,row*160+16))
    sheet.resize((1440,640),Image.Resampling.NEAREST).save(OUT/'before_after.png')
    child=bytearray(parent);child[hdr['off']:hdr['off']+len(rebuilt)]=rebuilt
    changed={i for i,(a,b) in enumerate(zip(parent,child)) if a!=b};assert changed<=allowed
    assert path.read_bytes()==parent
    output=OUT/'ggen_special_stage_tiles_ko_20260911.gba';output.write_bytes(child)
    (OUT/'ss1_original.png').write_bytes(path.with_suffix('.ss1').read_bytes())
    (OUT/'ss1_vram_reconstruction.bin').write_bytes(runtime)
    report=dict(parent={'sha256':sha(parent)},output={'path':str(output.relative_to(ROOT)),'size':len(child),'sha256':sha(child)},
      source_state_sha256=source_ss_hash,resource=hex(ADDRESS),titles=reports,tiles_before=hdr['tiles'],tiles_after=len(bank),changed_bytes=len(changed),
      verification={'result':'PASS','all_three_metasprite_roundtrips':True,'supplied_state_source_tiles_exact':True,'english_and_digits_preserved':True,'only_graphics_and_tile_lookup_changed':True,'runtime':'pending'})
    (OUT/'manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8');main()
