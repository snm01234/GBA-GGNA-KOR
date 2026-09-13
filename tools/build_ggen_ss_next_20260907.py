"""Close refreshed SS1-4 graphics and wait/pause map-dialogue extraction gaps."""
import sys,json,struct,shutil,copy,hashlib
from pathlib import Path
from PIL import Image,ImageDraw
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'analysis'))
import ggen_ss_tiles_common_20260905 as c
import ggen_advance_project_paths as paths
import ggen_advance_painted_glyph_identity as glyph
import patch_ggen_advance_pending_readable_batch_20260907 as prev
import build_ggen_advance_event_exp_weapon_badges_preemptive_candidate_20260904 as badges
import analyze_ggen_advance_battle_map_script_gap_20260905 as hook
import extract_ggen_advance_map_script_dialogue as extract
import build_ggen_advance_map_script_sheet as sheet
import _tmp_classify_pending_readable_20260907 as dec
import render_ggen_ss_tiles_20260905 as render
from ggen_advance_text_codec import *
OUT=c.ROOT/'outputs/20260907_ss1_ss4_next'
TEXT_START,TEXT_END=0x1FE4000,0x1FE6000
TABLE_START,TABLE_END=0x1308000,0x1358000
TITLE_CLONE=0x1FE8000
TRANSLATIONS={
'00F52620':['히이로 유이 이하 별동대가','여왕 구출에 나섭니다'],
'00F52BC9':['또한 솔로몬 요새의','지온군도 아직 건재하다'],
'00F52BE8':['최악의 경우 이 양쪽을','적으로 돌릴 수도 있다'],
'00F52C0A':['각자 우선 그 점을','명심해 두도록'],
'00F52DD7':['따라서 우리는 달로 가서……'],
'00F52DEB':['집결 중인 네오 지온 함대를','공격한다'],
'00F52E02':['함대의 루나2 공격을','저지하는 것이 이번 임무다'],
'00F52E2B':['네오 지온 함대에는','총수인 캐스발 외에도……'],
'00F52E46':['다수의 뉴타입이 참가했다는','정보도 들어와 있다'],
'00F52E69':['수는 결코 많지 않지만','강적임은 틀림없다'],
'00F52E89':['각자 긴장을 늦추지 말고','작전에 임하도록!'],
'00F52FFF':['에이스 파일럿을 다수 보유한','정예부대가 배치되어 있습니다'],
'00F6E389':['제1방어선에 적기 다수!','……지온군이다!'],
'00F6E426':['……응?','뭐지, 저건!?'],
}
def sha(b):return hashlib.sha256(b).hexdigest()
def save(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def title_canvas(raw):
 out=[[0]*176 for _ in range(32)];k=0
 for x0,w in [(0,64),(64,64),(128,32),(160,16)]:
  for ty in range(4):
   for tx in range(w//8):
    tile=c.raster.decode_tile(raw[k*32:(k+1)*32]);k+=1
    for y in range(8):out[ty*8+y][x0+tx*8:x0+tx*8+8]=tile[y]
 return out
def title_encode(canvas):
 out=bytearray()
 for x0,w in [(0,64),(64,64),(128,32),(160,16)]:
  for ty in range(4):
   for tx in range(w//8):out.extend(c.raster.encode_tile([row[x0+tx*8:x0+tx*8+8] for row in canvas[ty*8:ty*8+8]]))
 return bytes(out)
def main():
 OUT.mkdir(exist_ok=True);jp=paths.ORIGINAL_ROM.read_bytes();parent=paths.MAIN_TIP_ROM.read_bytes();sheetbytes=paths.TRANSLATION_MERGED_JSON.read_bytes()
 assert sha(parent)==json.loads(paths.MAIN_TIP_MANIFEST.read_text(encoding='utf-8'))['sha256']
 merged=json.loads(sheetbytes);candidate=bytearray(parent);allowed=set();font=glyph.load_galmuri12();reports={};states={}
 for n in range(1,5):states[n]=c.statefmt.parse_png_state(c.ROOT/f'SD Gundam GGeneration Advance (Korean).ss{n}')[0]
 def write(p,b):candidate[p:p+len(b)]=b;allowed.update(range(p,p+len(b)))
 # Seven-member BG family: four attack variants already use Korean clones.
 badge_report=[];gallery=[];tile_changes={}
 for source,text in [(0xA8F090,'회피'),(0xA8F2C0,'간접'),(0xA8F4F0,'대기')]:
  assert parent[source:source+0x230]==jp[source:source+0x230]
  resource=bytearray(parent[source:source+0x230]);result=badges.repaint_badge(resource,text,font)
  gr=c.u16(resource,8);size=c.u16(resource,10);write(source+gr,resource[gr:gr+size])
  for n in range(size//32):
   old=parent[source+gr+n*32:source+gr+(n+1)*32];new=bytes(resource[gr+n*32:gr+(n+1)*32])
   if old!=new:
    assert old not in tile_changes or tile_changes[old]==new
    tile_changes[old]=new
  colors=c.raster.palette_rgb(resource[c.u16(resource,12):c.u16(resource,12)+32])
  gallery.append((hex(source)+' '+text, c.raster.render_canvas([a+b for a,b in zip(result['before'],result['after'])],colors)))
  badge_report.append({'source':hex(source),'korean':text,'graphics_bytes':size})
 for pointer,expected in [(0x384F8,0x1F44000),(0x38510,0x1F44400),(0x38528,0x1F44800),(0x38558,0x1F44C00)]:
  assert c.u32(parent,pointer)==0x8000000+expected
  assert candidate[expected:expected+0x230]==parent[expected:expected+0x230]
 c.gallery(gallery,OUT/'battle_badges_before_after.png',4)
 st=states[2];fixed=bytearray(st);matches=[]
 # BG2 charbase=0, exact source matches limited to its live tile area.
 import analyze_ggen_advance_intermission_cycle_states_20260830 as bg
 info=bg.bg_info(st,2)
 for tile in range(1024):
  p=0x1000+info['char_base']+tile*32;old=st[p:p+32]
  if old in tile_changes:fixed[p:p+32]=tile_changes[old];matches.append(tile)
 assert {0x203,0x204,0x208}<=set(matches)
 render.OUT=OUT;render.render(bytes(fixed)).resize((720,480),Image.Resampling.NEAREST).save(OUT/'ss2_after.png')
 reports['badges']={'patched':badge_report,'existing_four_korean_clones_preserved':True,'ss2_live_tiles':matches}
 # The animated title repeats the same 88 source IDs in 53 frames. Give
 # every destination tile a private source ID, including formerly shared blanks.
 source=0x170D1C;gr=0x6200;pr=0x6D20;resource_end=pr+6*32
 assert parent[source:source+resource_end]==jp[source:source+resource_end]
 atlas=parent[source+gr:source+pr];live=states[1][0x13000:0x13B00]
 ids=[next(i for i in range(89) if atlas[i*32:(i+1)*32]==live[n*32:(n+1)*32]) for n in range(88)]
 needle=struct.pack('<88H',*ids);resource=bytearray(parent[source:source+resource_end]);positions=[];p=0
 while True:
  p=resource.find(needle,p,gr)
  if p<0:break
  positions.append(p);p+=len(needle)
 assert len(positions)==53
 before=title_canvas(live);after=[[0]*176 for _ in range(32)]
 base_ink=set();advance=0
 for ch in '스테이지 클리어':
  if ch==' ':advance+=4;continue
  cell=glyph.fontops.unpack_12x12(glyph.packed_12x12(ch,font));x0,y0,x1,y1=cell.getbbox()
  base_ink.update((advance+x-x0,y) for y in range(12) for x in range(x0,x1) if cell.getpixel((x,y)))
  advance+=x1-x0+1
 width=max(x for x,y in base_ink)+1;left=(176-width*2)//2
 ink={(x*2+dx+left,y*2+dy+3) for x,y in base_ink for dx in (0,1) for dy in (0,1)}
 # Preserve the title's white rim, turquoise face and dark lower edge.
 edge=c.raster.dilate(ink,176,32)
 rim=c.raster.dilate(edge,176,32)-edge
 for x,y in rim:after[y][x]=15
 for x,y in edge-ink:after[y][x]=4
 for x,y in ink:after[y][x]=7 if y<12 else 6 if y<20 else 5
 assert all(0<x<175 and 0<y<31 for x,y in ink|edge|rim)
 graphics=title_encode(after);assert title_canvas(graphics)==after
 resource[pr:pr]=graphics;struct.pack_into('<I',resource,12,pr+len(graphics))
 for p in positions:resource[p:p+len(needle)]=struct.pack('<88H',*range(89,177))
 assert not any(parent[TITLE_CLONE:TITLE_CLONE+len(resource)])
 assert resource[gr:gr+len(atlas)]==atlas and resource[pr+len(graphics):]==parent[source+pr:source+resource_end]
 write(TITLE_CLONE,resource);assert c.u32(parent,0x1A3BC)==0x8000000+source;write(0x1A3BC,struct.pack('<I',0x8000000+TITLE_CLONE))
 colors=c.raster.palette_rgb(states[1][0xAC0:0xAE0]);colors[0]=(32,32,32)
 c.gallery([('Stage clear',c.raster.render_canvas(before+after,colors))],OUT/'stage_clear_before_after.png',4)
 reports['stage_clear']={'source':hex(source),'clone':hex(TITLE_CLONE),'korean':'스테이지 클리어','animation_lookup_frames':len(positions),'private_source_tiles':[89,176],'VRAM_title_tiles_preserved':88,'original_atlas_and_bars_preserved':True}
 # Re-extract using both observed wait variants, then add all resulting omissions.
 extracted=extract.extract(paths.ORIGINAL_ROM,dec.CHARMAP_12X12_PATH);ids={r['record_id'] for r in merged['records']}
 missing=[r for r in extracted['records'] if r['record_id'] not in ids]
 assert {r['record_id'][-8:] for r in missing}==set(TRANSLATIONS)
 assert not any(parent[TEXT_START:TEXT_END]) and not any(parent[TABLE_START:TABLE_END])
 charmap=dec.load_identified_slot_to_char(dec.CHARMAP_12X12_PATH);charmap.update(dec.CORRECTED_LOW_KANA)
 reverse={}
 for s,ch in charmap.items():reverse.setdefault(ch,s)
 dictionary=load_dictionary(jp,DICT_12X12_BASE,DICT_12X12_END)
 chars=set(''.join(line for lines in TRANSLATIONS.values() for line in lines))-{' '};slots={};painted=[];occupied=set()
 _,live12=prev.unified.collect_live_slots(jp,merged['records'])
 for ch in sorted(chars):
  if '가'<=ch<='힣':
   wanted=glyph.packed_12x12(ch,font);slot=prev.try_recover(glyph.recover_unique_12x12_slots,candidate,font,ch)
  else:
   native=prev.FULLWIDTH.get(ch,ch);native=chr(ord(ch)+0xFEE0) if ch.isascii() and ch.isdigit() else native
   src=reverse.get(native,reverse.get(ch));assert src is not None,(ch,native)
   wanted=jp[glyph.fontops.FONT_12X12_BASE+src*18:glyph.fontops.FONT_12X12_BASE+(src+1)*18]
   hits=[s for s in range(glyph.fontops.FONT_12X12_COUNT) if glyph.slot_raw(candidate,glyph.FONT12_RELOCATED,s,18)==wanted];slot=hits[0] if hits else None
  if slot is None:
   slot=prev.choose_free_12x12(candidate,jp,live12,occupied);write(glyph.FONT12_RELOCATED+slot*18,wanted);painted.append({'char':ch,'slot':hex(slot)})
  slots[ch]=slot;occupied.add(slot);assert glyph.slot_raw(candidate,glyph.FONT12_RELOCATED,slot,18)==wanted
 h=hook.find_hook_table(parent);lookup=hook.load_lookup(parent,h['table_address'],h['count']);oldlookup=dict(lookup);cursor=TEXT_START;texts=[]
 prev.BATCH_ID='ss-next-wait-dialogue-20260907'
 for rawrow in missing:
  rawrow=copy.deepcopy(rawrow);rawrow['source_text_seed']=rawrow['source_text_seed'].replace('<02A5>','健');rawrow['unresolved_slots']=[]
  for part in rawrow['segments']:part['source_text']=part['source_text'].replace('<02A5>','健');part['unresolved_slots']=[]
  row,owner=sheet.build_record(rawrow,sha(jp));lines=TRANSLATIONS[row['record_id'][-8:]];assert len(lines)==len(row['segments'])
  original_cursor=int(row['target_file_offset'],16);segments=[]
  for part,line in zip(row['segments'],lines):
   assert len(line)<=15,(line,len(line))
   original_raw=bytes.fromhex(part['raw_hex']);assert jp[original_cursor:original_cursor+len(original_raw)]==original_raw
   payload=prev.encode_text(line,slots,{});write(cursor,payload)
   assert 0x8000000+original_cursor not in lookup
   lookup[0x8000000+original_cursor]=(0x8000000+cursor,0x8000000+original_cursor+len(original_raw)-1)
   actual=expand_to_slots(read_tokens(candidate,cursor)[0],dictionary);assert actual==[1 if ch==' ' else slots[ch] for ch in line]
   segments.append({'original':hex(original_cursor),'payload':hex(cursor),'japanese':part['source_text'],'korean':line,'cells':len(line)})
   cursor+=len(payload);original_cursor+=len(original_raw)
  row['translation_segments']=lines;prev.mark_row(row,row['source_text'],'\n'.join(lines),'Wait/pause print missed by extractor; literal 12x12 glyphs verified against active ROM.')
  row['qa_status']='static_rom_verified';prev.update_payload_hash(row);merged['records'].append(row);merged['owners'].append(owner);texts.append({'record_id':row['record_id'],'segments':segments})
 assert cursor<TEXT_END
 table=b''.join(struct.pack('<III',o,n,e) for o,(n,e) in sorted(lookup.items()));assert TABLE_START+len(table)<TABLE_END
 write(TABLE_START,table);write(h['word_offset'],struct.pack('<II',0x8000000+TABLE_START,len(lookup)))
 h2=hook.find_hook_table(candidate);check=hook.load_lookup(candidate,h2['table_address'],h2['count']);assert check==lookup and all(check[k]==v for k,v in oldlookup.items())
 reports['dialogue']={'boxes':texts,'new_box_count':len(texts),'new_line_count':len(lookup)-len(oldlookup),'existing_lookup_entries_preserved':len(oldlookup),'new_table':hex(TABLE_START),'painted_glyphs':painted}
 # Proof sheets use the exact emitted ROM font cells.
 all_lines=[s for r in texts for s in r['segments']];proof=Image.new('RGB',(240,len(all_lines)*18),(255,255,160));draw=ImageDraw.Draw(proof)
 for i,line in enumerate(all_lines):
  for n,ch in enumerate(line['korean']):
   if ch==' ':continue
   cell=glyph.fontops.unpack_12x12(glyph.slot_raw(candidate,glyph.FONT12_RELOCATED,slots[ch],18));proof.paste((65,65,0),(n*12,i*18),cell)
 proof.resize((720,proof.height*3),Image.Resampling.NEAREST).save(OUT/'dialogue_actual_rom_glyphs.png')
 # Exact-scope verification; original script and old table remain untouched.
 assert candidate[0xF00000:0xFC0000]==parent[0xF00000:0xFC0000]
 changes={i for i,(a,b) in enumerate(zip(parent,candidate)) if a!=b};assert changes<=allowed and len(candidate)==len(parent)
 output=OUT/'ggen_ss1_ss4_next_ko_20260907.gba';output.write_bytes(candidate)
 assert paths.MAIN_TIP_ROM.read_bytes()==parent and paths.TRANSLATION_MERGED_JSON.read_bytes()==sheetbytes,'concurrent change'
 (OUT/'translation_before.json').write_bytes(sheetbytes);shutil.copy2(paths.TRANSLATION_MANIFEST,OUT/'translation_manifest_before.json')
 identity=merged['identity'];oldidentity=identity.get('translation_overlay_identity_sha256','');identity['parent_translation_overlay_identity_sha256']=oldidentity
 identity['translation_overlay_identity_sha256']=prev.digest({'parent':oldidentity,'batch':prev.BATCH_ID,'records':texts});identity['ss_next_added_record_identity_sha256']=prev.digest(texts)
 sheet.recount(merged);merged['summary']['translation_overlay_identity_sha256']=identity['translation_overlay_identity_sha256']
 snapshot=OUT/'translation_after.json';save(snapshot,merged);paths.TRANSLATION_MERGED_JSON.write_bytes(snapshot.read_bytes());prev.update_translation_manifest(merged,snapshot)
 manifest={'parent':{'sha256':sha(parent)},'output':{'path':paths.advance_relative(output),'sha256':sha(candidate),'size':len(candidate)},**reports,'verification':{'result':'PASS','scope_verified':True,'changed_bytes':len(changes),'original_script_preserved':True,'old_lookup_preserved':True,'runtime':'Static ROM verification and derived graphics previews; emulator re-entry not run'}}
 save(OUT/'manifest.json',manifest);print(json.dumps({'output':manifest['output'],'verification':manifest['verification'],'dialogue_boxes':len(texts),'painted_glyphs':painted},ensure_ascii=False,indent=2))
if __name__=='__main__':sys.stdout.reconfigure(encoding='utf-8');main()
