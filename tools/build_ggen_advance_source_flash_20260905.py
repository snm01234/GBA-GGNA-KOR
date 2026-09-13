"""Replace the proven BG source descriptors, not another post-frame hook.

Use the user-measured pre-wait candidate as parent. Clone seven descriptors
into a verified empty ROM region and redirect every exact pointer to them.
The loader 080638E4 explicitly supports raw DMA with flag 0x10 cleared.
Do not modify the canonical ROM or any existing user save.
"""
from pathlib import Path
import sys,struct,json,hashlib
from PIL import Image,ImageDraw
sys.path.insert(0,str(Path(__file__).resolve().parent))
from analyze_ggen_advance_source_flash_20260905 import ROOT,descriptor,render
from analyze_ggen_advance_unit_list_sprite_state_20260830 import parse_png_state
PARENT=ROOT/'outputs/20260905_ggen_advance_owned_sort_pre_wait/ggen_advance_owned_sort_pre_wait_candidate_20260905.gba'
OUT=ROOT/'outputs/20260905_ggen_advance_source_flash'
STEM='ggen_advance_source_flash_candidate_20260905'
SPECS=[(0xc48630,'owned_panel',[0x6def8],0xc5a00),
       (0xc48ac4,'owned_blank_panel',[0x6de6c],0xc5a00),
       (0xc4543c,'level_focus',[0xd58f04],0x1f21800),
       (0xc45574,'name_focus',[0xd58f08,0xd58f14],0x1f21c00),
       (0xc456b4,'deployed_focus',[0xd58f0c,0xd58f18],0x1f22000),
       (0xc458d4,'ascending_focus',[0xd58f1c],0x1f21a00),
       (0xc459bc,'descending_focus',[0xd58f20],0x1f21e00)]
def gate(ok,msg):
    if not ok:raise RuntimeError(msg)
def sha(b):return hashlib.sha256(b).hexdigest()
def hits(data,pattern):
    start=0; result=[]
    while True:
        start=data.find(pattern,start)
        if start<0:return result
        result.append(start);start+=1
