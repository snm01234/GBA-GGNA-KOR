"""Fix ss1 지온해병, ss2 NT-001 dialogue, and ss3 Bio Field tiles.

ss1: GGA-TEXT-0017CEEB is ジオン+海(0x01A9)+兵. Pending, still Japanese.
ss2: GGA-MAPSCRIPT-00F9CD75 copied Japanese NT00 instead of NT-001.
ss3: バイオフィールド unique tiles 240-245 were never Koreanized. Shared
     I-Field hold suffix tiles stay as 아이필드; do not rewrite hold.
"""
from __future__ import annotations

import json
import struct
import sys
from collections import Counter
from pathlib import Path
from typing import Any
from zipfile import ZipFile

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import build_ggen_advance_ko_poc as fontops  # noqa: E402
import build_ggen_advance_turn_ability_overlays_20260905 as ability  # noqa: E402
import build_ggen_advance_unified_rom_poc as unified  # noqa: E402
import patch_ggen_advance_apsaras_zentetsu_20260908 as aps  # noqa: E402
import patch_ggen_profile_followup2_20260912 as f2  # noqa: E402
import test_ggen_advance_font_pair as fontpair  # noqa: E402
from ggen_advance_painted_glyph_identity import FONT12_RELOCATED, slot_raw  # noqa: E402
from ggen_advance_project_paths import (  # noqa: E402
    FONT_ZIP,
    MAIN_TIP_MANIFEST,
    MAIN_TIP_ROM,
    ORIGINAL_ROM,
    TRANSLATION_MERGED_JSON,
    advance_relative,
)
from ggen_advance_text_codec import (  # noqa: E402
    DICT_8X16_BASE,
    DICT_8X16_END,
    DICT_12X12_BASE,
    DICT_12X12_END,
    load_dictionary,
)
from merge_ggen_advance_translation_overlays import digest  # noqa: E402
from patch_ggen_advance_apsaras_zentetsu_20260908 import hangul_chars  # noqa: E402
from patch_ggen_advance_intermission_text_consumers_20260904 import gate, sha256  # noqa: E402
from patch_ggen_advance_kimi_jane_to_neo_20260904 import (  # noqa: E402
    owner_offsets,
    update_payload_hash,
    update_translation_manifest,
)
from patch_ggen_advance_map_script_inline_poc import MAX_DIALOGUE_CELLS, load_identified_12x12  # noqa: E402
from patch_ggen_advance_name_unify_20260909 import patch_map_row_live  # noqa: E402

BATCH_ID = "ss123-zeon-marine-nt001-biofield-20260912"
IDENTITY_KEY = "ss123_zeon_marine_nt001_biofield_20260912_sha256"
BATCH_KEY = "ss123_zeon_marine_nt001_biofield_20260912"
OUT = ROOT / "outputs" / "20260912_ss123_zeon_nt001_biofield"
WORK = OUT / "ggen_ss123_zeon_nt001_biofield_20260912.gba"
SNAPSHOT = ROOT / "analysis" / "ggen_advance_translation_merged_20260912_ss123_zeon_nt001_biofield.json"
CAVE_START = 0x01135330
CAVE_END = 0x01230000
TURN_A_SLOT_12 = 0x071B
NAME_RECORD = "GGA-TEXT-0017CEEB"
NAME_KO = "지온해병"
NAME_SOURCE = "ジオン<01A9><00C8>"
MAP_RECORD = "GGA-MAPSCRIPT-00F9CD75"
MAP_OLD = ["나는 NT00…… 아니", "레이라 레이먼드야"]
MAP_NEW = ["나는 NT-001…… 아니", "레이라 레이먼드야"]
BIO_IDS = [240, 241, 242, 149, 243, 244, 245, 153, 150, 151, 154, 155, 156, 130]
BIO_UNIQUE = {240, 241, 242, 243, 244, 245}
I_HOLD_IDS = [148, 149, 150, 151, 152, 153, 154, 155, 156, 130]
SHARED_SUFFIX = set(BIO_IDS) & set(I_HOLD_IDS)
NOTES = (
    "ss1 ジオン海兵→지온해병. 海는 8x16 슬롯 0x01A9. "
    "ss2 NT00→NT-001. ss3 바이오필드 고유타일만 한글화. I필드 hold(아이필드)는 유지."
)


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def patch_merged_row(row: dict[str, Any], ko: str, segments: list[str] | None = None) -> None:
    row["translation_ko"] = ko
    if segments is not None:
        row["translation_segments"] = segments
    row["translation_status"] = "translated"
    row["translation_source"] = "user_verified"
    row["review_status"] = "user_verified"
    row["review_count"] = int(row.get("review_count") or 0) + 1
    row["reviewed_at"] = "2026-09-12"
    row["translator_notes"] = NOTES
    row["qa_status"] = "static_consumer_verified"
    row["overlay_batch_id"] = BATCH_ID
    row["pointer_recalc_required"] = True
    update_payload_hash(row)


