"""Rebuild complete credit containers, including their empty-stream sentinel."""
import hashlib, json, struct
from pathlib import Path
from collections import Counter
import analyze_table_1c92e8 as table
import build_ggen_advance_unified_rom_poc as unified
import build_ggen_advance_ko_poc as fo
import ggen_advance_painted_glyph_identity as glyph
import ggen_advance_text_codec as codec
from merge_ggen_advance_translation_overlays import digest, translation_payload_digest

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs/20260912_ss123_credits'
BASE=0x8000000
sha=lambda b:hashlib.sha256(b).hexdigest()
# Offsets identify the original lines, including continuation lines without owners.
# Unconfirmed name readings are explicitly tracked in the translation data.
NAMES={
0x1c8e1e:('堀内 美康','호리우치 요시야스'),
0x1c8e38:('大野 聡','오노 사토시'),
0x1c8e40:('杉山 智則','스기야마 도모노리'),
0x1c8e53:('松田 隆','마쓰다 다카시'),
0x1c8e62:('杉山 剛','스기야마 고'),
0x1c8e71:('大田原 一博','오타하라 가즈히로'),
0x1c8e8e:('福田 正佳','후쿠다 마사요시'),
0x1c8ea6:('亀尾 司','가메오 쓰카사'),
0x1c8ebb:('石井 政幸','이시이 마사유키'),
0x1c8edc:('齋藤 秀教  永井 良明','사이토 히데유키  나가이 요시아키'),
0x1c8f00:('海野 貴明','우미노 다카아키'),
0x1c8f15:('池谷 俊之  佐藤 祐治','이케야 도시유키  사토 유지'),
0x1c8f2a:('縄村 竜一  小塚 久人','나와무라 류이치  고즈카 히사토'),
0x1c8f3d:('佐々木 徳俊','사사키 노리토시'),
0x1c8f54:('岡本 篤仁  山下 英之','오카모토 아쓰히토  야마시타 히데유키'),
0x1c8f75:('木村 さとみ  内山 幹','기무라 사토미  우치야마 쓰요시'),
0x1c8f95:('磯田 織江','이소다 오리에'),
0x1c8fa9:('安倍 政晴','아베 마사하루'),
0x1c8fbf:('川邉 照久','가와베 데루히사'),
0x1c8fc9:('藤社 陽実','후지코소 하루미'),
0x1c8fd9:('岡本 潤一郎  菊地 清香','오카모토 준이치로  기쿠치 기요카'),
0x1c8fee:('星野 協介   中西 悦子','호시노 교스케  나카니시 에쓰코'),
0x1c9003:('磯川 豊    山崎 徹','이소카와 유타카  야마자키 도루'),
0x1c9016:('秋山 靖成   田口 正和','아키야마 야스나리  다구치 마사카즈'),
0x1c902b:('仲野 聖人   小芦 隆','나카노 마사토  고아시 다카시'),
0x1c903e:('星野 英律','호시노 히데노리'),
0x1c9062:('作曲／音楽データ  河西 良','작곡/음악 데이터  가사이 료'),
0x1c907a:('音楽ディレクター  堀口 比呂志','음악 감독  호리구치 히로시'),
0x1c90c9:('安子 太樹','야스코 다이키'),
0x1c90d9:('澤田 悦己','사와다 요시미'),
0x1c90e3:('干川 耕司','호시카와 고지'),
0x1c90ed:('田中 穣','다나카 미노루'),
0x1c90f5:('ロープ熊田','로프 구마다'),
0x1c910a:('牛村 憲彦  後藤 能孝','우시무라 노리히코  고토 요시타카'),
0x1c9120:('岡本 吉弘  猪谷 公彦','오카모토 요시히로  이노타니 기미히코'),
0x1c9135:('ドラゴン鈴木  田中 庸介','드래곤 스즈키  다나카 노부유키'),
0x1c914a:('原田 真史  磯貝 健夫','하라다 마사시  이소가이 다케오'),
0x1c9160:('西澤 冬樹  永田 啓介','니시자와 후유키  나가타 게이스케'),
0x1c918f:('森田 彰啓','모리타 아키히로'),
0x1c9199:('堀口 滋','호리구치 시게루'),
0x1c91a2:('岡崎 昭行','오카자키 아키유키'),
0x1c91b8:('今西 智明','이마니시 도모아키'),
0x1c91c3:('松本 健','마쓰모토 겐'),
0x1c91d8:('東海林 隆','쇼지 다카시'),
0x1c91f3:('鵜之澤 伸','우노자와 신'),
0x1c9217:('片桐 圭一郎','가타기리 게이이치로'),
}
PROVISIONAL={0x1c8f15,0x1c8fbf,0x1c8fc9,0x1c8fee,0x1c902b,0x1c903e}
ROLES={0x1c8e29:'보조 프로듀서',0x1c8e7c:'메인/전투 프로그램',0x1c8ec6:'뷰/전투 이벤트 프로그램',0x1c91e3:'총괄 프로듀서',0x1c90fe:'스페셜 땡스'}
SOURCES=['https://raido.moe/staff/gba/gba_sd_gundam_ggeneration_advance.html','https://www.mobygames.com/game/61665/sd-gundam-g-generation-advance/credits/gameboy-advance/']

