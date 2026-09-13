"""Import the approved 251x129 logo into the 8bpp title BG resource.

Uses an ImageGen-restored space plate and the supplied logo without redrawing
its lettering. All three title-load references are redirected together.
"""
from ggen_ss_tiles_common_20260905 import *
from ggen_advance_project_paths import MAIN_TIP_ROM, MAIN_TIP_MANIFEST
import render_ggen_ss_tiles_20260905 as renderer
import hashlib, json

DEST=ROOT/'outputs/20260906_ggen_title_logo_ko'
ASSETS=ROOT/'outputs/20260906_ggen_title_logo_check'
SOURCE=0xCCAB18
TARGET=0x1FC0000
OWNERS=[0x26CD4,0x26D68,0x2703C]

def sha(b):return hashlib.sha256(b).hexdigest()

def image_from_raw(raw,palette):
 im=Image.new('RGB',(240,160));px=im.load()
 for y in range(160):
  for x in range(240):
   idx=raw[((y//8)*30+x//8)*64+(y%8)*8+x%8]
   v=u16(palette,idx*2)
   px[x,y]=tuple(((v>>k)&31)*255//31 for k in (0,5,10))
 return im

def main():
 DEST.mkdir(exist_ok=True)
 parent=MAIN_TIP_ROM.read_bytes()
 assert sha(parent)==json.loads(MAIN_TIP_MANIFEST.read_text(encoding='utf8'))['sha256']
 statepath=ROOT/'SD Gundam GGeneration Advance (Korean).ss1'
 st,_=statefmt.parse_png_state(statepath)
 assert parent[SOURCE:SOURCE+16].hex()=='10001e141000b004c004c14384480002'
 assert raster.pointer_hits(parent,0x08000000+SOURCE)==OWNERS
 oldraw=sem.lzss_decompress(parent[SOURCE+0x4C0:SOURCE+0x4C0+0x43C1])
 assert len(oldraw)==38400 and st[0x1000:0xA600]==oldraw
 oldpal=parent[SOURCE+0x4884:SOURCE+0x4A84]
 assert st[0x800:0xA00]==oldpal
 assert list(struct.unpack_from('<600H',parent,SOURCE+16))==list(range(600))
 original=image_from_raw(oldraw,oldpal)
 background=Image.open(ASSETS/'restored_space_background.png').convert('RGB').resize((240,160),Image.Resampling.LANCZOS)
 # Keep the original lower menu backdrop, with a short transition above it.
 p=background.load();q=original.load()
 for y in range(116,160):
  weight=min(1,(y-116)/8)
  for x in range(240):p[x,y]=tuple(round(a*(1-weight)+b*weight) for a,b in zip(p[x,y],q[x,y]))
 background.save(DEST/'background_native.png')
 logo=Image.open(ASSETS/'GGNA_KO_LOGO_251x129.png').convert('RGBA')
 assert logo.size==(251,129) and logo.getchannel('A').getbbox()==(6,11,245,121)
 canvas=background.convert('RGBA');canvas.alpha_composite(logo,(-6,0))
 canvas.convert('RGB').save(DEST/'composite_before_quantization.png')
 indexed=canvas.convert('RGB').quantize(colors=256,method=Image.Quantize.MEDIANCUT,dither=Image.Dither.NONE)
 rgbpal=indexed.getpalette();palette=bytearray()
 for i in range(256):
  red,green,blue=rgbpal[i*3:i*3+3]
  palette.extend(struct.pack('<H',round(red*31/255)|(round(green*31/255)<<5)|(round(blue*31/255)<<10)))
 pixels=indexed.load()
 raw=bytes(pixels[tx*8+x,ty*8+y] for ty in range(20) for tx in range(30) for y in range(8) for x in range(8))
 assert len(raw)==38400 and 0x4C0+len(raw)+512<65536
 blob=bytearray(parent[SOURCE:SOURCE+0x4C0])
 struct.pack_into('<H',blob,0,0) # 8bpp loader's native uncompressed DMA path
 struct.pack_into('<H',blob,10,len(raw));struct.pack_into('<H',blob,12,0x4C0+len(raw))
 blob.extend(raw);blob.extend(palette)
 assert all(v==0 for v in parent[TARGET:TARGET+len(blob)])
 candidate=bytearray(parent);candidate[TARGET:TARGET+len(blob)]=blob
 for owner in OWNERS:struct.pack_into('<I',candidate,owner,TARGET+0x08000000)
 # Byte-for-byte exclusion audit, including all earlier Korean patches.
 cursor=0
 for start,end in sorted([(p,p+4) for p in OWNERS]+[(TARGET,TARGET+len(blob))]):
  assert candidate[cursor:start]==parent[cursor:start];cursor=end
 assert candidate[cursor:]==parent[cursor:]
 result=DEST/'ggen_title_logo_ko_20260906.gba';result.write_bytes(candidate)
 derived=bytearray(st);derived[0x1000:0xA600]=raw;derived[0x800:0xA00]=palette
 assert derived[0xA00:0x1000]==st[0xA00:0x1000] # OBJ palette and sprite attributes
 assert derived[0x11000:0x19000]==st[0x11000:0x19000] # all menu sprite tiles
 result.with_suffix('.ss1').write_bytes(raster.replace_state_chunk(statepath,derived))
 renderer.OUT=DEST
 renderer.render(st).resize((480,320),Image.Resampling.NEAREST).save(DEST/'before.png')
 renderer.render(derived).resize((480,320),Image.Resampling.NEAREST).save(DEST/'after.png')
 decoded=image_from_raw(candidate[TARGET+0x4C0:TARGET+0x4C0+38400],candidate[TARGET+0x4C0+38400:TARGET+len(blob)])
 decoded.save(DEST/'title_native.png')
 assert renderer.render(derived).size==(240,160)
 manifest={'parent_sha256':sha(parent),'reference_state_sha256':sha(statepath.read_bytes()),
  'output':{'path':str(result.relative_to(ROOT)),'size':len(candidate),'sha256':sha(candidate)},
  'resource':{'original':hex(SOURCE),'replacement':hex(TARGET),'owners':[hex(p) for p in OWNERS],'bytes':len(blob),'format':'8bpp uncompressed, 600 tiles, RGB555 palette'},
  'logo':{'path':str((ASSETS/'GGNA_KO_LOGO_251x129.png').relative_to(ROOT)),'sha256':sha((ASSETS/'GGNA_KO_LOGO_251x129.png').read_bytes()),'size':[251,129],'position':[-6,0],'visible_ink_bounds':[0,11,239,121]},
  'background':{'path':str((ASSETS/'restored_space_background.png').relative_to(ROOT)),'method':'ImageGen removed original logo; original lower menu backdrop retained'},
  'verification':{'result':'PASS','source_matches_updated_ss1':True,'only_title_owners_and_private_asset_changed':True,'obj_menu_palette_oam_and_tiles_unchanged':True,'original_source_resource_preserved':True,'original_save_state_preserved':True,'all_three_title_reload_pointers_redirected':True,'runtime':'Static ROM/state render verified; live boot/menu transition test pending'}}
 (DEST/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
 print(json.dumps(manifest,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
