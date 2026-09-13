#!/usr/bin/env python3
"""Build a current-main-TIP candidate with Yuu's 女の…声……？ line corrected."""

from __future__ import annotations
import hashlib, json, struct, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from patch_ggen_advance_map_script_inline_poc import encode_map_korean_line, load_identified_12x12  # noqa: E402

ROM_BASE = 0x08000000
RECORD_ID = "GGA-MAPSCRIPT-00F64189"
ORIGINAL_ADDRESS, EXPECTED_ORIGINAL_END = 0x08F64189, 0x08F64192
NEW_TEXT, ALLOCATION = "여자의…목소리……？", 0x012DC000
OUTPUT_DIR = ROOT / "outputs" / "20260902_yuu_dialogue_correction"
OUTPUT_ROM = OUTPUT_DIR / "ggen_advance_yuu_voice_main_tip_candidate_20260902.gba"
REPORT = ROOT / "analysis" / "ggen_advance_yuu_voice_main_tip_20260902.json"
MAIN_ROM = ROOT / "SD Gundam GGeneration Advance (Korean).gba"
MAIN_MANIFEST = ROOT / "integrated" / "main_tip" / "ggen_advance_main_tip_manifest.json"
MERGED = ROOT / "integrated" / "translation" / "ggen_advance_translation_merged.json"
APPLY_CHARMAP = ROOT / "analysis" / "ggen_advance_korean_apply_charmap_20260844.json"

def sha256(value: bytes) -> str: return hashlib.sha256(value).hexdigest()
def gate(condition: bool, message: str) -> None:
    if not condition: raise SystemExit(f"gate failed: {message}")

def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    before = MAIN_ROM.read_bytes()
    main_manifest = json.loads(MAIN_MANIFEST.read_text(encoding="utf-8"))
    merged = json.loads(MERGED.read_text(encoding="utf-8"))
    gate(len(before) == 32 * 1024 * 1024 and sha256(before) == main_manifest["sha256"], "main TIP/manifest drift")
    row = next((item for item in merged["records"] if item.get("record_id") == RECORD_ID), None)
    gate(row is not None and row.get("source_text") == "女の…声……？" and row.get("translation_ko") == NEW_TEXT, "canonical translation drift")
    key = struct.pack("<I", ORIGINAL_ADDRESS)
    positions, cursor = [], 0
    while True:
        cursor = before.find(key, cursor)
        if cursor < 0: break
        positions.append(cursor); cursor += 1
    gate(len(positions) == 1, f"expected one lookup key, found {len(positions)}")
    entry = positions[0]
    old_pointer, original_end = struct.unpack_from("<II", before, entry + 4)
    gate(original_end == EXPECTED_ORIGINAL_END, f"original end drift: 0x{original_end:08X}")
    old_offset = old_pointer - ROM_BASE
    old_payload = bytes.fromhex("E2 5C E6 C9 07 E5 B7 E6 80 E6 BF 07 07 04 00")
    gate(before[old_offset : old_offset + len(old_payload)] == old_payload, "old Korean payload drift")
    apply_charmap = json.loads(APPLY_CHARMAP.read_text(encoding="utf-8"))
    hangul12 = {item["char"]: int(item["slot"], 16) for item in apply_charmap["assignments"]}
    encoded, missing = encode_map_korean_line(NEW_TEXT, hangul12, load_identified_12x12())
    gate(encoded is not None and not missing and len(NEW_TEXT) <= 15, f"encoding/width failed: {missing}")
    gate(before[ALLOCATION : ALLOCATION + len(encoded)] == bytes(len(encoded)), "allocation is not zero-filled")
    candidate = bytearray(before)
    candidate[ALLOCATION : ALLOCATION + len(encoded)] = encoded
    struct.pack_into("<I", candidate, entry + 4, ROM_BASE + ALLOCATION)
    after = bytes(candidate)
    allowed = set(range(ALLOCATION, ALLOCATION + len(encoded))) | set(range(entry + 4, entry + 8))
    changed = [index for index, (old, new) in enumerate(zip(before, after)) if old != new]
    gate(all(index in allowed for index in changed), "unexpected byte change")
    gate(after[0x00F00000:0x00FC0000] == before[0x00F00000:0x00FC0000], "original map-script bank changed")
    gate(after[old_offset : old_offset + len(old_payload)] == old_payload, "old payload changed")
    gate(struct.unpack_from("<I", after, entry + 4)[0] == ROM_BASE + ALLOCATION and after[ALLOCATION:ALLOCATION+len(encoded)] == encoded, "redirect/payload mismatch")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True); OUTPUT_ROM.write_bytes(after)
    output_sha = sha256(after)
    report = {
        "schema_version": 1, "kind": "ggen_advance_yuu_voice_main_tip_candidate",
        "source": {"path": MAIN_ROM.name, "sha256": sha256(before), "manifest_hash_verified": True},
        "correction": {"record_id": RECORD_ID, "source_text": "女の…声……？", "translation_before": "벽의…목소리……？", "translation_after": NEW_TEXT, "lookup_entry_file_offset": f"0x{entry:08X}", "old_payload_file_offset": f"0x{old_offset:08X}", "new_payload_file_offset": f"0x{ALLOCATION:08X}", "new_payload_gba_address": f"0x{ROM_BASE+ALLOCATION:08X}", "encoded_size": len(encoded)},
        "output": {"path": str(OUTPUT_ROM.relative_to(ROOT)).replace("\\", "/"), "size": len(after), "sha256": output_sha},
        "verification": {"result": "PASS", "canonical_translation_matched": True, "lookup_key_unique": True, "lookup_redirect_verified": True, "new_payload_byte_exact": True, "old_payload_preserved": True, "original_map_script_bank_preserved": True, "dialogue_width_cells": len(NEW_TEXT), "dialogue_width_limit": 15, "changed_bytes": len(changed), "unexpected_changes": 0, "canonical_main_tip_modified": False},
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2)); return 0

if __name__ == "__main__": raise SystemExit(main())