def main():
 OUT.mkdir(exist_ok=True)
 parent=(ROOT/'SD Gundam GGeneration Advance (Korean).gba').read_bytes()
 assert sha(parent)=='3efa0e3c992cea6ec0b8fd8702c8d635125cd5cfb56ebb7936c9e4a98a1e9b14'
 jp=(ROOT/'SD Gundam GGeneration Advance (Japan).gba').read_bytes()
 merged=json.loads((ROOT/'integrated/translation/ggen_advance_translation_merged.json').read_text(encoding='utf-8'))
 (OUT/'translation_before.json').write_text(json.dumps(merged,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 rows={int(r['target_file_offset'],16):r for r in merged['records']}
 groups=[]; jobs=[]
 for i in range(35,106):
  owner=0x1c92e8+4*i; ptr=table.u32(jp,owner)-BASE
  orig,_=table.parse_multiline_blob(jp,ptr)
  old,_=table.parse_multiline_blob(parent,table.u32(parent,owner)-BASE)
  group=dict(index=i,owner=owner,original_line_count=len(orig),previous_line_count=len(old),lines=[])
  for l in orig:
   off=int(l['offset'],16); r=rows[off]; source,ko=NAMES.get(off,(r['source_text'],ROLES.get(off,r['translation_ko'])))
   if len(ko)>18 and '  ' in ko:
    ko='  '.join(person.replace(' ','') for person in ko.split('  '))
   assert len(ko)<=18,(hex(off),ko)
   assert ko and '<' not in ko and not any('\u3040'<=c<='\u9fff' for c in ko),(hex(off),ko)
   r.update(source_text=source,source_decode_status='complete',source_unresolved_slots=[],translation_ko=ko,translation_status='translated',translation_policy='translate',translation_source='curated_project_data',overlay_batch_id='credits-complete-containers-20260912',translator_notes='일본어 인명 독음 한글 표기. 원본 컨테이너의 모든 줄과 종료 표식 보존.'+(' 독음 잠정: 공개 자료에서 독음 미확인.' if off in PROVISIONAL else ''),review_status='draft' if off in PROVISIONAL else 'reviewed',qa_status='static_verified')
   r['translation_payload_sha256']=translation_payload_digest(dict(r,batch_id=r['overlay_batch_id']))
   job=dict(offset=off,record_id=r['record_id'],source=source,ko=ko,reading_status='provisional' if off in PROVISIONAL else 'reference_checked' if off in NAMES else 'role')
   jobs.append(job);group['lines'].append(job)
  groups.append(group)
 child=bytearray(parent); allowed=set()
 def write(o,b):child[o:o+len(b)]=b;allowed.update(range(o,o+len(b)))
 font=glyph.load_galmuri12(); chars={c for j in jobs for c in j['ko'] if '가'<=c<='힣'}; slots={}; paints=[]
 _,live=unified.collect_live_slots(jp,merged['records'])
 for c in sorted(chars):
  wanted=glyph.packed_12x12(c,font)
  hits=[s for s in range(fo.FONT_12X12_COUNT) if child[glyph.FONT12_RELOCATED+s*18:glyph.FONT12_RELOCATED+(s+1)*18]==wanted]
  if hits:s=hits[0]
  else:
   safe=[s for s in range(unified.SLOT_MAX,unified.SLOT_MIN-1,-1) if s not in live|set(slots.values())|unified.SPECIAL_SLOTS|unified.RESERVED_GLYPH_SLOTS|{0x10a,0x143,0x71e,0x7db,0x7dc} and child[glyph.FONT12_RELOCATED+s*18:glyph.FONT12_RELOCATED+(s+1)*18]==jp[fo.FONT_12X12_BASE+s*18:fo.FONT_12X12_BASE+(s+1)*18]]
   assert safe,c;s=safe[0];write(glyph.FONT12_RELOCATED+s*18,wanted);paints.append(dict(char=c,slot=s));live.add(s)
  slots[c]=s
 verified=unified.load_verified_charmap(unified.CHARMAP_12X12_PATH)
 cursor=0x13d0000; assert not any(parent[cursor:cursor+0x4000])
 for g in groups:
  g['pointer']=BASE+cursor;blob=bytearray()
  for j in g['lines']:
   raw,missing=unified.encode_korean_text(j['ko'],slots,verified_charmap=verified,strict_punctuation=True)
   assert raw and not missing,(j,missing)
   j['pointer']=BASE+cursor+len(blob);j['encoded_hex']=raw.hex();blob.extend(raw)
  blob.append(0) # list terminator, distinct from the final line terminator
  write(cursor,blob);write(g['owner'],struct.pack('<I',BASE+cursor));cursor+=len(blob)
  parsed,end=table.parse_multiline_blob(child,g['pointer']-BASE)
  assert len(parsed)==g['original_line_count'] and end==len(blob),(g,end,len(blob))
  for p,j in zip(parsed,g['lines']):
   assert child[int(p['offset'],16):int(p['offset'],16)+p['byte_length']+1]==bytes.fromhex(j['encoded_hex'])
   tokens=codec.read_tokens(child,int(p['offset'],16))[0]
   assert len(tokens)==len(j['ko'])
   for c,t in zip(j['ko'],tokens):
    if '가'<=c<='힣':
     s=codec.normalized_slot(t);assert child[glyph.FONT12_RELOCATED+s*18:glyph.FONT12_RELOCATED+(s+1)*18]==glyph.packed_12x12(c,font)
 changed={i for i,(a,b) in enumerate(zip(parent,child)) if a!=b};assert changed<=allowed
 assert cursor<0x13d4000 and child[:0x1c9374]==parent[:0x1c9374]
 path=OUT/'ggen_credits_ko_20260912.gba';path.write_bytes(child)
 identity=merged.setdefault('identity',{});identity['parent_translation_overlay_identity_sha256']=identity.get('translation_overlay_identity_sha256');identity['translation_overlay_identity_sha256']=digest(jobs)
 merged['summary']['merged_translation_status_counts']=dict(Counter(r['translation_status'] for r in merged['records']))
 merged['summary']['translation_overlay_identity_sha256']=identity['translation_overlay_identity_sha256']
 snapshot=ROOT/'analysis/ggen_advance_translation_merged_20260912_credits.json';snapshot.write_text(json.dumps(merged,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 report=dict(output=dict(path=str(path.relative_to(ROOT)),size=len(child),sha256=sha(child)),parent_sha256=sha(parent),groups=groups,font_paints=paints,changed_bytes=len(changed),sources=SOURCES,verification=dict(result='PASS',all_71_containers_preserve_original_line_count=True,all_credits_hangul_glyphs_verified=True,changes_within_allowlist=True,runtime='pending'),translation_snapshot=str(snapshot.relative_to(ROOT)))
 (OUT/'manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps(dict(lines=len(jobs),groups=len(groups),font_paints=paints,output=report['output']),ensure_ascii=False))
if __name__=='__main__':main()
