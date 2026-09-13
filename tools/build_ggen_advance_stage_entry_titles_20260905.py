"""Replace the 25 stage-entry BG title sources with native Galmuri11 Regular.

Owner: 0805EB58 indexes the 12-byte table 08D58B40 and calls 08001C50.
The second and third fields select separate English OBJ artwork: untouched.
"""
from pathlib import Path
from zipfile import ZipFile
import sys,struct,json,hashlib
from PIL import Image,ImageDraw
sys.path.insert(0,str(Path(__file__).resolve().parent))
from analyze_ggen_advance_stage_title_sources_20260905 import descriptor,ROOT
from analyze_ggen_advance_unit_list_sprite_state_20260830 import parse_png_state
from test_ggen_advance_font_pair import BdfFont
OUT=ROOT/'outputs/20260905_ggen_advance_stage_titles'
STEM='ggen_advance_stage_entry_titles_ko_candidate_20260905'
TABLE=0xd58b40
def gate(ok,msg):
    if not ok:raise RuntimeError(msg)
def sha(b):return hashlib.sha256(b).hexdigest()
def plane(q):
    im=Image.new('L',(240,160))
    for n,c in enumerate(q['cells']):
        t=q['tiles'][(c&1023)*32:(c&1023)*32+32]
        for y in range(8):
            for x in range(8):
                xx=7-x if c&1024 else x;yy=7-y if c&2048 else y
                im.putpixel((n%30*8+x,n//30*8+y),(t[yy*4+xx//2]>>(4*(xx&1)))&15)
    return im
def rgb(im,pal):
    out=Image.new('RGB',im.size)
    out.putdata([tuple(((pal[v]>>shift)&31)*255//31 for shift in (0,5,10)) for v in im.getdata()])
    return out
def text_image(font,text):
    widths=[6 if c==' ' else 12 for c in text]; im=Image.new('L',(sum(widths),12),14);x=0
    for c,w in zip(text,widths):
        if c!=' ':
            mask=font.render(c,12,12);im.paste(1,(x,0,x+12,12),mask)
        x+=w
    return im
def ascii_strip(src,pal,box):
    crop=src.crop(box);lum=rgb(crop,pal).convert('L');bbox=lum.point(lambda v:255 if v>0 else 0).getbbox()
    gate(bbox is not None,'empty original ASCII strip')
    # Keep vertical alignment and every antialias pixel of the original glyphs.
    return crop.crop((bbox[0],0,bbox[2],crop.height))
def pack(im,palette):
    tiles=[];lookup={};cells=[]
    for ty in range(20):
        for tx in range(30):
            b=bytes(im.getpixel((tx*8+x,ty*8+y))|(im.getpixel((tx*8+x+1,ty*8+y))<<4) for y in range(8) for x in range(0,8,2))
            if b not in lookup:lookup[b]=len(tiles);tiles.append(b)
            cells.append(lookup[b])
    data=b''.join(tiles);pr=1216+len(data)
    gate(len(data)+32<=0x4000,'title spills into next character block')
    return struct.pack('<4B6H',2,0,30,20,16,1200,1216,len(data),pr,32)+struct.pack('<600H',*cells)+data+palette
def read_raw(blob):
    tr,tl,pr,pl=struct.unpack_from('<4H',blob,8)
    return dict(tiles=blob[tr:tr+tl],cells=struct.unpack_from('<600H',blob,16))
def main():
    parent_path=ROOT/'SD Gundam GGeneration Advance (Korean).gba';parent=parent_path.read_bytes()
    gate(sha(parent)=='4738f732f36085f6acb47a86a7f947d8e83f8888c7a4ce3375abeb37c989513e','approved parent drift')
    jp=(ROOT/'SD Gundam GGeneration Advance (Japan).gba').read_bytes()
    s,_=parse_png_state(ROOT/'SD Gundam GGeneration Advance (Korean).ss1')
    spec=json.loads((ROOT/'data/ggen_advance_stage_entry_titles_ko_20260905.json').read_text(encoding='utf-8'))
    gate(len(spec['titles'])==25,'title table count')
    with ZipFile(ROOT/'assets/fonts/Galmuri.zip') as z:fontbytes=z.read('Galmuri11.bdf')
    font=BdfFont.from_bytes(fontbytes,'Galmuri11 Regular')
    child=bytearray(parent);cursor=0x1f50000;spans=[];reports=[];pairs=[];runtime=None
    def put(off,b):child[off:off+len(b)]=b;spans.append((off,len(b)))
    for i,(session,japanese,korean) in enumerate(spec['titles']):
        ref=TABLE+12*i;a=struct.unpack_from('<I',parent,ref)[0]-0x8000000;q=descriptor(jp,a)
        gate(parent[a:a+q['pr']+32]==jp[a:a+q['pr']+32],'parent title has changes')
        palbytes=jp[a+q['pr']:a+q['pr']+32];pal=struct.unpack('<16H',palbytes)
        gate(pal[14]==0 and pal[1]==0x7fff,'native text palette drift')
        src=plane(q);dst=src.copy();dst.paste(14,(0,20,240,44));dst.paste(14,(0,48,240,96))
        parts=[]
        if session.startswith('extra'):
            parts=[text_image(font,'엑스트라 세션'),ascii_strip(src,pal,(196,24,216,40))]
        elif session.startswith('after'):
            parts=[text_image(font,'애프터 세션'),ascii_strip(src,pal,(180,24,224,40))]
        elif session.startswith('encore'):
            parts=[text_image(font,'앙코르'),ascii_strip(src,pal,(156,24,176,40))]
        else:
            # Twelve's original header is shifted eight pixels left.
            cut=90 if session=='12th' else (98 if len(session)==4 else 94)
            parts=[ascii_strip(src,pal,(48,24,cut,40)),text_image(font,'세션')]
        width=sum(p.width for p in parts)+8*(len(parts)-1);x=(240-width)//2
        retained=[]
        for p in parts:
            y=24 if p.height==16 else 26
            dst.paste(p,(x,y));retained.append((x,y,p));x+=p.width+8
        title=text_image(font,korean);gate(title.width<=224,'title too wide: '+korean)
        dst.paste(title,((240-title.width)//2,63))
        for x,y,p in retained:
            gate(dst.crop((x,y,x+p.width,y+p.height)).tobytes()==p.tobytes(),'header part clipped')
        blob=pack(dst,palbytes);decoded=plane(read_raw(blob))
        gate(decoded.tobytes()==dst.tobytes(),'source tile roundtrip failed')
        for y in list(range(20))+list(range(44,48))+list(range(96,160)):
            gate(src.crop((0,y,240,y+1)).tobytes()==dst.crop((0,y,240,y+1)).tobytes(),'non-Japanese region changed')
        gate(not any(parent[cursor:cursor+len(blob)]),'candidate allocation occupied')
        put(cursor,blob);put(ref,struct.pack('<I',cursor+0x8000000))
        gate(child[ref+4:ref+12]==parent[ref+4:ref+12],'English sprite selection changed')
        if i==6:
            # Loader copies to tile base 1; verify every live map cell and tile.
            for n,c in enumerate(q['cells']):
                x,y=n%30,n//30;live=struct.unpack_from('<H',s,0x1000+0xf000+2*(y*32+x))[0]
                gate(live==c+1,'live title map mismatch')
                gate(s[0x1000+(live&1023)*32:0x1000+(live&1023)*32+32]==q['tiles'][(c&1023)*32:(c&1023)*32+32],'live title tile mismatch')
            ss=bytearray(s);rawq=read_raw(blob)
            ss[0x1020:0x1020+len(rawq['tiles'])]=rawq['tiles']
            for n,c in enumerate(rawq['cells']):struct.pack_into('<H',ss,0x1000+0xf000+2*((n//30)*32+n%30),c+1)
            runtime=ss
        reports.append(dict(index=i,session=session,japanese=japanese,korean=korean,source=hex(a+0x8000000),replacement=hex(cursor+0x8000000),pointer=hex(ref+0x8000000),bytes=len(blob),tile_count=(len(blob)-1248)//32,ascii_artwork_preserved=True,english_obj_unchanged=True))
        pairs.append((session,rgb(src,pal),rgb(dst,pal)))
        cursor=(cursor+len(blob)+255)&~255
    allowed={x for off,n in spans for x in range(off,off+n)}
    changed=[i for i,(a,b) in enumerate(zip(parent,child)) if a!=b]
    gate(set(changed)<=allowed and len(child)==len(parent),'diff escape')
    gate(child[0xd4a650:0xd58b40]==parent[0xd4a650:0xd58b40],'English sprite packages changed')
    OUT.mkdir(exist_ok=True);rom=OUT/(STEM+'.gba');sav=rom.with_suffix('.sav');sv=parent_path.with_suffix('.sav').read_bytes()
    gate(not sav.exists() or sav.read_bytes()==sv,'output save has user changes')
    rom.write_bytes(child);sav.write_bytes(sv);gate(rom.read_bytes()==child,'ROM readback')
    sheet=Image.new('RGB',(960,((len(pairs)+3)//4)*180));dr=ImageDraw.Draw(sheet)
    for i,(label,before,after) in enumerate(pairs):
        x=i%4*240;y=i//4*180;dr.text((x+6,y+3),label,fill='white');sheet.paste(after,(x,y+20))
    sheet.save(OUT/'all_titles_ko.png')
    preview=Image.new('RGB',(960,640));preview.paste(pairs[6][2].resize((960,640),Image.Resampling.NEAREST))
    # The PNG save-container's image is the actual supplied screenshot. Keep
    # its English bottom portion exactly for a clearly labelled simulation.
    original=Image.open(ROOT/'SD Gundam GGeneration Advance (Korean).ss1').convert('RGB')
    if original.size==(240,160):
        bottom=original.crop((0,96,240,160)).resize((960,256),Image.Resampling.NEAREST);preview.paste(bottom,(0,384))
    preview.save(OUT/'stage6_ko_simulated.png')
    report=dict(kind=STEM,parent_sha256=sha(parent),output=dict(path=str(rom.relative_to(ROOT)),size=len(child),sha256=sha(child)),
        verification=dict(result='STATIC_PASS_RUNTIME_PENDING',live_state='600 map cells and all referenced tiles exact; source 08D3DEBC',
            table_entries=25,english_obj_bytes_preserved=True,source_roundtrip=True,unrelated_pixels_preserved=True),
        font=dict(member='Galmuri11.bdf',sha256=sha(fontbytes),weight='Regular',cell=[12,12],synthetic_bold=False),
        allocation=[hex(0x1f50000),hex(cursor)],changed_bytes=len(changed),sources=reports,
        note='All 25 entries in the stage-entry table covered. Native table numbering skips extra4 and 16th; no invented entries. Main ROM is not promoted. Preview is a source reconstruction, not an emulator run.')
    (ROOT/'legacy/analysis/ggen_advance_stage_entry_titles_ko_20260905.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='sources'},ensure_ascii=False,indent=2))
if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');main()
