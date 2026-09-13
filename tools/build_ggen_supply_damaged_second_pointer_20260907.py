"""Retarget the missed supply-screen 破損中 consumer at 0x0006DF98.

The 20260907 pass rewrote OWNER-U32-0006DF1C, the first (216,72) draw through
0x08000F54.  The live plaque tiles are copied from the second pass, which loads
the same Japanese stream via 0x08000648 from the literal at 0x0006DF98.
"""
from __future__ import annotations

import json
import shutil
import struct
import sys
from collections import Counter
from pathlib import Path

from PIL import Image

import build_ggen_advance_owned_count_ab_candidates_20260903 as ab
import ggen_advance_painted_glyph_identity as glyph
import patch_ggen_advance_pending_readable_batch_20260907 as prev
from build_ggen_advance_map_script_sheet import recount
from ggen_advance_project_paths import (
    MAIN_TIP_MANIFEST,
    MAIN_TIP_ROM,
    ORIGINAL_ROM,
    TRANSLATION_MERGED_JSON,
    advance_relative,
)
from ggen_advance_text_codec import (
    DICT_8X16_BASE,
    DICT_8X16_END,
    expand_to_slots,
    load_dictionary,
    read_tokens,
)
from merge_ggen_advance_translation_overlays import digest
from patch_ggen_advance_intermission_text_consumers_20260904 import gate, sha256, u32

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "20260907_supply_damaged_second_pointer"
RID = "GGA-UI-001BE7AA"
FIRST = 0x0006DF1C
SECOND = 0x0006DF98
ORIGIN = 0x001BE7AA
KO_ADDR = 0x09FF0185
TEXT = "파손중"
BATCH = "supply-damaged-second-pointer-20260907"


def decode(rom: bytes, addr: int, dic) -> tuple[list[int], bytes]:
    tokens, raw = read_tokens(rom, addr - 0x08000000)
    return expand_to_slots(tokens, dic), raw


