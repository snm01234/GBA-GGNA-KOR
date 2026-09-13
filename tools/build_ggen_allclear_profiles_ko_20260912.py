"""Translate all-clear BGM/profile resources and their omitted text owners."""
import hashlib,json,re,struct,sys,shutil
from collections import Counter
from pathlib import Path
from zipfile import ZipFile
from PIL import Image,ImageDraw
import analyze_ggen_advance_fixed_word_semantics_20260830 as sem
import analyze_ggen_advance_unit_list_sprite_state_20260830 as sf
import build_ggen_advance_turn_ability_overlays_20260905 as raster
import build_ggen_advance_unified_rom_poc as unified
import build_ggen_advance_ko_poc as fo
import ggen_advance_painted_glyph_identity as glyph
import ggen_advance_text_codec as codec
from test_ggen_advance_font_pair import BdfFont
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs/20260912_allclear_profiles_ko'
BASE=0x8000000
BGM=['붉은 혜성','전투의 공포','작열','늠름한 샤아','애전사','바람에 홀로','해후','폭풍 속에서 빛나 줘','멘 오브 데스티니','제타 발동','사일런트 보이스','비욘드 더 타임','스탠드 업 투 더 빅토리','타올라라 투지 저주받은 숙명을 넘어','저스트 커뮤니케이션','드림스','턴 에이 턴','달의 고치','그렇게 함께였는데','멋쟁이 동료들','암운','어둠의 팔','허공에 울려 퍼지다','밤이 밝아올 때','전사의 휴식','데터미네이션','인베이드','전투 행진곡','도그파이트','프리세션','프로그램 오버','커튼콜','코드 A/G','우주세기 어나더','에필로그','스탠바이','우레가 울리는 철의 요새','솔리드 파이터']
LABELS=['아행','카행','사행','타행','나행','하행','마행','야행','라행','와행','영숫자','기호']
NORMAL=[0xcc3800,0xcc38c4,0xcc3990,0xcc3a60,0xcc3b2c,0xcc3bf8,0xcc3cc8,0xcc3d9c,0xcc3e6c,0xcc3f38,0xcc4008,0xcc40d8]
FOCUS=[0xcc4188,0xcc4264,0xcc4340,0xcc4424,0xcc450c,0xcc45ec,0xcc46d0,0xcc47b0,0xcc4890,0xcc496c,0xcc4a48,0xcc4b24]
sha=lambda b:hashlib.sha256(b).hexdigest()
def resource(rom,o):
 kind,w,h,mr,unused,gr,size,pr,reserved=struct.unpack_from('<HBB6H',rom,o)
 assert kind==0x1a and mr==16 and gr==(16+w*h*2+3)&~3
 gfx=sem.lzss_decompress(rom[o+gr:o+gr+size])
 m=dict(offset=o,width=w,height=h,cells=list(struct.unpack_from(f'<{w*h}H',rom,o+16)),gfx=gfx,gr=gr,size=size)
 can=sem.stitch(gfx,m);im=Image.new('L',(w*8,h*8));im.putdata([v for row in can for v in row]);return m,im
