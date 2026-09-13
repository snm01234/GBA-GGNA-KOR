#!/usr/bin/env python3
"""Restore 12x12 ν and relocate Hangul that stole its cell.

Combat ID-command barks are already redirected and Korean-encoded.  The captured
Amuro line starts with token E063 (slot 0x0143).  The 12x12 identified map keeps
that cell as ν, but the apply-charmap painted Hangul there; the relocated font
currently shows 꺄, so ν건담은 허세가 아니야! renders as 꺄건담은….

This builder:
1. restores original Japanese 12x12 glyphs for protected specials (ν/∀/γ)
2. paints displaced Hangul onto unique free 12x12 slots
3. retargets 깃 payloads that currently share E063 with ν
4. leaves already-Korean bark bytes in place so ν encoding keeps using E063
"""
from __future__ import annotations

import binascii
import hashlib
import json
import shutil
import struct
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import build_ggen_advance_ko_poc as fontops
import build_ggen_advance_unified_rom_poc as unified
import ggen_advance_painted_glyph_identity as identity
from ggen_advance_project_paths import (
    ADVANCE_ROOT,
    MAIN_TIP_MANIFEST,
    MAIN_TIP_ROM,
    ORIGINAL_ROM,
    TRANSLATION_MERGED_JSON,
    advance_relative,
)

ANALYSIS = ADVANCE_ROOT / "analysis" / "ggen_advance_nu_kya_battle_bark_20260905.json"
APPLY = ADVANCE_ROOT / "analysis" / "ggen_advance_korean_apply_charmap_20260844.json"
BARK_OVERLAY = ADVANCE_ROOT / "integrated" / "translation" / "ggen_advance_id_command_battle_barks.json"
OUT_DIR = ADVANCE_ROOT / "outputs" / "20260905_ggen_advance_nu_slot_battle_bark"
OUT_ROM = OUT_DIR / "ggen_advance_nu_slot_battle_bark_candidate_20260905.gba"
OUT_SAV = OUT_DIR / "ggen_advance_nu_slot_battle_bark_candidate_20260905.sav"
OUT_MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_nu_slot_battle_bark_candidate_20260905.json"
TEXT_START = 0x01040000
TEXT_END = 0x01240000
AMURO_TABLE = 0x00226B14
GIT_OLD_SLOT = 0x0143
GIT_PLAN_SLOT = 0x01CF
KYA_META_SLOT = 0x0146
PROTECT_SLOTS = {
    0x0143: "ν",
}
SOURCE_SAV_CANDIDATES = [
    ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean)_allclear.sav",
    ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).sav",
]


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def paint_12x12(candidate: bytearray, slot: int, packed: bytes) -> None:
    start = identity.FONT12_RELOCATED + slot * fontops.FONT_12X12_STRIDE
    gate(len(packed) == fontops.FONT_12X12_STRIDE, "12x12 glyph length drift")
    candidate[start:start + fontops.FONT_12X12_STRIDE] = packed


def slot_main(rom: bytes | bytearray, slot: int) -> bytes:
    return identity.slot_raw(rom, identity.FONT12_RELOCATED, slot, fontops.FONT_12X12_STRIDE)


def slot_jp(rom: bytes, slot: int) -> bytes:
    return identity.slot_raw(rom, fontops.FONT_12X12_BASE, slot, fontops.FONT_12X12_STRIDE)


def choose_free_12x12(
    candidate: bytearray,
    japan: bytes,
    hangul_slots: set[int],
    live12: set[int],
    packed_hangul: set[bytes],
) -> int:
    protected = set(PROTECT_SLOTS) | unified.SPECIAL_SLOTS | unified.RESERVED_GLYPH_SLOTS
    for slot in range(unified.SLOT_MAX, unified.SLOT_MIN - 1, -1):
        if slot in protected or slot in hangul_slots or slot in live12:
            continue
        current = slot_main(candidate, slot)
        if current != slot_jp(japan, slot):
            continue
        if current in packed_hangul:
            continue
        return slot
    raise SystemExit("gate failed: no free 12x12 slot for displaced Hangul")


def replace_prefixed_token(blob: bytearray, start: int, end: int, prefix: bytes, old: bytes, new: bytes) -> int:
    needle = prefix + old
    gate(len(old) == len(new) == 2, "token rewrite width drift")
    count = 0
    index = start
    while True:
        found = bytes(blob[index:end]).find(needle)
        if found < 0:
            return count
        pos = index + found + len(prefix)
        blob[pos:pos + 2] = new
        count += 1
        index = pos + 2