def glyphs_match(rom: bytes, slots: list[int], text: str, font) -> bool:
    if len(slots) != len(text):
        return False
    for slot, char in zip(slots, text):
        if glyph.slot_raw(rom, glyph.FONT8_RELOCATED, slot, 32) != glyph.packed_8x16(char, font):
            return False
    return True


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    jp = ORIGINAL_ROM.read_bytes()
    parent = MAIN_TIP_ROM.read_bytes()
    before_sheet = TRANSLATION_MERGED_JSON.read_bytes()
    gate(sha256(parent) == json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))["sha256"], "main drift")
    dic = load_dictionary(jp, DICT_8X16_BASE, DICT_8X16_END)
    font = glyph.load_galmuri8()
    gate(u32(jp, FIRST) == 0x08000000 + ORIGIN and u32(jp, SECOND) == 0x08000000 + ORIGIN, "jp literals drift")
    gate(u32(parent, FIRST) == KO_ADDR, "first F54 owner lost Korean payload")
    gate(u32(parent, SECOND) == 0x08000000 + ORIGIN, "second 0648 owner already retargeted")
    gate(ab.thumb_bl_target(parent, 0x0806DF14) == 0x08000F54, "F54 callsite drift")
    gate(ab.thumb_bl_target(parent, 0x0806DF90) == 0x08000648, "0648 callsite drift")
    slots, raw = decode(parent, KO_ADDR, dic)
    gate(glyphs_match(parent, slots, TEXT, font), "existing 파손중 payload glyph drift")
    gate(parent[ORIGIN : ORIGIN + 7] == bytes.fromhex("E3DFE331E36200"), "original Japanese stream mutated")

    candidate = bytearray(parent)
    candidate[SECOND : SECOND + 4] = struct.pack("<I", KO_ADDR)
    changed = {i for i, (a, b) in enumerate(zip(parent, candidate)) if a != b}
    gate(changed == set(range(SECOND, SECOND + 4)), "changes escaped the missed literal")
    for owner in (FIRST, SECOND):
        addr = u32(candidate, owner)
        sl, _ = decode(candidate, addr, dic)
        gate(glyphs_match(candidate, sl, TEXT, font), f"owner 0x{owner:X} not 파손중")
    origin_ptr = struct.pack("<I", 0x08000000 + ORIGIN)
    remain = []
    pos = 0
    while True:
        pos = bytes(candidate).find(origin_ptr, pos)
        if pos < 0:
            break
        if pos % 4 == 0:
            remain.append(pos)
        pos += 1
    gate(not remain, f"Japanese 破損中 pointer remains: {[hex(x) for x in remain]}")

    merged = json.loads(before_sheet)
    row = next(r for r in merged["records"] if r["record_id"] == RID)
    gate(row["translation_ko"] in ("파손중", "파손 중"), "sheet translation drift")
    owner_id = "OWNER-U32-0006DF98"
    gate(owner_id not in row["owner_ids"], "second owner already on sheet")
    gate(not any(o["owner_id"] == owner_id for o in merged["owners"]), "second owner record exists")
    row["owner_ids"] = ["OWNER-U32-0006DF1C", owner_id]
    row["owner_count"] = 2
    row["owner_digest"] = digest(row["owner_ids"])
    row["translation_ko"] = TEXT
    row["baseline_translation_ko"] = TEXT
    row["translator_notes"] = (
        "Live supply plaque uses the second (216,72) pass through 0x08000648 "
        "at 0x0006DF98; the earlier F54 literal at 0x0006DF1C was not the BG tile source."
    )
    row["overlay_batch_id"] = BATCH
    row["qa_status"] = "static_consumer_and_actual_glyph_verified"
    row["review_count"] = int(row.get("review_count") or 0) + 1
    row["reviewed_at"] = "2026-09-07"
    prev.update_payload_hash(row)
    merged["owners"].append(
        {
            "owner_id": owner_id,
            "owner_kind": "u32_pointer",
            "source_file_offset": "0x0006DF98",
            "pointer_width": 4,
            "target_record_ids": [RID],
            "target_container_ids": [RID],
            "relocation_schemas": ["direct_pc_literal"],
            "source_types": ["owner_proven_ui_pointer"],
            "families": ["direct_0648_literal_ui"],
            "synthetic": False,
        }
    )
    ident = merged["identity"]
    previous = ident.get("translation_overlay_identity_sha256", "")
    ident["parent_translation_overlay_identity_sha256"] = previous
    ident["translation_overlay_identity_sha256"] = digest({"parent": previous, "batch": BATCH, "second_owner": owner_id})
    recount(merged)
    merged["summary"]["translation_overlay_identity_sha256"] = ident["translation_overlay_identity_sha256"]

    preview = Image.open(ROOT / "outputs" / "20260907_ss1_ss2_text_next" / "ss2_embedded.png").convert("RGB")
    x, y, w, h = 216, 72, 8, 16
    rect = (x, y, x + len(TEXT) * w, y + h)
    bg = Counter(preview.crop(rect).getdata()).most_common(1)[0][0]
    preview.paste(bg, rect)
    for i, slot in enumerate(slots):
        mask = glyph.fontops.unpack_8x16(glyph.slot_raw(candidate, glyph.FONT8_RELOCATED, slot, 32))
        preview.paste((115, 82, 24), (x + i * w, y), mask)
    preview.resize((960, 640), Image.Resampling.NEAREST).save(OUT / "ss2_after_preview.png")

    output = OUT / "ggen_supply_damaged_second_pointer_20260907.gba"
    gate(MAIN_TIP_ROM.read_bytes() == parent and TRANSLATION_MERGED_JSON.read_bytes() == before_sheet, "concurrent change")
    output.write_bytes(candidate)
    snapshot = OUT / "translation_after.json"
    snapshot.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    shutil.copy2(TRANSLATION_MERGED_JSON, OUT / "translation_before.json")
    TRANSLATION_MERGED_JSON.write_bytes(snapshot.read_bytes())
    prev.update_translation_manifest(merged, snapshot)

    report = {
        "parent": {"sha256": sha256(parent)},
        "output": {"path": advance_relative(output), "sha256": sha256(candidate), "size": len(candidate)},
        "cause": {
            "visible_path": "0x0806DF84 LDR 0x0006DF98 -> 0x08000648 at (216,72), then BG2 blit (27,9) x3",
            "previous_patch": "only OWNER-U32-0006DF1C / 0x08000F54 first pass",
            "missed_owner": "OWNER-U32-0006DF98",
            "why_sav_reload_kept_japanese": "the Japanese stream pointer lives in ROM code, not in the .sav",
        },
        "pointers": {
            "first_f54": {"offset": hex(FIRST), "before": hex(u32(parent, FIRST)), "after": hex(u32(candidate, FIRST))},
            "second_0648": {"offset": hex(SECOND), "before": hex(u32(parent, SECOND)), "after": hex(u32(candidate, SECOND))},
            "payload": hex(KO_ADDR),
            "korean": TEXT,
        },
        "verification": {
            "result": "PASS",
            "only_second_literal_changed": True,
            "both_live_owners_render_파손중": True,
            "original_japanese_stream_preserved": True,
            "no_remaining_origin_pointers": True,
            "overlay_stub_preserved": candidate[0xC5700:0xC5A00] == parent[0xC5700:0xC5A00],
            "runtime": "Static pointer/glyph verification; ss2 preview reconstructed from the existing 8x16 payload. Emulator re-entry not run.",
        },
    }
    (OUT / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": report["output"], "cause": report["cause"], "pointers": report["pointers"], "verification": report["verification"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
