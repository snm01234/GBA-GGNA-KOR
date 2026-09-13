#!/usr/bin/env python3
"""Redirect the actual save-progress runtime consumer to the Korean clone."""
from __future__ import annotations

import argparse, hashlib, json, shutil, struct, sys
from pathlib import Path
THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))
import analyze_ggen_advance_settings_suspend_ui as sprite
from ggen_advance_project_paths import ADVANCE_ROOT, MAIN_TIP_MANIFEST, MAIN_TIP_ROM, advance_relative

ROM_BASE = 0x08000000
PARENT = ADVANCE_ROOT / "outputs/20260831_ggen_advance_load_summary_ui/ggen_advance_load_summary_ui_ko_save_progress_followup_candidate_20260831.gba"
PARENT_SHA256 = "a88b7bd56662381f0f1bd4295dfccdee9a3f81dbb12396bfa705155937bf7a36"
PARENT_SAV = ADVANCE_ROOT / "outputs/20260831_ggen_advance_load_summary_ui/ggen_advance_load_summary_ui_ko_save_progress_followup_candidate_20260831.sav"
ANALYSIS = ADVANCE_ROOT / "legacy/analysis/ggen_advance_save_progress_runtime_owner_followup_20260831.json"
OUT_DIR = ADVANCE_ROOT / "outputs/20260831_ggen_advance_load_summary_ui"
DEFAULT_OUT = OUT_DIR / "ggen_advance_load_summary_ui_ko_save_progress_runtime_owner_candidate_20260831.gba"
DEFAULT_SAV = OUT_DIR / "ggen_advance_load_summary_ui_ko_save_progress_runtime_owner_candidate_20260831.sav"
DEFAULT_MANIFEST = ADVANCE_ROOT / "legacy/analysis/ggen_advance_save_progress_runtime_owner_fix_ko_20260831.json"

SHARED_RESOURCE = 0x0928C000
KOREAN_RESOURCE = 0x09298000
ACTUAL_LITERAL = 0x0007385C
PREVIOUS_LITERAL = 0x0001212C
UNRELATED_SHARED_LITERALS = (0x000121CC, 0x00026B6C)
TARGET_ANIMATION = 10
SAFE_ANIMATIONS = (1, 3, 4, 5, 6, 7)


def gate(ok: bool, msg: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {msg}")

def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()

def u16(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]

def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]

def record(data: bytes, resource: int, animation: int) -> bytes:
    return sprite.animation_records(data, resource)[1][animation][1]

def changed_ranges(offsets: list[int]) -> list[list[str]]:
    if not offsets: return []
    out=[]; start=prev=offsets[0]
    for x in offsets[1:]:
        if x != prev+1:
            out.append([f"0x{start:08X}", f"0x{prev+1:08X}"]); start=x
        prev=x
    out.append([f"0x{start:08X}", f"0x{prev+1:08X}"])
    return out


