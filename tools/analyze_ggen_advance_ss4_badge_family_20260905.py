#!/usr/bin/env python3
"""Read-only binding of ss4 lower badges (命中/反応 family) to ROM owners."""
from __future__ import annotations
import json, struct, sys
from pathlib import Path
THIS=Path(__file__).resolve().parent
if str(THIS) not in sys.path: sys.path.insert(0,str(THIS))
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
import analyze_ggen_advance_intermission_cycle_states_20260830 as bg
from ggen_ss_tiles_common_20260905 import direct, canvas_direct
from ggen_advance_project_paths import ADVANCE_ROOT

ROM=ADVANCE_ROOT/'SD Gundam GGeneration Advance (Korean).gba'
STATE=ADVANCE_ROOT/'SD Gundam GGeneration Advance (Korean).ss4'
OUT=ADVANCE_ROOT/'analysis'/'ggen_advance_ss4_badge_family_20260905.json'


def raw_obj_tile(st:bytes,tid:int)->bytes:
    base=statefmt.STATE_VRAM+statefmt.OBJ_VRAM+tid*32
    return bytes(st[base:base+32])

def raw_bg_tile(st:bytes, info:dict, tid:int)->bytes:
    base=statefmt.STATE_VRAM+info['char_base']+tid*32
    return bytes(st[base:base+32])

def overlap(a0,a1,b0,b1): return max(a0,b0)<min(a1,b1)

def main():
    rom=ROM.read_bytes(); st,_=statefmt.parse_png_state(STATE)
    dispcnt=struct.unpack_from('<H',st,statefmt.STATE_IO)[0]
    # Bottom strip where user screenshot shows fixed graphic badges.
    rect=(0,96,160,128)
    bg_rows={}
    for layer in range(4):
        if not(dispcnt&(0x100<<layer)): continue
        info=bg.bg_info(st,layer); vram=st[statefmt.STATE_VRAM:statefmt.STATE_IWRAM]
        cells=[]; raws={}
        for sy in range(rect[1],rect[3],8):
            row=[]
            for sx in range(rect[0],rect[2],8):
                wx,wy=sx+info['scroll_x'],sy+info['scroll_y']
                entry=bg.map_entry(vram,info['screen_base'],info['size'],wx//8,wy//8)
                tid=entry&0x3ff; pal=(entry>>12)&15
                raw=raw_bg_tile(st,info,tid)
                row.append({'screen':[sx,sy],'tile':tid,'pal':pal,'raw':raw.hex()})
                raws.setdefault(raw.hex(),[]).append([sx,sy,tid,pal])
            cells.append(row)
        bg_rows[str(layer)]={'info':info,'cells':cells,'raws':raws}
    oam=st[statefmt.STATE_OAM:statefmt.STATE_VRAM]
    objs=[]; live_raw={}
    for i in range(128):
        e=statefmt.parse_oam_entry(oam,i); a0=int(e['attr0'],16)
        if ((a0>>8)&3)==2: continue
        if not(overlap(e['x'],e['x']+e['width'],rect[0],rect[2]) and overlap(e['y'],e['y']+e['height'],rect[1],rect[3])): continue
        tile_ids=[]
        tw=e['width']//8; th=e['height']//8
        for ty in range(th):
            for tx in range(tw):
                tid=e['tile']+ty*(tw if dispcnt&0x40 else 32)+tx
                raw=raw_obj_tile(st,tid)
                tile_ids.append({'tile':tid,'raw':raw.hex()})
                if any(raw): live_raw.setdefault(raw,[]).append({'oam':i,'tile':tid,'x':e['x'],'y':e['y'],'w':e['width'],'h':e['height'],'pal':e['palette_bank']})
        objs.append({**e,'tiles':tile_ids})
    # Search all 0xA9xxxx direct descriptors for exact live OBJ/BG tile matches.
    wanted={bytes.fromhex(k):[{'kind':'obj',**v} for v in vals] for k,vals in [(raw.hex(),uses) for raw,uses in live_raw.items()]}
    for layer,data in bg_rows.items():
        for hx,uses in data['raws'].items():
            raw=bytes.fromhex(hx)
            if any(raw): wanted.setdefault(raw,[]).extend({'kind':'bg','layer':int(layer),'screen':u[:2],'tile':u[2],'pal':u[3]} for u in uses)
    owners=[]
    for off in range(0x00A90000,0x00AA0000,4):
        try:m=direct(rom,off)
        except Exception: continue
        hits=[]
        for tid in range(m['size']//32):
            raw=rom[m['graphics_offset']+tid*32:m['graphics_offset']+(tid+1)*32]
            if raw in wanted: hits.append({'source_tile':tid,'uses':wanted[raw]})
        if hits:
            c=canvas_direct(rom,m)
            owners.append({'owner':off,'width':m['width'],'height':m['height'],'graphics_offset':m['graphics_offset'],'graphics_size':m['size'],'palette_offset':m['palette_offset'],'hits':hits,'canvas_rows':[''.join(format(v,'X') for v in row) for row in c]})
    # BG1 badge cells: identify source compressed atlases by exact tile matches and coherent live-source delta.
    badge_cells=[]
    if '1' in bg_rows:
        for row in bg_rows['1']['cells']:
            for c in row:
                if c['screen'][1] in (104,112) and c['screen'][0] < 136 and int(c['raw'],16): badge_cells.append(c)
    live_by_raw={}
    for c in badge_cells: live_by_raw.setdefault(bytes.fromhex(c['raw']),[]).append(c)
    streams=[]
    for s in bg.accepted_streams(rom):
        dec=s['decoded']; lookup={}
        for sid in range(len(dec)//32): lookup.setdefault(dec[sid*32:(sid+1)*32],[]).append(sid)
        pairs=[]
        for raw,cells in live_by_raw.items():
            for sid in lookup.get(raw,[]):
                for c in cells: pairs.append((c['tile'],sid,c['screen'],c['pal']))
        if not pairs: continue
        from collections import Counter
        cnt=Counter(a-b for a,b,_,_ in pairs); delta,coh=cnt.most_common(1)[0]
        streams.append({'offset':s['offset'],'body_len':s['body_len'],'decoded_tiles':len(dec)//32,'exact_live_tiles':len({a for a,_,_,_ in pairs}),'dominant_delta':delta,'coherent_hits':coh,'pairs':[[a,b,xy,p] for a,b,xy,p in pairs if a-b==delta]})
    streams.sort(key=lambda r:(r['coherent_hits'],r['exact_live_tiles']),reverse=True)
    # Raw ROM positions are useful for direct/uncompressed duplicate families.
    raw_hits={}
    for raw,cells in live_by_raw.items():
        pos=[]; start=0
        while True:
            hit=rom.find(raw,start)
            if hit<0: break
            pos.append(hit); start=hit+1
            if len(pos)>=40: break
        raw_hits[raw.hex()]={'cells':[{k:v for k,v in c.items() if k!='raw'} for c in cells],'positions':pos}
    report={'dispcnt':hex(dispcnt),'rect':rect,'bg':bg_rows,'oam_objects':objs,'direct_owners':owners,'stream_matches':streams[:30],'raw_hits':raw_hits}
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'oam':[{'index':o['index'],'x':o['x'],'y':o['y'],'w':o['width'],'h':o['height'],'tile':o['tile'],'pal':o['palette_bank']} for o in objs], 'owners':[{'owner':hex(o['owner']),'size':[o['width'],o['height']],'gfx':hex(o['graphics_offset']),'hits':len(o['hits'])} for o in owners], 'streams':streams[:12]},ensure_ascii=False,indent=2))
if __name__=='__main__': main()