def bitmap(font,char):
 g=font.glyphs[ord(char)];im=Image.new('L',(g.width,g.height));bits=max(1,(g.width+7)//8)*8
 im.putdata([255 if row&(1<<(bits-x-1)) else 0 for row in g.rows for x in range(g.width)])
 return im
def paint(im,text,box,font,cell=12,face=11,outline=2):
 x0,y0,x1,y1=box;adv=[cell//2 if c==' ' else max(cell//2,bitmap(font,c).width+1) if ord(c)<128 else cell for c in text];width=sum(adv);assert width+2<=x1-x0,(text,width,box)
 mask=Image.new('L',im.size);x=x0+(x1-x0-width)//2
 for c,a in zip(text,adv):
  if c!=' ':
   b=bitmap(font,c);assert b.width<=a and b.height+2<=y1-y0,(text,b.size,box)
   mask.paste(b,(x+(a-b.width)//2,y0+(y1-y0-b.height)//2))
  x+=a
 pix=mask.load();points=[(x,y) for y in range(y0,y1) for x in range(x0,x1) if pix[x,y]]
 for x,y in points:
  for dx,dy in [(-1,0),(1,0),(0,-1),(0,1),(-1,-1),(1,1),(-1,1),(1,-1)]:
   if x0<=x+dx<x1 and y0<=y+dy<y1:im.putpixel((x+dx,y+dy),outline)
 for p in points:im.putpixel(p,face)
def clean_badge(focus):
 rows=[]
 for y in range(16):
  if focus:
   row='bb'+'8'*28+'bb' if y in (0,15) else 'b88'+'9'*26+'88b' if y in (1,14) else '88'+'9'*28+'88' if y in (2,13) else '899'+'a'*26+'998'
  else:row='b'*32 if y in (0,15) else 'bbb'+'7'*26+'bbb' if y in (1,14) else 'bb77'+'a'*24+'77bb' if y in (2,13) else 'b77'+'a'*26+'77b'
  assert len(row)==32;rows.extend(int(c,16) for c in row)
 im=Image.new('L',(32,16));im.putdata(rows);return im
def rebuilt_resource(rom,m,im):
 bank=[];lookup={};cells=[]
 for ty in range(m['height']):
  for tx in range(m['width']):
   raw=raster.encode_tile([[im.getpixel((tx*8+x,ty*8+y)) for x in range(8)] for y in range(8)])
   if raw not in lookup:lookup[raw]=len(bank);bank.append(raw)
   old=m['cells'][ty*m['width']+tx];cells.append((old&0xf000)|lookup[raw])
 # Keep the loader's fixed VRAM partitions: full profile <0xff; overlay <0x100.
 assert len(bank)<255,(hex(m['offset']),len(bank))
 head=bytearray(rom[m['offset']:m['offset']+m['gr']]);struct.pack_into('<H',head,0,0xa)
 struct.pack_into('<H',head,10,len(bank)*32);struct.pack_into(f'<{len(cells)}H',head,16,*cells)
 decoded=sem.stitch(b''.join(bank),dict(m,cells=cells));assert bytes(v for row in decoded for v in row)==im.tobytes()
 return bytes(head)+b''.join(bank),dict(m,cells=cells,gfx=b''.join(bank))
def main():
 import argparse
 args=argparse.ArgumentParser(description=__doc__);args.add_argument('--parent',type=Path,default=ROOT/'SD Gundam GGeneration Advance (Korean).gba');args=args.parse_args()
 sys.stdout.reconfigure(encoding='utf-8');OUT.mkdir(exist_ok=True)
 parent=args.parent.read_bytes();jp=(ROOT/'SD Gundam GGeneration Advance (Japan).gba').read_bytes()
 assert sha(parent)=='93e6fcc262f4fc428caace3d3797cdaae1d46ce7b94b5d5c88bc8bc5cdd7cc5a','Use the recorded pre-patch main TIP backup as --parent'
 child=bytearray(parent);allowed=set();report=dict(parent_sha256=sha(parent),graphics=[],texts=[],font_paints=[])
 def write(o,b):child[o:o+len(b)]=b;allowed.update(range(o,o+len(b)))
 with ZipFile(ROOT/'assets/fonts/Galmuri.zip') as z:
  fonts={n:BdfFont.from_bytes(z.read(n+'.bdf'),n) for n in ['Galmuri11','Galmuri11-Condensed','Galmuri7']}
 states={n:sf.parse_png_state(ROOT/f'SD Gundam GGeneration Advance (Korean)_allclear.ss{n}')[0] for n in range(1,5)}
 edits={};oldmeta={};newmeta={};before={}
 def openres(o):
  m,im=resource(parent,o);oldmeta[o]=m;before[o]=im.copy();edits[o]=im;return im
 # Title strips share an exact native row gradient; replace the entire old ink well.
 grad=[4,5,6,6,7,7,8,8,9,9,9,10,10,10,10,11]
 for o,text,box in [(0xcc1558,'BGM 감상',(84,8,160,24)),(0xcc1d70,'캐릭터 프로파일',(56,8,192,24)),(0xcc2a80,'캐릭터 프로파일',(0,0,136,16)),(0xcc2d04,'유닛 프로파일',(0,0,136,16))]:
  im=openres(o);x0,y0,x1,y1=box
  for y,v in enumerate(grad):im.paste(v,(x0,y0+y,x1,y0+y+1))
  paint(im,text,box,fonts['Galmuri11'],cell=12)
 # The embedded normal badges and separately loaded normal/focus variants all agree.
 badge_images={}
 for focus,addresses in [(False,NORMAL),(True,FOCUS)]:
  for i,o in enumerate(addresses):
   openres(o);im=clean_badge(focus);font=fonts['Galmuri11-Condensed'] if i==10 else fonts['Galmuri11'];cell=8 if i==10 else 12
   paint(im,LABELS[i],(1,0,31,16),font,cell,12 if focus else 11,1 if focus else 2);edits[o]=im;badge_images[focus,i]=im
 for col in range(3):
  for row in range(4):edits[0xcc1d70].paste(badge_images[False,col*4+row],(8+32*col,48+24*row))
 im=openres(0xcc055c)
 # Label uses palette bank 11; restore its flat brown well before painting.
 im.paste(5,(64,29,115,43));paint(im,'등장작품',(64,29,115,43),fonts['Galmuri11'],12,11,5)
 cursor=0x13b0000;assert not any(parent[cursor:0x13c0000])
 for o,im in edits.items():
  blob,m=rebuilt_resource(parent,oldmeta[o],im);cursor=(cursor+3)&~3;assert cursor+len(blob)<0x13c0000
  hits=[];pos=parent.find(struct.pack('<I',BASE+o))
  while pos>=0:
   assert pos%4==0;hits.append(pos);pos=parent.find(struct.pack('<I',BASE+o),pos+1)
  assert hits,(hex(o),'no pointer owners');write(cursor,blob)
  for p in hits:write(p,struct.pack('<I',BASE+cursor))
  newmeta[o]=m;report['graphics'].append(dict(source=hex(o),target=hex(cursor),owners=[hex(p) for p in hits],tiles=len(m['gfx'])//32));cursor+=len(blob)
 # The footer is an 8-pixel-high OBJ, not part of the profile background.
 footer=Image.new('L',(64,8));raw=parent[0xcbfba8:0xcbfca8];can=sem.stitch(raw,dict(width=8,height=1,cells=list(range(8))))
 footer.putdata([v for row in can for v in row]);oldfooter=footer.copy();footer.paste(15,(18,1,61,8));footer.paste(1,(18,0,61,1))
 # Galmuri7 Korean is 7 pixels high; retain the original L: and frame ends.
 for j,c in enumerate('능력치'):
  b=bitmap(fonts['Galmuri7'],c);assert b.height<=8
  for y in range(b.height):
   for x in range(b.width):
    if not b.getpixel((x,y)):continue
    for dx,dy in [(-1,0),(1,0),(0,-1),(0,1)]:
     if 0<=y+dy<8:footer.putpixel((24+j*8+x+dx,y+dy),2)
  footer.paste(10,(24+j*8,0,24+j*8+b.width,b.height),b)
 for tx in range(8):write(0xcbfba8+tx*32,raster.encode_tile([[footer.getpixel((tx*8+x,y)) for x in range(8)] for y in range(8)]))
 # Separate short-name fields at +12 were omitted from the original translation owner inventory.
 inv=json.loads((ROOT/'outputs/20260911_allclear_profiles/characters_inventory.json').read_text(encoding='utf-8'))
 manual={5:'아스란 자라3',23:'가이아',26:'카미유 비단H',35:'키라 야마토S',40:'쿠쿠루스 도안H',70:'티파',75:'동방불패 마스터 아시아',79:'도몬 캇슈 명경',101:'포우 에이지 울음',109:'미샤',112:'밀리아르도 피스크래프트',117:'유 카지마1',118:'유 카지마2'}
 for row in inv:
  ko=re.sub(r'<.*?>','',row['ko']);ko=re.sub(r' (전편|후편)$','',ko)
  suffix=re.search(r'([123])$',row['jp'])
  if suffix:ko=re.sub(r' [123]$','',ko)+suffix.group(1)
  ko=manual.get(row['i'],ko);assert ko and len(ko)<=14,(row,ko)
  report['texts'].append(dict(owner=row['owner'],jp=row['jp'],ko=ko,mode=8,kind='character_short_name'))
 for i,ko in enumerate(BGM):
  assert len(ko)<=25;report['texts'].append(dict(owner=hex(0x18dc3c+i*8),ko=ko,mode=8,kind='bgm'))
 report['texts'].append(dict(owner='0x1b195c',jp='ジョニー・ライデン専用のザクⅡ。',ko='조니 라이덴 전용 자쿠Ⅱ.',mode=12,kind='profile_description'))
 # Empty-group message is a shared ordinary 8x16 UI text owner, located by its source address.
 empty=0x1be7a3;owners=[];p=jp.find(struct.pack('<I',BASE+empty))
 while p>=0:
  owners.append(p);p=jp.find(struct.pack('<I',BASE+empty),p+1)
 for p in owners:report['texts'].append(dict(owner=hex(p),ko='해당 없음',mode=8,kind='empty_group'))
 merged=json.loads((ROOT/'integrated/translation/ggen_advance_translation_merged.json').read_text(encoding='utf-8'))
 live8,live12=unified.collect_live_slots(jp,merged['records'])
 import patch_ggen_advance_apsaras_zentetsu_20260908 as alloc8

 maps={}
 for mode in [8,12]:
  font=glyph.load_galmuri8() if mode==8 else glyph.load_galmuri12();base=glyph.FONT8_RELOCATED if mode==8 else glyph.FONT12_RELOCATED;stride=32 if mode==8 else 18;count=fo.FONT_8X16_COUNT if mode==8 else fo.FONT_12X12_COUNT
  pack=glyph.packed_8x16 if mode==8 else glyph.packed_12x12;live=live8 if mode==8 else live12;occupied=set();mapping={}
  for c in sorted({c for row in report['texts'] if row['mode']==mode for c in row['ko'] if '가'<=c<='힣'}):
   wanted=pack(c,font);hits=[s for s in range(count) if child[base+s*stride:base+(s+1)*stride]==wanted]
   if hits:s=hits[0]
   else:
    assert mode==8, (c,"missing 12x12 glyph");s=alloc8.choose_free_8x16(child,jp,live,occupied);write(base+s*stride,wanted);report['font_paints'].append(dict(char=c,mode=mode,slot=hex(s)));live.add(s)
   mapping[c]=s;occupied.add(s)
  maps[mode]=mapping
 textcursor=0x1114000;assert not any(parent[textcursor:0x1118000])
 for row in report['texts']:
  mode=row['mode'];verified=unified.load_verified_charmap(unified.CHARMAP_8X16_PATH if mode==8 else unified.CHARMAP_12X12_PATH)
  encoded,missing=unified.encode_korean_text(row['ko'],maps[mode],verified_charmap=verified,strict_punctuation=True);assert encoded and not missing,(row,missing)
  o=int(row['owner'],16);old=struct.unpack_from('<I',parent,o)[0];assert BASE<=old<BASE+len(parent)
  row.update(original_pointer=hex(old),pointer=hex(BASE+textcursor),encoded_hex=encoded.hex());write(textcursor,encoded);write(o,struct.pack('<I',BASE+textcursor));textcursor+=len(encoded);assert textcursor<0x1118000
 # Keep all unrelated bytes, original save files, and original source records intact.
 changed={i for i,(a,b) in enumerate(zip(parent,child)) if a!=b};assert changed<=allowed
 path=OUT/'ggen_allclear_profiles_ko_20260912.gba';path.write_bytes(child)
 shutil.copy2(ROOT/'SD Gundam GGeneration Advance (Korean)_allclear.sav',path.with_suffix('.sav'))
 report['output']=dict(path=str(path.relative_to(ROOT)),size=len(child),sha256=sha(child));report['changed_bytes']=len(changed)
 report['verification']=dict(result='PASS',graphics_roundtrip=True,unchanged_bytes_outside_allowlist=True,runtime='pending')
 (OUT/'manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 import pickle
 with (OUT/'reconstruction.pkl').open('wb') as f:pickle.dump(dict(old=oldmeta,new=newmeta,before=before,after=edits,footer=footer,oldfooter=oldfooter),f)
 print(json.dumps(dict(output=report['output'],graphics=len(edits),texts=len(report['texts']),font_paints=report['font_paints']),ensure_ascii=False,indent=2))
if __name__=='__main__':main()





