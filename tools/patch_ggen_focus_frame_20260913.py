"""Unify develop/dismantle execute and cancel focus chrome with supply."""
import json,struct
from PIL import Image
import patch_ggen_ss1_ss9_20260912 as common
ROOT=common.ROOT;OUT=ROOT/'outputs/20260913_focus_frame'
EXPECTED='8636d8fe8df37715fa3c1fe518f196ceb722f501102bbf4fded2798c449dfaf9'
btn=common.btn;cat=common.cat
def canvas(rom,row):
 start=btn.CLONES[row['package']];h=btn.analysis.parse_resource_header(rom,0x8000000+start)
 _,records=btn.sprite.animation_records(rom,0x8000000+start)
 p,ids,lookup=cat.parse_anim(records,row['anim'])
 return btn.analysis.stitch(h['graphics'],p,ids,list(row['objects'])),h,p,lookup
def main():
 OUT.mkdir(parents=True,exist_ok=True)
 parent=(ROOT/'SD Gundam GGeneration Advance (Korean).gba').read_bytes();assert common.sha(parent)==EXPECTED
 rows=cat.enumerate_buttons((ROOT/'SD Gundam GGeneration Advance (Japan).gba').read_bytes())
 ref=next(r for r in rows if r['package']=='supply' and r['ko']=='캔슬' and r['face']==12 and r['kind']=='64')
 template,*_=canvas(parent,ref)
 clean=[[template[y][8] if v in (1,12) else v for v in line] for y,line in enumerate(template)]
 assert all(any(v in (8,9) for v in line[:4]) and any(v in (8,9) for v in line[-4:]) for line in clean)
 cand=bytearray(parent);allowed=set();changes=[];expected={};previews=[]
 targets=[r for r in rows if r['package'] in ('develop','dismantle_popup') and r['kind']=='64' and r['face']==12]
 assert len(targets)==4
 for package in ('develop','dismantle_popup'):
  start=btn.CLONES[package];h=btn.analysis.parse_resource_header(parent,0x8000000+start)
  clone=bytearray(parent[start:start+h['graphics_rel']]);graphics=bytearray(h['graphics'])
  for row in targets:
   if row['package']!=package:continue
   old,_,p,lookup=canvas(parent,row)
   new=[[v if v in (1,12) else clean[y][x] for x,v in enumerate(line)] for y,line in enumerate(old)]
   assert all((old[y][x] if old[y][x] in (1,12) else 0)==(new[y][x] if new[y][x] in (1,12) else 0) for y in range(16) for x in range(64))
   objs=p['objects'];gx=min(objs[i]['x'] for i in row['objects']);gy=min(objs[i]['y'] for i in row['objects'])
   for local,idx in enumerate(row['objects']):
    obj=objs[idx];wt=obj['size_px'][0]//8;ht=obj['size_px'][1]//8
    for ty in range(ht):
     for tx in range(wt):
      payload=btn.tile_payload(new,obj,gx,gy,tx,ty);tid=len(graphics)//32;graphics.extend(payload)
      struct.pack_into('<H',clone,lookup-start+(row['lookup_object_bases'][local]+ty*wt+tx)*2,tid)
   key=(package,row['anim'],tuple(row['objects']));expected[key]=new
   changes.append(dict(package=package,animation=row['anim'],objects=list(row['objects']),label=row['ko'],changed_pixels=sum(a!=b for ar,br in zip(old,new) for a,b in zip(ar,br))))
   previews.append((old,new,h['palettes'],row['bank']))
  struct.pack_into('<I',clone,12,h['graphics_rel']+len(graphics));clone.extend(graphics);clone.extend(h['palettes'])
  assert len(clone)<0x8000 and not any(parent[start+h['resource_bytes']:start+len(clone)])
  cand[start:start+len(clone)]=clone;allowed.update(range(start,start+len(clone)))
 unchanged=0
 for row in rows:
  key=(row['package'],row['anim'],tuple(row['objects']));old,oh,*_=canvas(parent,row);new,nh,*_=canvas(cand,row)
  assert oh['palettes']==nh['palettes']
  if key in expected:assert new==expected[key]
  else:assert new==old;unchanged+=1
 changed={i for i,(a,b) in enumerate(zip(parent,cand)) if a!=b};assert changed<=allowed
 preview=Image.new('RGB',(512,len(previews)*64))
 for i,(old,new,pal,bank) in enumerate(previews):
  preview.paste(cat.canvas_image(old,pal,bank,4),(0,i*64));preview.paste(cat.canvas_image(new,pal,bank,4),(256,i*64))
 preview.save(OUT/'before_after.png')
 path=OUT/'ggen_focus_frame_20260913.gba';path.write_bytes(cand)
 report=dict(parent_sha256=EXPECTED,output=dict(path=path.relative_to(ROOT).as_posix(),sha256=common.sha(cand),size=len(cand)),changes=changes,changed_bytes=len(changed),verification=dict(result='PASS',reference='supply focus cancel chrome',closed_left_and_right_edges=True,glyph_pixels_unchanged=True,resource_roundtrip=True,unchanged_button_variants=unchanged,palettes_unchanged=True,unrelated_bytes_preserved=True,runtime='ROM tile reconstruction; not emulator playback'))
 (OUT/'manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps(report,ensure_ascii=True))
if __name__=='__main__':main()
