#!/usr/bin/env python3
"""Fix 12x12 battle-quote pronunciations on the 22.129 candidate.

- Fin Funnel in 12x12 dialogue was the 8x16 payload ``핀 판넬``.
  8x16 ``핀`` lives at slot 0x010A, which is still original Ｖ in 12x12, so
  Amuro's battle line showed ``Ｖ 판넬``. Paint 12x12 ``핀`` on a free slot
  and retarget only the scenario-dynamic 12x12 owners.
- Master Asia 石破天驚拳 second line: ``천경케에엔！！`` → ``천경궈어언！！``.
  ``궈`` is not painted on 12x12 yet.
"""
from __future__ import annotations

import binascii
import hashlib
import json
import shutil
import struct
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import build_ggen_advance_ko_poc as fontops  # noqa: E402
import build_ggen_advance_unified_rom_poc as unified  # noqa: E402
from build_ggen_advance_battle_cutin_quotes_20260905 import (  # noqa: E402
    parse_blocks,
    rebuild_container,
    verify_hangul_and_nu,
)
from build_ggen_advance_nu_slot_battle_bark_20260905 import (  # noqa: E402
    paint_12x12,
    slot_jp,
    slot_main,
)
from extract_ggen_advance_id_command_battle_barks import load_slot_map  # noqa: E402
from ggen_advance_painted_glyph_identity import (  # noqa: E402
    FONT12_RELOCATED,
    load_galmuri12,
    load_galmuri8,
    packed_12x12,
    recover_unique_12x12_slots,
    recover_unique_8x16_slots,
    verify_payload_painted,
)
from ggen_advance_project_paths import (  # noqa: E402
    ORIGINAL_ROM,
    TRANSLATION_MANIFEST,
    TRANSLATION_MERGED_JSON,
    advance_relative,
)
from ggen_advance_text_codec import DICT_12X12_BASE, DICT_12X12_END, load_dictionary  # noqa: E402
from merge_ggen_advance_translation_overlays import digest, translation_payload_digest  # noqa: E402
from patch_ggen_advance_kimi_jane_to_neo_20260904 import find_lookup, payload_until_nul  # noqa: E402

ROM_BASE = 0x08000000
TABLE = 0x00228600
PAYLOAD_LO = 0x00228184
CAVE_START = 0x012A2840
CAVE_END = 0x012A6000
PARENT_ROM = (
    ROOT
    / "outputs"
    / "20260905_ggen_advance_cutin_mistranslation_fix"
    / "ggen_advance_cutin_mistranslation_fix_candidate_20260905.gba"
)
PARENT_SAV = PARENT_ROM.with_suffix(".sav")
PARENT_MANIFEST = ROOT / "analysis" / "ggen_advance_cutin_mistranslation_fix_candidate_20260905.json"
MAP12 = ROOT / "analysis" / "ggen_advance_12x12_identified_charmap_20260828.json"
CORR = ROOT / "analysis" / "ggen_advance_12x12_runtime_measurement_corrections_20260829.json"
APPLY = ROOT / "analysis" / "ggen_advance_korean_apply_charmap_20260844.json"
OUT_DIR = ROOT / "outputs" / "20260905_ggen_advance_cutin_pronunciation_fix"
OUT_ROM = OUT_DIR / "ggen_advance_cutin_pronunciation_fix_candidate_20260905.gba"
OUT_SAV = OUT_DIR / "ggen_advance_cutin_pronunciation_fix_candidate_20260905.sav"
OUT_MANIFEST = ROOT / "analysis" / "ggen_advance_cutin_pronunciation_fix_candidate_20260905.json"
SNAPSHOT = ROOT / "analysis" / "ggen_advance_translation_merged_20260905_pronunciation.json"
CUTIN_OVERLAY = ROOT / "integrated" / "translation" / "ggen_advance_battle_cutin_quotes.json"
BATCH_ID = "cutin-pronunciation-tengyo-finfunnel-20260905"
PROTECT_SLOTS = {
    0x010A: "Ｖ",
    0x0143: "ν",
}
PRODUCTION_OWNERS = [
    0x001939F4,
    0x00193AA0,
    0x00199F68,
    0x0019A014,
]
DYNAMIC_OWNERS = [
    0x001F2B50,
    0x001F2B68,
    0x001F3E10,
    0x001F3E28,
    0x001F5580,
    0x001F5598,
]
EIGHT_PIN_SLOT = 0x010A


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def hangul_chars(text: str) -> set[str]:
    return {char for char in text if "가" <= char <= "힣"}


