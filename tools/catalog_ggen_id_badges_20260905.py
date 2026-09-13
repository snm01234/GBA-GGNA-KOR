from ggen_ss_tiles_common_20260905 import *
import analyze_ggen_advance_settings_suspend_ui as sprite
import analyze_ggen_advance_develop_menu_buttons_state_20260901 as pkg
OUT=ROOT/'outputs/20260905_ggen_ss5_ss7_tiles'
r=(ROOT/'SD Gundam GGeneration Advance (Korean).gba').read_bytes();items=[];rows=[]
sig=r[0xc36910:0xc36910+20]
for off in range(0xc30000,0xc50000,4):
 if r[off:off+20]!=sig:continue
 gr,recs=sprite.animation_records(r,off+0x8000000)
 g=r[off+0x384:off+0x664];colors=raster.palette_rgb(r[off+0x664:off+0x684])
 print(hex(off))
 c=sem.stitch(g,{'width':4,'height':2,'cells':list(range(15,23))})
 items.append((hex(off),raster.render_canvas(c,colors)));rows.append(hex(off))
gallery(items,OUT/'id_family.png',5)

