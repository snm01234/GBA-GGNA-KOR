from pathlib import Path
import sys,struct,json
sys.path.insert(0,str(Path(__file__).resolve().parent))
from analyze_ggen_advance_source_flash_20260905 import render,ROOT
from analyze_ggen_advance_action_graphics_scan_20260830 import lzss_decompress
from PIL import Image,ImageDraw
def descriptor(r,a):
    f,z,w,h=r[a:a+4]
    mr,ml,tr,tl,pr,pl=struct.unpack_from('<6H',r,a+4)
    if not (f==0x12 and z==0 and w==30 and h==20 and mr==16 and ml==1200):raise ValueError()
    d=lzss_decompress(r[a+tr:a+tr+tl])
    return dict(address=a,width=w,height=h,tiles=d,cells=struct.unpack_from('<600H',r,a+mr),tr=tr,tl=tl,pr=pr,pl=pl)
from analyze_ggen_advance_unit_list_sprite_state_20260830 import parse_png_state
def main():
    r=(ROOT/'SD Gundam GGeneration Advance (Japan).gba').read_bytes()
    s,_=parse_png_state(ROOT/'SD Gundam GGeneration Advance (Korean).ss1')
    ids=set(struct.unpack_from('<640H',s,0x1000+0xf000))
    live={s[0x1000+(c&1023)*32:0x1000+(c&1023)*32+32] for c in ids}
    live={t for t in live if len(set(t))>2}
    qs=[]
    for a in range(0,len(r)-16,4):
        if r[a]!=0x12:continue
        try:q=descriptor(r,a)
        except (ValueError,IndexError,struct.error):continue
        ts={q['tiles'][i:i+32] for i in range(0,len(q['tiles']),32)}
        n=len(ts&live)
        if 0xd30000<=a<0xd50000:
            qs.append({'address':hex(a),'w':q['width'],'h':q['height'],'matches':n,'tiles':len(ts),'tr':q['tr'],'tl':q['tl'],'pr':q['pr'],'pl':q['pl']})
    out=ROOT/'outputs/20260905_ggen_advance_stage_titles';out.mkdir(exist_ok=True)
    im=Image.new('RGB',(720,((len(qs)+2)//3)*180));dr=ImageDraw.Draw(im)
    for i,row in enumerate(qs):
        q=descriptor(r,int(row['address'],16)); src=render(q);x=i%3*240;y=i//3*180
        dr.text((x,y),f"{i} {row['address']} match={row['matches']}",fill='white');im.paste(src,(x,y+20))
    im.save(out/'source_titles.png')
    (ROOT/'legacy/analysis/ggen_advance_stage_title_sources_20260905.json').write_text(json.dumps(qs,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(qs,indent=2));print('live',len(live))
if __name__=='__main__':main()