def update_payload_hash(row: dict[str, Any], notes: str) -> None:
    row["overlay_batch_id"] = BATCH_ID
    row["translation_source"] = "user_verified"
    row["review_status"] = "user_verified"
    row["reviewed_at"] = "2026-09-05"
    row["review_count"] = int(row.get("review_count") or 0) + 1
    row["translator_notes"] = notes
    row["qa_status"] = "user_verified_term"
    row["translation_payload_sha256"] = translation_payload_digest(
        {
            "record_id": row["record_id"],
            "batch_id": row["overlay_batch_id"],
            "translation_ko": row.get("translation_ko") or "",
            "translation_segments": row.get("translation_segments"),
            "translation_status": row.get("translation_status") or "",
            "translation_source": row.get("translation_source") or "",
            "source_model": row.get("source_model") or "",
            "prompt_version": row.get("prompt_version") or "",
            "review_status": row.get("review_status") or "",
            "review_count": row.get("review_count") or 0,
            "reviewed_at": row.get("reviewed_at") or "",
            "translator_notes": row.get("translator_notes") or "",
            "qa_status": row.get("qa_status") or "",
        }
    )


def write_payload(
    candidate: bytearray,
    address: int,
    encoded: bytes,
    old_size: int,
    allowed: set[int],
    cursor: int,
) -> tuple[int, int]:
    gate(encoded.endswith(b"\x00"), "encoded payload missing NUL")
    if old_size > 0 and len(encoded) <= old_size:
        start = address - ROM_BASE
        candidate[start : start + len(encoded)] = encoded
        if len(encoded) < old_size:
            candidate[start + len(encoded) : start + old_size] = b"\x00" * (old_size - len(encoded))
        allowed.update(range(start, start + old_size))
        return address, cursor
    gate(cursor + len(encoded) <= CAVE_END, "pronunciation cave exhausted")
    start = cursor
    candidate[start : start + len(encoded)] = encoded
    allowed.update(range(start, start + len(encoded)))
    return ROM_BASE + start, (start + len(encoded) + 3) & ~3


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
    raise SystemExit("gate failed: no free 12x12 slot for new Hangul")


