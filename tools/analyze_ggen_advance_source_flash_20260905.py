from pathlib import Path
import sys, struct, json
from PIL import Image, ImageDraw
sys.path.insert(0,str(Path(__file__).resolve().parent))
from analyze_ggen_advance_action_graphics_scan_20260830 import lzss_decompress
from analyze_ggen_advance_unit_list_sprite_state_20260830 import parse_png_state
ROOT=Path(__file__).resolve().parent.parent
def descriptor(r,a):
    f,_,w,h=r[a:a+4]
    mr,ml,tr,tl,pr,pl=struct.unpack_from('<6H',r,a+4)
    if not (f in (10,26) and 0<w<=32 and 0<h<=32 and ml==w*h*2 and mr==16 and tr>=16+ml and tl>0): raise ValueError()
    d=lzss_decompress(r[a+tr:a+tr+tl]) if f&16 else r[a+tr:a+tr+tl]
    cells=struct.unpack_from('<%dH'%(w*h),r,a+mr)
    if len(d)%32 or max(c&1023 for c in cells)*32>=len(d): raise ValueError()
    return dict(address=a,width=w,height=h,tiles=d,cells=cells,tr=tr,tl=tl,pr=pr,pl=pl)
def render(q):
    w,h=q['width'],q['height']; im=Image.new('RGB',(w*8,h*8)); pal=[(i*17,i*17,i*17) for i in range(16)]
    for n,c in enumerate(q['cells']):
        raw=q['tiles'][(c&1023)*32:(c&1023)*32+32]
        for y in range(8):
            for x in range(8):
                xx=7-x if c&1024 else x; yy=7-y if c&2048 else y
                v=(raw[yy*4+xx//2]>>(4*(xx&1)))&15
                im.putpixel((n%w*8+x,n//w*8+y),pal[v])
    return im
def main():
    r=(ROOT/'SD Gundam GGeneration Advance (Japan).gba').read_bytes()
    s,_=parse_png_state(ROOT/'SD Gundam GGeneration Advance (Japan).ss1')
    live=[]
    for y in (9,10):
        for x in range(22,27):
            c=struct.unpack_from('<H',s,0x1000+0xe800+2*(32*y+x))[0]
            live.append(s[0x1000+0x8000+(c&1023)*32:0x1000+0x8000+(c&1023)*32+32])
    qs=[]
    for a in range(0xc40000,0xc60000,4):
        try:q=descriptor(r,a)
        except (ValueError,IndexError,struct.error):continue
        q['matches']=[i for i,t in enumerate(live) if t in [q['tiles'][j:j+32] for j in range(0,len(q['tiles']),32)]]
        qs.append(q)
    out=ROOT/'outputs/20260905_ggen_advance_source_flash'; out.mkdir(exist_ok=True)
    sheet=Image.new('RGB',(640, sum(max(q['height']*8+22,40) for q in qs)),(40,40,60)); draw=ImageDraw.Draw(sheet); y=0
    for q in qs:
        draw.text((0,y),f"{q['address']:08X} {q['width']}x{q['height']} matches={q['matches']}",fill='white'); sheet.paste(render(q),(0,y+20)); y+=max(q['height']*8+22,40)
    sheet.save(out/'descriptors.png')
    print(json.dumps([{k:v for k,v in q.items() if k not in ('tiles','cells')} for q in qs],indent=2))
if __name__=='__main__':main()
