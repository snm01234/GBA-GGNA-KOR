"""Three-way merge the concurrent landform fix with ss5/ss7 graphics."""
from ggen_ss_tiles_common_20260905 import *
import json,hashlib,binascii,shutil,subprocess,sys
def sha(b):return hashlib.sha256(b).hexdigest()
dest=ROOT/'outputs/20260905_ggen_ss5_ss7_tiles'
basepath=ROOT/'integrated/main_tip/backups/20260905T094531Z_user_verified_landform_evade_ko_20260905/SD Gundam GGeneration Advance (Korean).gba'
latestpath=ROOT/'integrated/main_tip/backups/20260905T094533Z_user_requested_ss5_ss7_tiles_preemptive_condensed_20260905/SD Gundam GGeneration Advance (Korean).gba'
ourpath=dest/'ggen_ss5_ss7_tiles_ko_20260905.gba'
base=basepath.read_bytes();latest=latestpath.read_bytes();ours=ourpath.read_bytes()
manifest=json.loads((dest/'manifest.json').read_text(encoding='utf-8'))
assert sha(base)==manifest['parent']['sha256']
assert sha(latest)=='885bdc7afdb6c192afd721bf8cfd4741699e49c8973173590104559505ae5bbb'
merged=bytearray(latest);ours_count=other_count=0
for i,(b,o,l) in enumerate(zip(base,ours,latest)):
 if o!=b:
  assert l in (b,o),f'overlapping concurrent edit at {i:x}'
  merged[i]=o;ours_count+=1
 if l!=b:other_count+=1
assert other_count==158
assert all(merged[i]==l for i,(b,l) in enumerate(zip(base,latest)) if b!=l)
target=dest/'ggen_ss5_ss7_tiles_ko_latest_20260905.gba';target.write_bytes(merged)
manifest['parent']={'sha256':sha(latest),'path':str(latestpath.relative_to(ROOT))}
manifest['output']={'path':str(target.relative_to(ROOT)),'sha256':sha(merged),'size':len(merged)}
manifest['verification']['three_way_merge_conflicts']=0
manifest['verification']['concurrent_landform_fix_preserved_bytes']=other_count
manifest['verification']['changed_bytes_from_latest']=ours_count
outmanifest=dest/'manifest_latest.json';outmanifest.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
for n in (5,7):
 src=ourpath.with_suffix(f'.ss{n}');st,_=statefmt.parse_png_state(src);fixed=bytearray(st);struct.pack_into('<I',fixed,8,binascii.crc32(merged)&0xffffffff)
 target.with_suffix(f'.ss{n}').write_bytes(raster.replace_state_chunk(src,bytes(fixed)))
shutil.copy2(ROOT/'SD Gundam GGeneration Advance (Korean).sav',target.with_suffix('.sav'))
assert (ROOT/'SD Gundam GGeneration Advance (Korean).gba').read_bytes()==ours,'main changed again; preserve and rebase'
subprocess.run([sys.executable,str(ROOT/'tools/promote_ggen_advance_main_tip.py'),'--candidate',str(target),'--candidate-manifest',str(outmanifest),'--reason','user_requested_ss5_ss7_preserving_latest_landform_20260905'],check=True)
assert (ROOT/'SD Gundam GGeneration Advance (Korean).gba').read_bytes()==merged
print('MERGE PASS',sha(merged),'preserved concurrent bytes',other_count)