def update_translation_manifest(merged: dict[str, Any], snapshot: Path) -> None:
    manifest = json.loads(TRANSLATION_MANIFEST.read_text(encoding="utf-8"))
    merged_sha = sha256(TRANSLATION_MERGED_JSON.read_bytes())
    counts = dict(sorted(Counter(str(row.get("translation_status") or "") for row in merged["records"]).items()))
    manifest.update(
        {
            "source_snapshot": advance_relative(snapshot),
            "sha256": merged_sha,
            "source_sha256": merged_sha,
            "record_count": len(merged["records"]),
            "record_identity_sha256": merged.get("identity", {}).get("record_identity_sha256"),
            "translation_overlay_identity_sha256": merged.get("identity", {}).get(
                "translation_overlay_identity_sha256"
            ),
            "record_translation_status_counts": counts,
            "source_summary_translation_status_counts": counts,
        }
    )
    TRANSLATION_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parent = PARENT_ROM.read_bytes()
    japan = ORIGINAL_ROM.read_bytes()
    parent_manifest = json.loads(PARENT_MANIFEST.read_text(encoding="utf-8"))
    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    overlay = json.loads(CUTIN_OVERLAY.read_text(encoding="utf-8"))
    apply_map = json.loads(APPLY.read_text(encoding="utf-8"))
    gate(sha256(parent) == parent_manifest["output"]["sha256"], "22.129 parent/manifest drift")
    gate(all(value == 0 for value in parent[CAVE_START:CAVE_END]), "pronunciation cave is not zero-filled")

    leftover = [
        row["record_id"]
        for row in merged["records"]
        if "천경케에엔" in str(row.get("translation_ko") or "")
        or "천경케에엔" in "".join(str(x) for x in (row.get("translation_segments") or []))
    ]
    gate(leftover == ["GGA-MAPSCRIPT-00F545BB"], f"unexpected 천경케에엔 rows: {leftover}")

    by_id = {row["record_id"]: row for row in merged["records"]}
    mapscript = by_id["GGA-MAPSCRIPT-00F545BB"]
    gate(mapscript["translation_ko"] == "천경케에엔！！", "map-script 天驚 translation drift")
    gate(by_id["GGA-TEXT-0017A602"]["translation_ko"] == "핀 판넬", "weapon 핀 판넬 drift")

    hangul_by_slot = {
        int(str(row["slot"]), 16): str(row["char"])
        for row in apply_map["assignments"]
        if str(row.get("paint") or "") in {"both", "12x12", "split"} and "가" <= str(row["char"]) <= "힣"
    }
    font12 = load_galmuri12()
    packed_by_char = {
        char: packed_12x12(char, font12) for char in set(hangul_by_slot.values()) | {"핀", "궈"}
    }
    packed_hangul = set(packed_by_char.values())
    _live8, live12 = unified.collect_live_slots(japan, list(merged["records"]))

    candidate = bytearray(parent)
    allowed: set[int] = set()
    pin_slot = choose_free_12x12(candidate, japan, set(hangul_by_slot), live12, packed_hangul)
    hangul_by_slot[pin_slot] = "핀"
    live12.add(pin_slot)
    gwo_slot = choose_free_12x12(candidate, japan, set(hangul_by_slot), live12, packed_hangul)
    gate(pin_slot not in PROTECT_SLOTS, f"핀 collided with protected slot 0x{pin_slot:04X}")
    gate(gwo_slot not in PROTECT_SLOTS, f"궈 collided with protected slot 0x{gwo_slot:04X}")
    gate(pin_slot != gwo_slot, "핀/궈 reused the same free slot")

    for slot, char in ((pin_slot, "핀"), (gwo_slot, "궈")):
        packed = packed_by_char[char]
        paint_12x12(candidate, slot, packed)
        start = FONT12_RELOCATED + slot * fontops.FONT_12X12_STRIDE
        allowed.update(range(start, start + fontops.FONT_12X12_STRIDE))
        gate(slot_main(candidate, slot) == packed, f"failed to paint 12x12 {char!r}")

    gate(slot_main(candidate, EIGHT_PIN_SLOT) == slot_jp(japan, EIGHT_PIN_SLOT), "12x12 Ｖ slot 0x010A was overwritten")
    recovered12 = recover_unique_12x12_slots(
        candidate, font12, hangul_chars("핀 판넬천경궈어언케에엔")
    )
    gate(recovered12["핀"] == pin_slot, f"recovered 핀 is 0x{recovered12['핀']:04X}, painted 0x{pin_slot:04X}")
    gate(recovered12["궈"] == gwo_slot, f"recovered 궈 is 0x{recovered12['궈']:04X}, painted 0x{gwo_slot:04X}")
    font8 = load_galmuri8()
    recovered8 = recover_unique_8x16_slots(candidate, font8, {"핀", "판", "넬"})
    gate(recovered8["핀"] == EIGHT_PIN_SLOT, "8x16 핀 is no longer unique at 0x010A")

    verified12 = unified.load_verified_charmap(unified.CHARMAP_12X12_PATH)
    map12 = load_slot_map(MAP12, CORR)
    dictionary = load_dictionary(japan, DICT_12X12_BASE, DICT_12X12_END)
    cave_cursor = CAVE_START
    evidence: list[dict[str, Any]] = []

    encoded_pin, missing_pin = unified.encode_korean_text(
        "핀 판넬", recovered12, verified_charmap=verified12, strict_punctuation=True
    )
    gate(encoded_pin is not None and not missing_pin, f"12x12 핀 판넬 encode failed: {missing_pin}")
    assert encoded_pin is not None
    verify_hangul_and_nu(candidate, encoded_pin, "핀 판넬", font12, japan)
    production_ptr = u32(parent, PRODUCTION_OWNERS[0])
    for owner in PRODUCTION_OWNERS:
        gate(u32(parent, owner) == production_ptr, "production 핀 판넬 owners diverged")
    for owner in DYNAMIC_OWNERS:
        gate(u32(parent, owner) == production_ptr, "dynamic 핀 판넬 owners are not on the 8x16 payload")
    old_dynamic = payload_until_nul(parent, production_ptr)
    gate(old_dynamic[:2] == bytes((0xE0, 0x2A)), "shared 핀 판넬 payload no longer starts with 8x16 핀")
    new_pin_addr, cave_cursor = write_payload(
        candidate, 0, encoded_pin, 0, allowed, cave_cursor
    )
    for owner in DYNAMIC_OWNERS:
        struct.pack_into("<I", candidate, owner, new_pin_addr)
        allowed.update(range(owner, owner + 4))
    for owner in PRODUCTION_OWNERS:
        gate(u32(candidate, owner) == production_ptr, "production 8x16 핀 판넬 pointer drifted")
    evidence.append(
        {
            "record_id": "GGA-DYNAMIC-001F1D3D",
            "before": "Ｖ 판넬 (8x16 핀 at 12x12 0x010A)",
            "after": "핀 판넬",
            "path": "scenario_dynamic_12x12",
            "old_address": f"0x{production_ptr:08X}",
            "new_address": f"0x{new_pin_addr:08X}",
            "pin_slot_12x12": f"0x{pin_slot:04X}",
            "owners": [f"0x{owner:08X}" for owner in DYNAMIC_OWNERS],
        }
    )

    ko_tengyo = "천경궈어언！！"
    mapscript["translation_ko"] = ko_tengyo
    mapscript["translation_segments"] = [ko_tengyo]
    update_payload_hash(
        mapscript,
        "石破天驚拳 天驚けぇぇぇぇん！！ → 천경궈어언！！; 12x12 핀/궈 painted",
    )
    encoded_tengyo, missing_tengyo = unified.encode_korean_text(
        ko_tengyo, recovered12, verified_charmap=verified12, strict_punctuation=True
    )
    gate(encoded_tengyo is not None and not missing_tengyo, f"12x12 천경궈어언 encode failed: {missing_tengyo}")
    assert encoded_tengyo is not None
    verify_hangul_and_nu(candidate, encoded_tengyo, ko_tengyo, font12, japan)
    orig = ROM_BASE + int(mapscript["target_file_offset"], 16)
    original = bytes.fromhex(str(mapscript["segments"][0]["raw_hex"]).replace(" ", ""))
    lookup_pos, neu, _orig_end = find_lookup(parent, orig, orig + len(original) - 1)
    old_payload = payload_until_nul(parent, neu)
    new_tengyo_addr, cave_cursor = write_payload(
        candidate, neu, encoded_tengyo, len(old_payload), allowed, cave_cursor
    )
    if new_tengyo_addr != neu:
        struct.pack_into("<I", candidate, lookup_pos + 4, new_tengyo_addr)
        allowed.update(range(lookup_pos + 4, lookup_pos + 8))
    evidence.append(
        {
            "record_id": "GGA-MAPSCRIPT-00F545BB",
            "before": "천경케에엔！！",
            "after": ko_tengyo,
            "path": "map_script_lookup",
            "old_address": f"0x{neu:08X}",
            "new_address": f"0x{new_tengyo_addr:08X}",
            "gwo_slot_12x12": f"0x{gwo_slot:04X}",
        }
    )

    ptrs: list[tuple[int, int]] = []
    off = TABLE
    while off + 4 <= len(japan):
        val = u32(japan, off)
        dest = val - ROM_BASE
        if not (PAYLOAD_LO <= dest < TABLE):
            break
        ptrs.append((off, dest))
        off += 4
    src, start = ptrs[20]
    boundary = ptrs[21][1]
    parsed = parse_blocks(japan, start, boundary, dictionary, map12)
    gate(parsed["streams"][0]["source_text"] == "天驚けぇぇぇぇん！！", "cut-in index 20 is not 天驚")
    original_container = japan[start:boundary]
    rebuilt = rebuild_container(
        original_container,
        start,
        parsed,
        {int(parsed["streams"][0]["start_file_offset"], 16): encoded_tengyo},
    )
    live_ptr = u32(parent, src)
    gate(cave_cursor + len(rebuilt) <= CAVE_END, "cut-in 天驚 cave exhausted")
    start_off = cave_cursor
    candidate[start_off : start_off + len(rebuilt)] = rebuilt
    allowed.update(range(start_off, start_off + len(rebuilt)))
    new_cutin_addr = ROM_BASE + start_off
    cave_cursor = (start_off + len(rebuilt) + 3) & ~3
    struct.pack_into("<I", candidate, src, new_cutin_addr)
    allowed.update(range(src, src + 4))
    evidence.append(
        {
            "record_id": "GGA-BATTLECUTIN-0022841A",
            "before": "천경케에엔！！",
            "after": ko_tengyo,
            "path": "battle_cutin_container_20",
            "old_address": f"0x{live_ptr:08X}",
            "new_address": f"0x{new_cutin_addr:08X}",
            "new_size": len(rebuilt),
        }
    )
    for row in overlay["records"]:
        if row.get("record_id") == "GGA-BATTLECUTIN-0022841A":
            row["translation_ko"] = ko_tengyo
            row["translation_source"] = "user_verified:천경궈어언"

    leftover_after = [
        row["record_id"]
        for row in merged["records"]
        if "천경케에엔" in str(row.get("translation_ko") or "")
        or "천경케에엔" in "".join(str(x) for x in (row.get("translation_segments") or []))
    ]
    gate(not leftover_after, f"leftover 천경케에엔: {leftover_after}")

    parent_overlay = str(merged.get("identity", {}).get("translation_overlay_identity_sha256") or "")
    identity = digest(
        {
            "parent": parent_overlay,
            "batch_id": BATCH_ID,
            "pin_slot_12x12": f"0x{pin_slot:04X}",
            "gwo_slot_12x12": f"0x{gwo_slot:04X}",
            "records": [
                {"record_id": "GGA-MAPSCRIPT-00F545BB", "payload": mapscript["translation_payload_sha256"]},
                {"record_id": "GGA-DYNAMIC-001F1D3D", "payload": encoded_pin.hex()},
            ],
        }
    )
    merged["identity"]["parent_translation_overlay_identity_sha256"] = parent_overlay
    merged["identity"]["cutin_pronunciation_sha256"] = identity
    merged["identity"]["translation_overlay_identity_sha256"] = identity
    counts = dict(sorted(Counter(str(row.get("translation_status") or "") for row in merged["records"]).items()))
    merged["summary"]["merged_translation_status_counts"] = counts
    merged["summary"]["translation_overlay_identity_sha256"] = identity

    changed = [index for index, (before, after) in enumerate(zip(parent, candidate)) if before != after]
    stray = sorted(set(changed) - allowed)
    gate(set(changed) <= allowed, f"changed outside targets: {[hex(off) for off in stray[:12]]}")
    gate(candidate[PAYLOAD_LO:TABLE] == japan[PAYLOAD_LO:TABLE], "original cut-in payloads changed")
    gate(slot_main(candidate, EIGHT_PIN_SLOT) == slot_jp(japan, EIGHT_PIN_SLOT), "Ｖ glyph lost")
    live_pin = payload_until_nul(candidate, new_pin_addr)
    gate(live_pin[:2] != bytes((0xE0, 0x2A)), "12x12 핀 판넬 still uses 8x16 핀 token")
    verify_payload_painted(
        candidate,
        payload_until_nul(candidate, production_ptr),
        "핀판넬",
        font8,
    )

    out = bytes(candidate)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_ROM.write_bytes(out)
    if PARENT_SAV.is_file():
        shutil.copy2(PARENT_SAV, OUT_SAV)
    SNAPSHOT.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    TRANSLATION_MERGED_JSON.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    CUTIN_OVERLAY.write_text(json.dumps(overlay, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    update_translation_manifest(merged, SNAPSHOT)
    manifest = {
        "schema_version": 1,
        "kind": "ggen_advance_cutin_pronunciation_fix_candidate_20260905",
        "result": "PASS",
        "base": {
            "path": advance_relative(PARENT_ROM),
            "sha256": sha256(parent),
        },
        "output": {
            "path": advance_relative(OUT_ROM),
            "sha256": sha256(out),
            "crc32": f"0x{binascii.crc32(out) & 0xFFFFFFFF:08X}",
            "size": len(out),
            "sav": advance_relative(OUT_SAV) if OUT_SAV.exists() else None,
        },
        "glyphs": {
            "pin_12x12": f"0x{pin_slot:04X}",
            "gwo_12x12": f"0x{gwo_slot:04X}",
            "v_12x12_preserved": "0x010A",
            "nu_12x12_preserved": "0x0143",
            "pin_8x16_preserved": "0x010A",
        },
        "fixes": evidence,
        "verification": {
            "result": "PASS",
            "no_천경케에엔_in_merged": True,
            "production_fin_funnel_unchanged": True,
            "changed_bytes": len(changed),
        },
    }
    OUT_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "result": "PASS",
                "rom": advance_relative(OUT_ROM),
                "sha256": sha256(out),
                "changed_bytes": len(changed),
                "glyphs": manifest["glyphs"],
                "fixes": evidence,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
