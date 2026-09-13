"""Apply SS1-4 defense/terrain/ID text and two status-effect graphic badges."""
import json,struct,shutil,copy,binascii,sys
from collections import Counter
from pathlib import Path
from PIL import Image,ImageDraw
import patch_ggen_special_title_20260907 as b
import analyze_ggen_ss_followup_20260907 as a
import ggen_advance_painted_glyph_identity as glyph
import build_ggen_advance_unified_rom_poc as unified
import render_ggen_ss_tiles_20260905 as fullrender
from ggen_advance_text_codec import *
from build_ggen_advance_map_script_sheet import recount

OUT=b.ROOT/'outputs/20260907_ss1_ss4_followup'
START,END=0x1FE0000,0x1FE4000
TERRAIN=[
('18CF19','ア・バオア・クー','아 바오아 쿠'),('18CF22','アクシズ','액시즈'),('18CF27','ソロモン','솔로몬'),
('18CF2C','宇宙','우주'),('18CF2F','暗礁宙域','암초 우주역'),('18CF37','コロニー','콜로니'),('18CF3C','廃コロニー','폐콜로니'),
('18CF43','月面','월면'),('18CF48','クレーター','크레이터'),('18CF4E','月都市','월도시'),('18CF55','基地','기지'),
('18CF59','港湾施設','항만 시설'),('18CF62','工場','공장'),('18CF67','市街地','시가지'),('18CF6D','道路','도로'),
('18CF72','平地','평지'),('18CF76','森林','삼림'),('18CF7B','基地','기지'),('18CF7F','砂漠','사막'),
('18CF84','市街地','시가지'),('18CF8A','地面','지면'),('18CF8E','道路','도로'),('18CF93','平地','평지'),
('18CF97','森林','삼림'),('18CF9C','海','바다'),('18CF9F','オアシス','오아시스'),('18CFA4','荒地','황무지'),
('18CFA8','廃墟','폐허'),('18CFAD','地下洞窟','지하 동굴'),('18CFB5','地下基地','지하 기지'),('18CFBC','川','강'),
('18CFBF','岩壁','암벽'),('18CFC4','川','강'),('18CFC7','道路','도로'),('18CFCC','崖','절벽'),
('18CFCF','白の宮殿','백색 궁전'),('18CFD7','バルジ','벌지'),('18CFDB','衛星','위성'),('18CFE0','ソーラーシステム','솔라 시스템'),
('18CFE7','月','달'),('18CFEA','岩塊','바위'),('18CFEF','ジャンクヤード','정크 야드'),('18CFF7','デビルコロニー','데빌 콜로니'),('18CFFF','廃墟','폐허')]
IDNAMES=[
('17B6C6','友達は大事に……','친구는 소중히……'),('17B830','こいつはオレの獲物だ！！','이 녀석은 내 사냥감이다!!'),
('17BAD5','戦争屋風情が……！','전쟁꾼 따위가……!'),('17BD9C','尻尾を巻いて逃げるんだな！','꽁무니 빼고 도망쳐라!'),
('17BF34','私の愛馬は狂暴です','내 애마는 사납습니다'),('17BFDA','無茶をやるのがサイクロプスだ','무모한 게 사이클롭스다'),
('17C18E','この軟弱もの！！','이 나약한 녀석!!'),('17C1B4','概念だけのニュータイプなど……','개념뿐인 뉴타입 따위……'),
('17C4FE','まだ生贄が足りないと言うのか…','아직 제물이 부족하다는 건가…'),('17C84E','おとなしく棺桶で……','얌전히 관 속에서……'),
('17C882','わざわざヨーイドンで……','굳이 준비, 땅 하고……'),('17CCAF','この肌触りこそ戦争よ！','이 감촉이야말로 전쟁이지!'),
('17CDB1','負け犬は尻尾を巻いて……','패배자는 꼬리를 말고……')]