def main() -> int:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", type=Path, default=PARENT)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--out-sav", type=Path, default=DEFAULT_SAV)
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args=ap.parse_args()
    for p in (args.input, PARENT_SAV, ANALYSIS, MAIN_TIP_ROM, MAIN_TIP_MANIFEST):
        gate(p.is_file(), f"missing input: {p}")
    parent=args.input.read_bytes()
    gate(len(parent)==32*1024*1024 and sha256(parent)==PARENT_SHA256, f"parent hash drift: {sha256(parent)}")
    analysis=json.loads(ANALYSIS.read_text(encoding="utf-8"))
    gate(analysis.get("result")=="PASS" and analysis["candidate"]["sha256"]==PARENT_SHA256, "runtime-owner analysis binding failed")
    gate(analysis["runtime_sprite"]["resource_pointer"]==f"0x{SHARED_RESOURCE:08X}" and analysis["runtime_sprite"]["animation_field_11"]==10, "fresh state runtime proof drift")
    gate(analysis["obj_vram_match"]["shared_resource_animation10"]=={"exact":122,"total":122}, "fresh state shared match drift")

    main_tip=MAIN_TIP_ROM.read_bytes(); mm=json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(main_tip)==mm.get("sha256"), "main TIP/manifest drift")
    gate(u32(parent,PREVIOUS_LITERAL)==KOREAN_RESOURCE, "previous redirect drift")
    gate(u32(parent,ACTUAL_LITERAL)==SHARED_RESOURCE, "actual literal parent drift")
    for ref in UNRELATED_SHARED_LITERALS:
        gate(u32(parent,ref)==SHARED_RESOURCE, f"unrelated shared literal drift 0x{ref:08X}")
    gate(u16(parent,0x73818)==0x4810, "0x08073818 LDR drift")
    gate(u16(parent,0x7387E)==0x200A and u16(parent,0x73880)==0x7460, "animation10 setter drift")

    for anim in SAFE_ANIMATIONS:
        gate(record(parent,SHARED_RESOURCE,anim)==record(parent,KOREAN_RESOURCE,anim), f"non-target animation {anim} differs")
        rr=record(parent,KOREAN_RESOURCE,anim)
        for sid in range(225,229):
            gate(struct.pack("<H",sid) not in rr, f"non-target animation {anim} references implicit Korean source {sid}")
    gate(record(parent,SHARED_RESOURCE,TARGET_ANIMATION)!=record(parent,KOREAN_RESOURCE,TARGET_ANIMATION), "target animation10 is not remapped")

    candidate=bytearray(parent)
    struct.pack_into("<I",candidate,ACTUAL_LITERAL,KOREAN_RESOURCE)
    gate(u32(candidate,ACTUAL_LITERAL)==KOREAN_RESOURCE, "actual redirect failed")
    changed=[i for i,(a,b) in enumerate(zip(parent,candidate)) if a!=b]
    gate(changed and all(ACTUAL_LITERAL<=i<ACTUAL_LITERAL+4 for i in changed), f"patch escaped actual literal: {changed[:16]}")
    for ref in UNRELATED_SHARED_LITERALS:
        gate(u32(candidate,ref)==SHARED_RESOURCE, f"unrelated shared consumer changed 0x{ref:08X}")

    args.out.parent.mkdir(parents=True,exist_ok=True); args.out.write_bytes(candidate)
    shutil.copy2(PARENT_SAV,args.out_sav); gate(args.out_sav.read_bytes()==PARENT_SAV.read_bytes(), "SAV copy drift")
    output=bytes(candidate)
    manifest={
        "schema_version":1,"kind":"ggen_advance_save_progress_runtime_owner_fix_ko_20260831","result":"PASS",
        "source":{"parent":advance_relative(args.input),"parent_sha256":sha256(parent),"fresh_state_analysis":advance_relative(ANALYSIS),"fresh_state3_sha256":analysis["fresh_state3"]["sha256"],"canonical_main_tip_sha256":sha256(main_tip)},
        "root_cause":analysis["root_cause"],
        "patch":{"actual_consumer_instruction":"0x08073818","literal_file_offset":f"0x{ACTUAL_LITERAL:08X}","before":f"0x{SHARED_RESOURCE:08X}","after":f"0x{KOREAN_RESOURCE:08X}","previous_0x1212C_redirect_preserved":True,"unrelated_shared_consumers_preserved":[f"0x{x:08X}" for x in UNRELATED_SHARED_LITERALS],"runtime_path_animations_safe":list(SAFE_ANIMATIONS),"target_animation":10},
        "translations":{"セーブ中です":"세이브중입니다","電源を切らないでください":"전원을 끄지말아주세요"},
        "output":{"rom":advance_relative(args.out),"rom_sha256":sha256(output),"rom_size":len(output),"sav":advance_relative(args.out_sav),"sav_sha256":sha256(args.out_sav.read_bytes()),"changed_bytes":len(changed),"changed_ranges":changed_ranges(changed)},
        "verification":{"result":"PASS","fresh_real_run_state_owned_by_0x08073818":True,"fresh_state_shared_animation10_match":"122/122","actual_runtime_literal_redirected":True,"only_actual_literal_bytes_changed":True,"main_tip_unchanged":True}}
    args.manifest.parent.mkdir(parents=True,exist_ok=True); args.manifest.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"result":"PASS","rom":str(args.out),"rom_sha256":manifest["output"]["rom_sha256"],"sav":str(args.out_sav),"manifest":str(args.manifest),"changed_bytes":len(changed),"redirect":f"0x{SHARED_RESOURCE:08X} -> 0x{KOREAN_RESOURCE:08X}"},ensure_ascii=False,indent=2))
    return 0

if __name__=="__main__": raise SystemExit(main())