def main():
    parent=PARENT.read_bytes(); jp=(ROOT/'SD Gundam GGeneration Advance (Japan).gba').read_bytes()
    gate(sha(parent)=='3f05793cb1a32c940c0889c11bd7b5dfaef02a5127b3ad0e95b06ff4b084a442','parent drift')
    gate(sha(jp)=='75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772','JP drift')
    state,_=parse_png_state(ROOT/'SD Gundam GGeneration Advance (Japan).ss1')
    child=bytearray(parent); cursor=0x1f23000; reports=[]; previews=[]; spans=[]
    def put(off,b):child[off:off+len(b)]=b;spans.append((off,len(b)))
    for a,name,refs,payload in SPECS:
        q=descriptor(jp,a); end=a+q['tr']+q['tl']
        gate(parent[a:end]==jp[a:end],name+' original resource drift')
        gate(q['pr']==q['pl']==0,'embedded palette unexpected')
        gate(hits(parent,struct.pack('<I',a+0x8000000))==refs,name+' pointer inventory drift')
        tiles=bytearray(q['tiles']); evidence={}
        if name.startswith('owned'):
            target=[y*9+x for y in (9,10) for x in range(1,6)]
            ids=[q['cells'][n]&1023 for n in target]
            gate(len(set(ids))==10,'owned target alias')
            gate([n for n,c in enumerate(q['cells']) if c&1023 in ids]==target,'owned aliases outside glyph window')
            for j,n in enumerate(target):
                c=q['cells'][n]; x=21+n%9; y=n//9
                live=struct.unpack_from('<H',state,0x1000+0xe800+2*(32*y+x))[0]
                raw=state[0x1000+0x8000+(live&1023)*32:0x1000+0x8000+(live&1023)*32+32]
                gate(c&0xc00==0 and raw==tiles[(c&1023)*32:(c&1023)*32+32],name+' live glyph mismatch')
                tiles[(c&1023)*32:(c&1023)*32+32]=parent[payload+j*32:payload+(j+1)*32]
            evidence={'live_exact_glyph_tiles':10,'target_source_tile_ids':ids,'screen_box':[176,72,216,88]}
        else:
            count=q['width']*q['height']
            gate([c&0xfff for c in q['cells']]==list(range(count)),'focus nonsequential map')
            gate(len(tiles)==count*32,'focus allocation drift')
            tiles[:]=parent[payload:payload+len(tiles)]
        # Existing graphics/map geometry and tile count stay byte-exact.
        blob=bytearray(parent[a:a+q['tr']]);blob[0]&=~0x10
        struct.pack_into('<H',blob,10,len(tiles));blob+=tiles
        gate(len(blob)%4==0 and cursor%4==0,'DMA alignment')
        gate(not any(parent[cursor:cursor+len(blob)]),'source cave occupied')
        put(cursor,blob)
        for ref in refs:put(ref,struct.pack('<I',cursor+0x8000000))
        decoded=descriptor(child,cursor)
        gate(decoded['tiles']==tiles and decoded['cells']==q['cells'],'descriptor reload failed')
        before=render(q); after=render(decoded)
        if name.startswith('owned'):
            for y in range(before.height):
                for x in range(before.width):
                    if not(8<=x<48 and 72<=y<88):gate(before.getpixel((x,y))==after.getpixel((x,y)),'unrelated panel pixel changed')
        gate(before.tobytes()!=after.tobytes(),'source did not change')
        reports.append(dict(name=name,original=hex(a+0x8000000),replacement=hex(cursor+0x8000000),
            references=[hex(x+0x8000000) for x in refs],tile_bytes=len(tiles),map_preserved=True,
            korean_payload=hex(payload+0x8000000),evidence=evidence))
        previews.append((name,before,after));cursor=(cursor+len(blob)+0xff)&~0xff
    allowed={i for off,n in spans for i in range(off,off+n)}
    diff=[i for i,(a,b) in enumerate(zip(parent,child)) if a!=b]
    gate(set(diff)<=allowed and len(child)==len(parent),'diff escaped')
    gate(child[0x1f20000:0x1f22200]==parent[0x1f20000:0x1f22200],'existing sort/pre-wait changed')
    OUT.mkdir(exist_ok=True)
    path=OUT/(STEM+'.gba');save=path.with_suffix('.sav');savebytes=PARENT.with_suffix('.sav').read_bytes()
    gate(not save.exists() or save.read_bytes()==savebytes,'existing candidate save has user changes')
    path.write_bytes(child);save.write_bytes(savebytes)
    gate(path.read_bytes()==child,'ROM readback failed')
    sheet=Image.new('RGB',(520,sum(b.height*2+34 for _,b,_ in previews)),(30,30,40));dr=ImageDraw.Draw(sheet);y=0
    for name,b,a in previews:
        dr.text((8,y+3),name+'   original -> Korean source',fill='white')
        sheet.paste(b.resize((b.width*2,b.height*2)),(8,y+26));sheet.paste(a.resize((a.width*2,a.height*2)),(260,y+26));y+=b.height*2+34
    sheet.save(OUT/'source_before_after.png')
    report=dict(parent=str(PARENT.relative_to(ROOT)),parent_sha256=sha(parent),output=str(path.relative_to(ROOT)),sha256=sha(child),
        static='PASS',runtime='PENDING user frame-by-frame test',changed_bytes=len(diff),sources=reports,
        cave=[hex(0x1f23000),hex(cursor)],save_sha256=sha(savebytes),
        method='Replace all known exact source references with raw Korean BG descriptor clones; 080638E4 raw DMA path. No new frame hook.',
        preserved='Canonical main f4ec, original compressed resources, prior saves, pre-wait candidate hooks and Korean payloads.',
        limitation='Static reload and exact live owned glyph matches verified; no new emulator frame trace. HP focus resource intentionally unchanged (different original sort criterion).')
    (ROOT/'analysis'/('ggen_advance_source_flash_20260905.json')).write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))
if __name__=='__main__':main()