def stream(r,p):return read_tokens(r,p-0x8000000)[1]
def savejson(p,d):p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def main():
 OUT.mkdir(exist_ok=True)
 original=b.ORIGINAL_ROM.read_bytes();current=b.MAIN_TIP_ROM.read_bytes();sheetbytes=b.TRANSLATION_MERGED_JSON.read_bytes()
 b.gate(b.sha256(current)==json.loads(b.MAIN_TIP_MANIFEST.read_text(encoding='utf-8'))['sha256'],'main drift')
 merged=json.loads(sheetbytes);byid={r['record_id']:r for r in merged['records']};jobs=[]
 for off,jp,ko in TERRAIN+IDNAMES:
  row=byid['GGA-TEXT-00'+off]
  jobs.append({'row':row,'jp':jp,'ko':ko,'group':'terrain' if off.startswith('18') else 'id_name'})
 # Defense ability descriptions share one 8x16 table. Close every pending description in it.
 inventory=json.loads((OUT/'text_inventory.json').read_text(encoding='utf-8'))
 for item in inventory:
  if item['category']!='unit_defense_ability' or item['status']!='pending':continue
  jp=item['jp'].replace('<0269>','軽').replace('<028F>','減').replace('<07E5>','%').replace('<05AD>','率')
  b.gate('<' not in jp,'unresolved defense description')
  if jp=='50%の確率で':ko='50% 확률로'
  elif jp=='ダメージを20%軽減':ko='피해를 20% 경감'
  elif jp.startswith('威力'):
   ko=jp.replace('威力','위력').replace('軽減','경감').replace('なし','없음')
  else:raise ValueError(jp)
  b.gate(len(ko)<=12,'defense width overflow')
  jobs.append({'row':byid[item['id']],'jp':jp,'ko':ko,'group':'defense'})
 # The menu's unused-ID option was absent from the canonical extraction.
 rid='GGA-TEXT-001BE795';ownerid='OWNER-U32-0003AA88'
 b.gate(rid not in byid and not any(o['owner_id']==ownerid for o in merged['owners']),'new ID option already registered')
 source=0x1BE795;raw=read_tokens(original,source)[1]
 b.gate(b.u32(original,0x3AA88)==0x8000000+source,'ID option literal drift')
 row=copy.deepcopy(byid['GGA-TEXT-001BE746'])
 for k in ['record_id','container_id','translation_unit_id','context_bundle_id','source_record_id']:row[k]=rid
 row.update(target_file_offset=f'0x{source:08X}',target_address=f'0x{source+0x8000000:08X}',raw_hex=raw.hex(' ').upper(),original_byte_length=len(raw),original_raw_sha256=b.sha256(raw),owner_ids=[ownerid],owner_count=1,owner_digest=b.digest([ownerid]),translation_status='pending',translation_ko='',review_count=0)
 row['source_fingerprint']=b.digest({'record':rid,'raw':row['raw_hex'],'owner':ownerid})
 merged['records'].append(row);byid[rid]=row
 newowner={'owner_id':ownerid,'owner_kind':'u32_pointer','source_file_offset':'0x0003AA88','pointer_width':4,'target_record_ids':[rid],'target_container_ids':[rid],'relocation_schemas':['ordinary_u32_stream'],'source_types':['direct_pc_literal'],'families':['direct_pc_literal'],'synthetic':False}
 merged['owners'].append(newowner)
 jobs.append({'row':row,'jp':'IDコマンドを使用しない','ko':'ID커맨드를 사용하지 않음','group':'id_option'})
 candidate=bytearray(current);allowed=set();b.gate(not any(current[START:END]),'text cave occupied')
 dictionary=load_dictionary(original,DICT_8X16_BASE,DICT_8X16_END)
 font=glyph.load_galmuri8();chars=set(''.join(j['ko'] for j in jobs))-{' '};slots={};painted=[];live8,_=unified.collect_live_slots(original,merged['records']);occupied=set()
 cm=a.dec.load_identified_slot_to_char(a.dec.CHARMAP_8X16_PATH);cm[0x7E5]='%'
 rev={}
 for s,c in cm.items():rev.setdefault(c,s)
 for c in sorted(chars):
  if '가'<=c<='힣':
   wanted=glyph.packed_8x16(c,font);s=b.prev.try_recover(glyph.recover_unique_8x16_slots,candidate,font,c)
  else:
   jpchar={'!':'！',',':'、'}.get(c,c)
   b.gate(jpchar in rev,'missing native character '+c)
   src=rev[jpchar];wanted=original[b.fontops.FONT_8X16_BASE+src*32:b.fontops.FONT_8X16_BASE+(src+1)*32]
   hits=[s for s in range(b.fontops.FONT_8X16_COUNT) if glyph.slot_raw(candidate,glyph.FONT8_RELOCATED,s,32)==wanted]
   s=hits[0] if hits else None
  if s is None:
   s=b.prev.choose_free_8x16(candidate,original,live8,occupied);p=glyph.FONT8_RELOCATED+s*32
   candidate[p:p+32]=wanted;allowed.update(range(p,p+32));painted.append({'char':c,'slot':hex(s)});live8.add(s)
  slots[c]=s;occupied.add(s)
  b.gate(glyph.slot_raw(candidate,glyph.FONT8_RELOCATED,s,32)==wanted,'painted mismatch')
 # Keep an explicit byte mask for every emitted glyph, including native numerals/punctuation.
 glyphbytes={c:glyph.slot_raw(candidate,glyph.FONT8_RELOCATED,s,32) for c,s in slots.items()}
 cursor=START;reports=[];b.prev.BATCH_ID='ss1-ss4-followup-20260907'
 for j in jobs:
  row=j['row'];owners=b.prev.owner_offsets(row);b.gate(bool(owners),'no text owners')
  for own in owners:
   b.gate(b.u32(original,own)==int(row['target_address'],16),'source owner mismatch')
  payload=b.prev.encode_text(j['ko'],slots,{})
  decoded=expand_to_slots(read_tokens(payload,0)[0],dictionary)
  b.gate(len(decoded)==len(j['ko']),'glyph count mismatch')
  for c,s in zip(j['ko'],decoded):
   if c==' ':b.gate(s==1,'space mismatch')
   else:b.gate(glyph.slot_raw(candidate,glyph.FONT8_RELOCATED,s,32)==glyphbytes[c],'glyph verification')
  old=[stream(current,b.u32(current,own)) for own in owners]
  changed=any(x!=payload for x in old)
  if changed:
   cursor=b.prev.align16(cursor);b.gate(cursor+len(payload)<=END,'cave overflow')
   candidate[cursor:cursor+len(payload)]=payload;allowed.update(range(cursor,cursor+len(payload)))
   for own in owners:
    struct.pack_into('<I',candidate,own,0x8000000+cursor);allowed.update(range(own,own+4))
   cursor+=len(payload)
  for own in owners:b.gate(stream(candidate,b.u32(candidate,own))==payload,'owner roundtrip')
  b.prev.mark_row(row,j['jp'],j['ko'],'ss1~ss3 및 동일 테이블 누락/오역. 원본 8x16 글리프 판독과 현재 한글 글리프 역대조.')
  row['translation_source']='rom_glyph_analysis';row['qa_status']='static_payload_and_glyph_verified';b.prev.update_payload_hash(row)
  reports.append({'record':row['record_id'],'group':j['group'],'japanese':j['jp'],'korean':j['ko'],'owners':[hex(x) for x in owners],'changed_rom':changed,'pointer':hex(b.u32(candidate,owners[0]))})
 # Resource64=足止 and65=ID封印 use their original private atlas slots.
 atlasoff=b.u32(current,a.badges.TABLE)-0x8000000;length=b.u32(current,atlasoff)&65535
 atlas=a.status.lzss_decompress(current[atlasoff+4:atlasoff+4+length]);b.gate(len(atlas)==519*32,'atlas size drift')
 newatlas=bytearray(atlas);patchtiles={};badge_reports=[];previews=[]
 for index,text in [(64,'발묶기'),(65,'ID봉인')]:
  m=a.badges.parse_map(current,index);before=a.sem.stitch(atlas,m)
  clean=[[13]*32 for _ in range(16)]
  clean[0]=[4]*32;clean[15]=[4]*32
  if index==64:
   for y in range(1,15):
    clean[y][26:]=before[y][26:]
    clean[y][0]=7 if 3<=y<=10 else 5
   for x in range(1,26):clean[1][x]=5;clean[12][x]=5;clean[13][x]=3;clean[14][x]=8
  else:
   for y in range(1,15):clean[y][0]=4;clean[y][31]=4
   for x in range(1,31):clean[1][x]=8;clean[14][x]=8
  after=[r[:] for r in clean];ink=set();xpos=0
  for c in text:
   # Use the same Galmuri11 condensed shapes as the active text font.
   mask=b.fontops.unpack_8x16(glyph.packed_8x16(c,font)) if '가'<=c<='힣' else font.render(c,8,16)
   bb=mask.getbbox();b.gate(bb is not None,'blank badge glyph')
   x0,y0,x1,y1=bb
   for yy in range(y0,y1):
    for xx in range(x0,x1):
     if mask.getpixel((xx,yy)):ink.add((xpos+xx-x0,yy-y0))
   xpos+=x1-x0
  iw=max(x for x,y in ink)+1;ih=max(y for x,y in ink)+1
  region=25 if index==64 else 30
  dx=1+(region-iw)//2;dy=2
  ink={(x+dx,y+dy) for x,y in ink};outline=a.raster.dilate(ink,32,16)-ink
  b.gate(all(0<x<31 and 0<y<15 for x,y in ink|outline),'badge text clips frame')
  for x,y in outline:after[y][x]=3
  for x,y in ink:after[y][x]=(7,6,5)[min(2,(y-dy)*3//ih)]
  for n,cell in enumerate(m['cells']):
   b.gate(cell&0xC00==0,'flipped badge tile')
   tid=cell&1023;new=a.raster.encode_tile([line[n%4*8:n%4*8+8] for line in after[n//4*8:n//4*8+8]])
   for other in range(1,69):
    om=a.sem.parse_map(current,b.u32(current,a.badges.TABLE+other*4))
    if other!=index and om:b.gate(tid not in {c&1023 for c in om['cells']},'shared status tile')
   patchtiles[tid]=new;newatlas[tid*32:tid*32+32]=new
  b.gate(a.sem.stitch(newatlas,m)==after,'badge map roundtrip')
  badge_reports.append({'resource':index,'japanese':'足止' if index==64 else 'ID封印','korean':text,'tiles':[c&1023 for c in m['cells']],'ink_width':iw,'ink_height':ih})
  previews.append((before,clean,after))
 blob=a.status.literal_only_compress(newatlas)
 b.gate(len(blob)==length+4 and a.status.lzss_decompress(blob[4:])==newatlas,'atlas roundtrip')
 candidate[atlasoff:atlasoff+len(blob)]=blob;allowed.update(range(atlasoff,atlasoff+len(blob)))
 for index in range(1,69):
  m=a.sem.parse_map(current,b.u32(current,a.badges.TABLE+index*4))
  if m and index not in (64,65):b.gate(a.sem.stitch(atlas,m)==a.sem.stitch(newatlas,m),'unrelated graphics changed')
 changes={i for i,(x,y) in enumerate(zip(current,candidate)) if x!=y};b.gate(changes<=allowed,'unapproved bytes changed')
 st,_=a.statefmt.parse_png_state(b.ROOT/'SD Gundam GGeneration Advance (Korean).ss4')
 colors=a.raster.palette_rgb(st[0x9A0:0x9C0]);im=Image.new('RGB',(96,32))
 for y,triple in enumerate(previews):
  for x,c in enumerate(triple):im.paste(a.raster.render_canvas(c,colors),(x*32,y*16))
 im.resize((768,256),Image.Resampling.NEAREST).save(OUT/'badges_before_clean_after.png')
 fixed=bytearray(st);live=[]
 for tid,new in patchtiles.items():
  pos=0x1000+(tid+1)*32
  if st[pos:pos+32]==atlas[tid*32:tid*32+32]:fixed[pos:pos+32]=new;live.append(tid)
 b.gate(set(a.badges.parse_map(current,64)['cells'][i]&1023 for i in range(8))<=set(live),'ss4 source VRAM proof missing')
 struct.pack_into('<I',fixed,8,binascii.crc32(candidate)&0xFFFFFFFF)
 (OUT/'preview.ss4').write_bytes(a.raster.replace_state_chunk(b.ROOT/'SD Gundam GGeneration Advance (Korean).ss4',bytes(fixed)))
 fullrender.OUT=OUT;fullrender.render(bytes(fixed)).resize((720,480),Image.Resampling.NEAREST).save(OUT/'ss4_after.png')
 # Text proofs rendered from the actual emitted cells, rather than substitute fonts.
 for group in ['defense','terrain','id_name','id_option']:
  subset=[j for j in jobs if j['group']==group];im=Image.new('L',(260,len(subset)*24));draw=ImageDraw.Draw(im)
  for i,j in enumerate(subset):
   draw.text((0,i*24),j['row']['record_id'][-6:],fill=128)
   for x,c in enumerate(j['ko']):
    if c!=' ':im.paste(b.fontops.unpack_8x16(glyphbytes[c]),(48+x*8,i*24))
  im.resize((780,im.height*3),Image.Resampling.NEAREST).save(OUT/(group+'_after.png'))
 output=OUT/'ggen_ss1_ss4_followup_ko_20260907.gba';output.write_bytes(candidate)
 b.gate(b.MAIN_TIP_ROM.read_bytes()==current and b.TRANSLATION_MERGED_JSON.read_bytes()==sheetbytes,'concurrent project change')
 (OUT/'translation_before.json').write_bytes(sheetbytes);shutil.copy2(b.TRANSLATION_MANIFEST,OUT/'translation_manifest_before.json')
 identity=merged['identity'];parent=identity.get('translation_overlay_identity_sha256','');identity['parent_translation_overlay_identity_sha256']=parent
 identity['translation_overlay_identity_sha256']=b.digest({'parent':parent,'batch':b.prev.BATCH_ID,'records':reports})
 identity['ss_followup_added_record_identity_sha256']=b.digest({'record':rid,'owner':newowner})
 summary=merged['summary'];counts=dict(Counter(r.get('translation_status','') for r in merged['records']));summary['merged_translation_status_counts']=counts
 for k in ['records_total','canonical_records','unique_target_count','owner_count','u32_owner_count','context_bundle_count','translation_unit_count']:summary[k]=summary.get(k,0)+1
 summary['translated_canonical_records']=sum(r.get('scope_status')=='included' and r.get('translation_status')=='translated' for r in merged['records'])
 summary['untranslated_canonical_records']=sum(r.get('scope_status')=='included' and r.get('translation_status')!='translated' for r in merged['records'])
 summary['translation_overlay_identity_sha256']=identity['translation_overlay_identity_sha256']
 recount(merged)
 snapshot=OUT/'translation_after.json';data=json.dumps(merged,ensure_ascii=False,indent=2)+'\n';snapshot.write_text(data,encoding='utf-8');b.TRANSLATION_MERGED_JSON.write_text(data,encoding='utf-8');b.prev.update_translation_manifest(merged,snapshot)
 report={'parent':{'sha256':b.sha256(current)},'output':{'path':b.advance_relative(output),'size':len(candidate),'sha256':b.sha256(candidate)},'texts':reports,'painted_glyphs':painted,'badges':badge_reports,'verification':{'result':'PASS','text_groups':dict(Counter(j['group'] for j in jobs)),'rom_text_updates':sum(r['changed_rom'] for r in reports),'text_payload_and_actual_glyphs_verified':True,'atlas_size_preserved':len(atlas),'non_target_graphics_pixel_exact':True,'ss4_live_tiles_matched':live,'scope_verified':True,'runtime':'static ROM and derived SS4 rendering; emulator re-entry not run'}}
 savejson(OUT/'manifest.json',report);print(json.dumps({k:report[k] for k in ['output','painted_glyphs','badges','verification']},ensure_ascii=False,indent=2))

if __name__=='__main__':sys.stdout.reconfigure(encoding='utf-8');main()