def blit_ability(canvas: list[list[int]], text: str, font: fontpair.BdfFont, x0: int, width: int) -> None:
    height = len(canvas)
    blank = [[0] * width for _ in range(height)]
    ink, tw, th = ability.native_ink(font, text)
    if tw > width - 2:
        scale = (width - 2) / tw
        ink = {(min(width - 3, int(x * scale)), y) for x, y in ink}
        tw = max(x for x, _y in ink) + 1
        th = max(y for _x, y in ink) + 1
    ox = 1
    oy = max(1, (height - th) // 2)
    placed = {(ox + x, oy + y) for x, y in ink if 0 <= ox + x < width and 0 <= oy + y < height}
    gate(placed, f"ability glyph clipped: {text}")
    contour = ability.dilate(placed, width, height) - placed
    after = [[0] * width for _ in range(height)]
    for x, y in contour:
        after[y][x] = 7
    for x, y in placed:
        after[y][x] = 1 if y - oy <= max(0, th // 2) else 2
    for y in range(height):
        canvas[y][x0 : x0 + width] = after[y]


def save_plate(path: Path, graphics: bytes, ids: list[int], pal: bytes) -> None:
    canvas = ability.canvas_from_objects(graphics, ability.objects_from_ids(ids))
    image = ability.render_canvas(canvas, ability.palette_rgb(pal))
    image.resize((image.width * 4, image.height * 4), Image.Resampling.NEAREST).save(path)


def patch_bio_field(candidate: bytearray, japan: bytes, allowed: set[int]) -> dict[str, Any]:
    live_ptr = u32(candidate, ability.ABILITY_POINTER)
    gate(live_ptr == ability.ROM_BASE + ability.ABILITY_CLONE, f"ability clone pointer drift {hex(live_ptr)}")
    hdr, blob = ability.resource_blob(bytes(candidate), live_ptr)
    clone = bytearray(blob)
    gfx = bytearray(clone[hdr["gfx_rel"] : hdr["pal_rel"]])
    pal = bytes(clone[hdr["pal_rel"] : hdr["pal_rel"] + 32])
    orig_gfx = bytes(gfx)
    save_plate(OUT / "biofield_before.png", orig_gfx, BIO_IDS, pal)
    save_plate(OUT / "ifield_hold_before.png", orig_gfx, I_HOLD_IDS, pal)
    with ZipFile(FONT_ZIP) as archive:
        font9 = fontpair.BdfFont.from_bytes(archive.read("Galmuri9.bdf"), "Galmuri9 Regular")
    bio_canvas = [[0] * 56 for _ in range(16)]
    blit_ability(bio_canvas, "바이오", font9, 0, 24)
    ability.write_objects(
        gfx, ability.objects_from_ids(BIO_IDS), bio_canvas, skip_ids=SHARED_SUFFIX | {6}
    )
    clone[hdr["gfx_rel"] : hdr["pal_rel"]] = gfx
    gate(clone[: hdr["gfx_rel"]] == blob[: hdr["gfx_rel"]], "ability animation records changed")
    gate(clone[hdr["pal_rel"] :] == blob[hdr["pal_rel"] :], "ability palettes changed")
    start = ability.ABILITY_CLONE
    candidate[start : start + len(clone)] = clone
    allowed.update(range(start + hdr["gfx_rel"], start + hdr["pal_rel"]))
    save_plate(OUT / "biofield_after.png", bytes(gfx), BIO_IDS, pal)
    save_plate(OUT / "ifield_hold_after.png", bytes(gfx), I_HOLD_IDS, pal)
    jp_hdr, jp_blob = ability.resource_blob(japan, ability.ABILITY_SOURCE)
    jp_gfx = jp_blob[jp_hdr["gfx_rel"] : jp_hdr["pal_rel"]]
    changed_tiles = [
        tile
        for tile in sorted(BIO_UNIQUE | set(I_HOLD_IDS))
        if gfx[tile * 32 : (tile + 1) * 32] != orig_gfx[tile * 32 : (tile + 1) * 32]
    ]
    vs_jp = [
        tile
        for tile in sorted(BIO_UNIQUE)
        if gfx[tile * 32 : (tile + 1) * 32] != jp_gfx[tile * 32 : (tile + 1) * 32]
    ]
    hold_changed = [tile for tile in I_HOLD_IDS if gfx[tile * 32 : (tile + 1) * 32] != orig_gfx[tile * 32 : (tile + 1) * 32]]
    gate(not hold_changed, f"I-hold tiles rewritten {hold_changed}")
    gate(set(changed_tiles) <= BIO_UNIQUE, "ability tile escape")
    gate(set(BIO_UNIQUE) <= set(vs_jp), "bio unique tiles still Japanese")
    return {"changed_tiles": changed_tiles, "unique": sorted(BIO_UNIQUE), "shared": sorted(SHARED_SUFFIX), "vs_jp": vs_jp}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    parent_path = WORK if WORK.exists() else MAIN_TIP_ROM
    parent = parent_path.read_bytes()
    japan = ORIGINAL_ROM.read_bytes()
    manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    if parent_path == MAIN_TIP_ROM:
        gate(sha256(parent) == str(manifest.get("sha256") or ""), "main TIP sha mismatch")
        gate(all(b == 0 for b in parent[CAVE_START:CAVE_END]), "ss123 cave is not empty")
    gate(len(MAP_NEW[0]) <= MAX_DIALOGUE_CELLS, f"NT-001 width {len(MAP_NEW[0])}")

    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    by_id = {str(row["record_id"]): row for row in merged["records"]}
    name_row = by_id[NAME_RECORD]
    map_row = by_id[MAP_RECORD]
    gate(str(name_row.get("source_text") or "") == NAME_SOURCE, "해병 source drift")
    gate(str(name_row.get("translation_ko") or "") in {"", NAME_KO}, "해병 translation drift")
    gate(bytes.fromhex(str(name_row.get("raw_hex") or "").replace(" ", "")).hex() == "f004e0c9c800", "해병 raw drift")
    gate(list(map_row.get("translation_segments") or []) in (MAP_OLD, MAP_NEW), "NT00 segment drift")

    live8, live12 = unified.collect_live_slots(japan, merged["records"])
    verified8 = unified.load_verified_charmap(unified.CHARMAP_8X16_PATH)
    verified12 = unified.load_verified_charmap(unified.CHARMAP_12X12_PATH)
    identified = load_identified_12x12()
    jp_forall = slot_raw(japan, fontops.FONT_12X12_BASE, TURN_A_SLOT_12, fontops.FONT_12X12_STRIDE)
    hangul8 = set(hangul_chars(NAME_KO))
    hangul12: set[str] = set()
    for line in MAP_OLD + MAP_NEW:
        hangul12.update(hangul_chars(line))

    candidate = bytearray(parent)
    allowed: set[int] = set()
    painted: list[dict[str, str]] = []
    occupied8: set[int] = set()
    occupied12: set[int] = set()
    recovered8 = f2.recover_hangul(
        candidate, japan, hangul8, mode=8, live=live8, occupied=occupied8, allowed=allowed, painted=painted
    )
    recovered12 = f2.recover_hangul(
        candidate, japan, hangul12, mode=12, live=live12, occupied=occupied12, allowed=allowed, painted=painted
    )
    cave_cursor = CAVE_START
    evidence: list[dict[str, Any]] = []

    encoded_name, missing_name = unified.encode_korean_text(
        NAME_KO, recovered8, verified_charmap=verified8, strict_punctuation=True
    )
    gate(encoded_name is not None and not missing_name, f"encode 해병 failed {missing_name}")
    owners = owner_offsets(name_row)
    gate(owners, "해병 has no owners")
    old_payload = f2.payload_at(parent, u32(parent, owners[0]))
    cave_cursor, old_addresses, new_addr = aps.patch_owned_payload(
        name_row, old_payload, encoded_name, parent, candidate, allowed, cave_cursor, require_nul=True
    )
    patch_merged_row(name_row, NAME_KO)
    evidence.append(
        {
            "record_id": NAME_RECORD,
            "path": "u32_8x16",
            "before": NAME_SOURCE,
            "after": NAME_KO,
            "old_active_addresses": old_addresses,
            "new_address": new_addr,
        }
    )

    map_old = list(map_row.get("translation_segments") or [])
    if map_old == MAP_NEW:
        written = [{"segment": 0, "old": MAP_NEW[0], "new": MAP_NEW[0], "skipped": "already_nt001"}]
    else:
        cave_cursor, written = patch_map_row_live(
            map_row, MAP_OLD, MAP_NEW, parent, candidate, recovered12, identified, verified12, allowed, cave_cursor
        )
    patch_merged_row(map_row, "\n".join(MAP_NEW), MAP_NEW)
    evidence.append({"record_id": MAP_RECORD, "path": "map_script", "segments": written})
    bio_report = patch_bio_field(candidate, japan, allowed)

    hangul_live8 = f2.hangul_slot_map(candidate, mode=8)
    hangul_live12 = f2.hangul_slot_map(candidate, mode=12)
    map8 = f2.slot_to_char_map(verified8, recovered8, hangul_live8)
    map12 = f2.slot_to_char_map(verified12, recovered12, hangul_live12)
    map12[TURN_A_SLOT_12] = "∀"
    dict8 = load_dictionary(bytes(candidate), DICT_8X16_BASE, DICT_8X16_END)
    dict12 = load_dictionary(bytes(candidate), DICT_12X12_BASE, DICT_12X12_END)
    name_live = f2.decode_text(candidate, u32(candidate, owners[0]), dict8, map8)
    gate(name_live == NAME_KO, f"해병 live {name_live!r}")
    raw0 = bytes.fromhex(str(map_row["segments"][0]["raw_hex"]).replace(" ", ""))
    orig0 = ability.ROM_BASE + int(str(map_row["target_file_offset"]), 16)
    hits = aps.find_lookups(bytes(candidate), orig0, orig0 + len(raw0) - 1)
    nt_live = f2.decode_text(candidate, hits[0][1], dict12, map12)
    gate(nt_live.replace("－", "-") == MAP_NEW[0], f"NT live {nt_live!r}")
    leftover_nt = [
        str(row["record_id"])
        for row in merged["records"]
        if "NT00" in str(row.get("translation_ko") or "") and str(row["record_id"]) != MAP_RECORD
    ]
    gate(not leftover_nt, f"other NT00 leftover {leftover_nt}")
    gate(
        slot_raw(candidate, FONT12_RELOCATED, TURN_A_SLOT_12, fontops.FONT_12X12_STRIDE) == jp_forall,
        "∀ glyph drifted",
    )

    changed = {i for i, (old, new) in enumerate(zip(parent, candidate)) if old != new}
    gate(changed <= allowed, f"unrelated writes {len(changed - allowed)}")
    gate(cave_cursor <= CAVE_END, "cave overflow")

    parent_identity = str(merged.get("identity", {}).get("translation_overlay_identity_sha256") or "")
    new_identity = digest({"parent": parent_identity, "batch_id": BATCH_ID, "records": [NAME_RECORD, MAP_RECORD]})
    identity = merged.setdefault("identity", {})
    identity["parent_translation_overlay_identity_sha256"] = parent_identity
    identity[IDENTITY_KEY] = new_identity
    identity["translation_overlay_identity_sha256"] = new_identity
    summary = merged.setdefault("summary", {})
    summary["merged_translation_status_counts"] = dict(
        sorted(Counter(str(row.get("translation_status") or "") for row in merged["records"]).items())
    )
    summary["translation_overlay_identity_sha256"] = new_identity
    merged[BATCH_KEY] = {"batch_id": BATCH_ID, "changed_records": [NAME_RECORD, MAP_RECORD], "evidence": evidence}
    payload_json = json.dumps(merged, ensure_ascii=False, indent=2) + "\n"
    SNAPSHOT.write_text(payload_json, encoding="utf-8")
    TRANSLATION_MERGED_JSON.write_text(payload_json, encoding="utf-8")
    update_translation_manifest(merged, SNAPSHOT)
    WORK.write_bytes(bytes(candidate))
    sav_src = MAIN_TIP_ROM.with_suffix(".sav")
    if sav_src.exists():
        WORK.with_suffix(".sav").write_bytes(sav_src.read_bytes())
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_ss123_zeon_nt001_biofield_20260912",
        "batch_id": BATCH_ID,
        "parent_sha256": sha256(parent),
        "output": {"path": advance_relative(WORK), "size": len(candidate), "sha256": sha256(bytes(candidate))},
        "painted": painted,
        "cave": {"start": hex(CAVE_START), "end": hex(cave_cursor), "capacity_end": hex(CAVE_END)},
        "changed_bytes": len(changed),
        "bio_field": bio_report,
        "proofs": {"name": name_live, "nt001": nt_live},
        "verification": {
            "result": "PASS",
            "zeon_marine_ko": True,
            "nt001_dialogue": True,
            "biofield_unique_painted": True,
            "forall_071b_preserved": True,
            "unrelated_bytes_preserved": True,
        },
    }
    (OUT / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {k: report[k] for k in ("output", "painted", "cave", "bio_field", "proofs", "verification")},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