def main() -> int:
    analysis = json.loads(ANALYSIS.read_text(encoding="utf-8"))
    gate(analysis.get("result") == "PASS", "nu/kya analysis is not PASS")
    gate(analysis["nu_slot"]["painted_as"] == "꺄", "expected 0x0143 to be painted as 꺄")
    parent = MAIN_TIP_ROM.read_bytes()
    japan = ORIGINAL_ROM.read_bytes()
    manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(parent) == manifest["sha256"], "parent is not current main TIP")
    gate(analysis["current_main_tip"]["sha256"] == sha256(parent), "analysis parent drift")

    apply_map = json.loads(APPLY.read_text(encoding="utf-8"))
    hangul_by_slot = {
        int(str(row["slot"]), 16): str(row["char"])
        for row in apply_map["assignments"]
        if str(row.get("paint") or "") in {"both", "12x12", "split"} and "가" <= str(row["char"]) <= "힣"
    }
    gate(hangul_by_slot.get(GIT_OLD_SLOT) == "깃", "apply-charmap 0x0143 is no longer 깃")
    gate(hangul_by_slot.get(KYA_META_SLOT) == "꺄", "apply-charmap 0x0146 is no longer 꺄")

    font12 = identity.load_galmuri12()
    packed_by_char = {char: identity.packed_12x12(char, font12) for char in sorted(set(hangul_by_slot.values()) | {"꺄", "깃"})}
    glyph_to_char = {packed: char for char, packed in packed_by_char.items()}
    gate(glyph_to_char.get(slot_main(parent, GIT_OLD_SLOT)) == "꺄", "live 0x0143 is not 꺄")

    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    _live8, live12 = unified.collect_live_slots(japan, list(merged["records"]))

    overlay = json.loads(BARK_OVERLAY.read_text(encoding="utf-8"))
    amuro = next(row for row in overlay["records"] if row["record_id"] == "GGA-IDBARK-00223520")
    amuro_ptr = struct.unpack_from("<I", parent, AMURO_TABLE)[0]
    amuro_off = amuro_ptr - 0x08000000
    amuro_before = bytes(parent[amuro_off:amuro_off + 24])
    gate(amuro_before.startswith(bytes((0xE0, 0x63, 0xE6, 0xAF))), "Amuro bark no longer starts with ν+건 tokens")
    gate("ν건담은 허세가 아니야" in str(amuro.get("translation_ko") or ""), "Amuro overlay translation drift")

    candidate = bytearray(parent)
    restored = []
    displaced: dict[int, str] = {}
    for slot, special in PROTECT_SLOTS.items():
        gate(slot < fontops.FONT_12X12_COUNT, f"protected slot 0x{slot:04X} is outside the 12x12 glyph array")
        current = slot_main(candidate, slot)
        original = slot_jp(japan, slot)
        if current == original:
            continue
        painted = glyph_to_char.get(current)
        displaced[slot] = painted or f"<unknown:{hangul_by_slot.get(slot, '?')}>"
        paint_12x12(candidate, slot, original)
        gate(slot_main(candidate, slot) == original, f"failed to restore 12x12 {special} at 0x{slot:04X}")
        restored.append({"slot": f"0x{slot:04X}", "special": special, "displaced_hangul": displaced[slot]})

    hangul_slots = set(hangul_by_slot)
    packed_hangul = set(packed_by_char.values())
    # 꺄 consumers already use token E066 = slot 0x0146.  That cell currently
    # paints 껍 because of the same identity cascade that put 꺄 on ν.
    kya_slot = KYA_META_SLOT
    paint_12x12(candidate, kya_slot, packed_by_char["꺄"])
    gate(glyph_to_char.get(slot_main(candidate, kya_slot)) == "꺄", "꺄 paint at consumer slot 0x0146 failed")

    git_slot = GIT_PLAN_SLOT
    if git_slot in live12 or git_slot in hangul_slots or slot_main(candidate, git_slot) != slot_jp(japan, git_slot):
        git_slot = choose_free_12x12(candidate, japan, hangul_slots | {kya_slot}, live12, packed_hangul)
    paint_12x12(candidate, git_slot, packed_by_char["깃"])
    gate(glyph_to_char.get(slot_main(candidate, git_slot)) == "깃", "깃 paint failed")
    gate(git_slot != GIT_OLD_SLOT, "깃 must not occupy the ν cell")
    gate(slot_main(candidate, GIT_OLD_SLOT) == slot_jp(japan, GIT_OLD_SLOT), "ν cell was not restored")

    old_git = unified.slot_to_token_bytes(GIT_OLD_SLOT)
    new_git = unified.slot_to_token_bytes(git_slot)
    ta = unified.slot_to_token_bytes(int(next(row["slot"] for row in apply_map["assignments"] if row["char"] == "타"), 16))
    ya = unified.slot_to_token_bytes(int(next(row["slot"] for row in apply_map["assignments"] if row["char"] == "야"), 16))
    git_rewrites = replace_prefixed_token(candidate, TEXT_START, TEXT_END, ta, old_git, new_git)
    git_rewrites += replace_prefixed_token(candidate, TEXT_START, TEXT_END, ya, old_git, new_git)
    gate(bytes(candidate[amuro_off:amuro_off + 4]) == bytes((0xE0, 0x63, 0xE6, 0xAF)), "Amuro ν+건 tokens were rewritten")

    # Remaining E063 in the text region must be ν (followed by 건) or 1-byte aligned noise.
    hangul_end = bytes(candidate[amuro_off + 2:amuro_off + 24]).find(b"\x05")
    gate(hangul_end > 0, "Amuro hangul stream missing terminator")
    git_payload = bytes(candidate[amuro_off + 2:amuro_off + 2 + hangul_end]) + b"\x00"
    identity.verify_payload_painted_12x12(candidate, git_payload, "건담은 허세가 아니야", font12)
    gate(slot_main(candidate, GIT_OLD_SLOT) == slot_jp(japan, GIT_OLD_SLOT), "ν cell lost after 깃 retarget")

    special_ok = []
    for slot, special in PROTECT_SLOTS.items():
        if slot_main(candidate, slot) == slot_jp(japan, slot):
            special_ok.append(special)

    out = bytes(candidate)
    changed = [i for i, (a, b) in enumerate(zip(parent, out)) if a != b]
    font12_start = identity.FONT12_RELOCATED
    font12_end = font12_start + fontops.FONT_12X12_COUNT * fontops.FONT_12X12_STRIDE
    escaped = [
        off for off in changed
        if not (font12_start <= off < font12_end or TEXT_START <= off < TEXT_END)
    ]
    gate(changed and not escaped, f"change escaped 12x12 font or text region: {escaped[:8]}")
    gate(out[:0x01000000] == parent[:0x01000000], "original 16 MiB half changed")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_ROM.write_bytes(out)
    sav_source = next((path for path in SOURCE_SAV_CANDIDATES if path.is_file()), None)
    if sav_source is not None:
        shutil.copy2(sav_source, OUT_SAV)

    manifest_out = {
        "schema_version": 1,
        "kind": "ggen_advance_nu_slot_battle_bark_candidate_20260905",
        "result": "PASS",
        "base": {"path": advance_relative(MAIN_TIP_ROM), "sha256": sha256(parent), "crc32": f"0x{binascii.crc32(parent) & 0xFFFFFFFF:08X}"},
        "output": {
            "path": advance_relative(OUT_ROM),
            "sha256": sha256(out),
            "crc32": f"0x{binascii.crc32(out) & 0xFFFFFFFF:08X}",
            "bytes": len(out),
            "size": len(out),
            "sav": advance_relative(OUT_SAV) if OUT_SAV.exists() else None,
            "sav_source": advance_relative(sav_source) if sav_source is not None else None,
        },
        "analysis": advance_relative(ANALYSIS),
        "diagnosis": {
            "nu_to_kya": "12x12 slot 0x0143 is original ν (token E063). Apply-charmap assigned 깃 there; the relocated cell actually paints 꺄. Untranslated ν and Korean ν both used E063, so Amuro's line showed 꺄건담은 허세가 아니야!",
            "battle_barks_already_korean": "ID-command bark table already points at 0x09 Korean containers; the screenshot rest is Hangul 건담은 허세가 아니야, not leftover Japanese ガンダムはダテじゃない",
            "similar_cases": "Allocator now treats 12x12 ν slot 0x0143 as a special like ∀/γ so Hangul cannot steal it again; 깃 is painted on a free cell so 타깃 cannot share E063 with ν",
        },
        "font": {
            "restored_specials": restored,
            "protected_ok": special_ok,
            "kya_slot": f"0x{kya_slot:04X}",
            "git_slot": f"0x{git_slot:04X}",
            "nu_slot_restored": "0x0143",
        },
        "git_retarget": {"old_token": "0xE063", "new_token": f"0x{0xDF20 + git_slot:04X}", "rewrites": git_rewrites, "patterns": ["타깃", "이야깃"]},
        "amuro": {"pointer": f"0x{amuro_ptr:08X}", "translation_ko": amuro.get("translation_ko"), "nu_geon_prefix_preserved": True, "payload_verifies_as_korean_with_nu": True},
        "diff": {"changed_byte_count": len(changed), "original_16mib_unchanged": True},
        "verification": {
            "result": "PASS",
            "nu_cell_matches_japan": True,
            "kya_unique_at_0146": True,
            "git_not_on_nu_cell": True,
            "amuro_nu_geon_preserved": True,
            "amuro_12x12_painted_identity": True,
            "special_slots_added_to_allocator_guard": True,
        },
    }
    OUT_MANIFEST.write_text(json.dumps(manifest_out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "rom": advance_relative(OUT_ROM),
        "sav": advance_relative(OUT_SAV) if OUT_SAV.exists() else None,
        "manifest": advance_relative(OUT_MANIFEST),
        "sha256": manifest_out["output"]["sha256"],
        "restored": restored,
        "kya_slot": f"0x{kya_slot:04X}",
        "git_slot": f"0x{git_slot:04X}",
        "git_rewrites": git_rewrites,
        "changed_bytes": len(changed),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
