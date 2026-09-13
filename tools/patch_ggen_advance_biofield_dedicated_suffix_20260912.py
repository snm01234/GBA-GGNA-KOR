"""Give Bio Field its own suffix tiles so 바이오필드 does not reuse I-hold.

I-Field hold and Bio Field share eight graphic tiles. Painting the full Bio
label onto those IDs rewrites 아이필드; leaving them shared shows 바이오이필드.
No unused IDs remain in the 294-tile sheet, but the ability clone has 10 KiB
of zero slack. Append eight tiles, retarget only the Bio animation sequences,
and paint 바이오필드 onto unique 240-245 plus the new suffix.
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import build_ggen_advance_turn_ability_overlays_20260905 as ability  # noqa: E402
import test_ggen_advance_font_pair as fontpair  # noqa: E402
from ggen_advance_project_paths import FONT_ZIP, MAIN_TIP_MANIFEST, MAIN_TIP_ROM, ORIGINAL_ROM, advance_relative
from patch_ggen_advance_intermission_text_consumers_20260904 import gate, sha256
from patch_ggen_advance_ss123_zeon_nt001_biofield_20260912 import (
    BIO_IDS,
    BIO_UNIQUE,
    I_HOLD_IDS,
    SHARED_SUFFIX,
    blit_ability,
    save_plate,
    u32,
)

OUT = ROOT / "outputs" / "20260912_biofield_dedicated_suffix"
WORK = OUT / "ggen_biofield_dedicated_suffix_20260912.gba"
EXTRA_TILES = 8
NEW_SUFFIX_START = 294
BEAM_COAT_TAIL = 130
BIO_SEQ_HITS = 4
HOLD_SEQ_HITS = 4


def pack_ids(ids: list[int]) -> bytes:
    return b"".join(struct.pack("<H", value) for value in ids)


def count_seq(blob: bytes, ids: list[int]) -> int:
    needle = pack_ids(ids)
    hits = 0
    start = 0
    while True:
        found = blob.find(needle, start)
        if found < 0:
            return hits
        hits += 1
        start = found + len(needle)


def replace_seq(blob: bytearray, old: list[int], new: list[int]) -> int:
    needle = pack_ids(old)
    put = pack_ids(new)
    gate(len(needle) == len(put), "bio id sequence length drift")
    hits = 0
    start = 0
    while True:
        found = blob.find(needle, start)
        if found < 0:
            return hits
        blob[found : found + len(put)] = put
        hits += 1
        start = found + len(put)


def tile_bytes(gfx: bytes, tile: int) -> bytes:
    return bytes(gfx[tile * 32 : (tile + 1) * 32])


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    parent = MAIN_TIP_ROM.read_bytes()
    japan = ORIGINAL_ROM.read_bytes()
    manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(parent) == str(manifest.get("sha256") or ""), "main TIP sha mismatch")

    live_ptr = u32(parent, ability.ABILITY_POINTER)
    gate(live_ptr == ability.ROM_BASE + ability.ABILITY_CLONE, "ability clone pointer drift")
    hdr, blob = ability.resource_blob(parent, live_ptr)
    gate(hdr["tiles"] == NEW_SUFFIX_START, f"tile count drift {hdr['tiles']}")
    clone_end = ability.ABILITY_CLONE + hdr["size"]
    slack = parent[clone_end : ability.ALLOCATION_END]
    gate(all(byte == 0 for byte in slack), "ability clone slack is not empty")
    gate(hdr["size"] + EXTRA_TILES * 32 <= ability.ALLOCATION_END - ability.ABILITY_CLONE, "clone overflow")

    suffix_old = [tile for tile in BIO_IDS if tile in SHARED_SUFFIX]
    suffix_new = list(range(NEW_SUFFIX_START, NEW_SUFFIX_START + EXTRA_TILES))
    gate(suffix_old == [149, 153, 150, 151, 154, 155, 156, 130], f"shared suffix order {suffix_old}")
    bio_new = [suffix_new[suffix_old.index(tile)] if tile in SHARED_SUFFIX else tile for tile in BIO_IDS]
    gate(bio_new[:3] == [240, 241, 242] and bio_new[4:7] == [243, 244, 245], "unique ids moved")

    orig_prefix = bytes(blob[: hdr["gfx_rel"]])
    prefix = bytearray(orig_prefix)
    gate(count_seq(prefix, BIO_IDS) == BIO_SEQ_HITS, "bio sequence count drift")
    gate(count_seq(prefix, I_HOLD_IDS) == HOLD_SEQ_HITS, "I-hold sequence count drift")
    seq_at = []
    needle = pack_ids(BIO_IDS)
    cursor = 0
    while True:
        found = orig_prefix.find(needle, cursor)
        if found < 0:
            break
        seq_at.append(found)
        cursor = found + len(needle)
    replaced = replace_seq(prefix, BIO_IDS, bio_new)
    gate(replaced == BIO_SEQ_HITS, f"bio retarget hits {replaced}")
    gate(len(seq_at) == BIO_SEQ_HITS, "bio sequence offsets drift")
    gate(count_seq(prefix, BIO_IDS) == 0, "old bio sequence remains")
    gate(count_seq(prefix, bio_new) == BIO_SEQ_HITS, "new bio sequence missing")
    gate(count_seq(prefix, I_HOLD_IDS) == HOLD_SEQ_HITS, "I-hold sequence rewritten")

    new_pal_rel = hdr["pal_rel"] + EXTRA_TILES * 32
    struct.pack_into("<I", prefix, 12, new_pal_rel)
    prefix_changed = {i for i, (old, new) in enumerate(zip(orig_prefix, prefix)) if old != new}
    expected_prefix = set(range(12, 16))
    for offset in seq_at:
        expected_prefix.update(range(offset, offset + len(needle)))
    gate(prefix_changed <= expected_prefix, f"anim prefix escape {sorted(prefix_changed - expected_prefix)[:20]}")
    orig_gfx = bytes(blob[hdr["gfx_rel"] : hdr["pal_rel"]])
    palettes = bytes(blob[hdr["pal_rel"] :])
    gfx = bytearray(orig_gfx + bytes(EXTRA_TILES * 32))
    pal = palettes[:32]
    save_plate(OUT / "biofield_before.png", orig_gfx, BIO_IDS, pal)
    save_plate(OUT / "ifield_hold_before.png", orig_gfx, I_HOLD_IDS, pal)

    with ZipFile(FONT_ZIP) as archive:
        font9 = fontpair.BdfFont.from_bytes(archive.read("Galmuri9.bdf"), "Galmuri9 Regular")
    bio_canvas = [[0] * 56 for _ in range(16)]
    blit_ability(bio_canvas, "바이오필드", font9, 0, 56)
    ability.write_objects(gfx, ability.objects_from_ids(bio_new), bio_canvas, skip_ids={6})

    hold_changed = [tile for tile in I_HOLD_IDS if tile_bytes(gfx, tile) != tile_bytes(orig_gfx, tile)]
    gate(not hold_changed, f"I-hold tiles rewritten {hold_changed}")
    gate(tile_bytes(gfx, BEAM_COAT_TAIL) == tile_bytes(orig_gfx, BEAM_COAT_TAIL), "beam-coat tail rewritten")
    painted = [
        tile
        for tile in bio_new
        if tile_bytes(gfx, tile) != (tile_bytes(orig_gfx, tile) if tile < hdr["tiles"] else bytes(32))
    ]
    jp_hdr, jp_blob = ability.resource_blob(japan, ability.ABILITY_SOURCE)
    jp_gfx = jp_blob[jp_hdr["gfx_rel"] : jp_hdr["pal_rel"]]
    vs_jp = [tile for tile in sorted(BIO_UNIQUE) if tile_bytes(gfx, tile) != tile_bytes(jp_gfx, tile)]
    gate(set(BIO_UNIQUE) <= set(vs_jp), "bio unique still Japanese")
    suffix_ink = [tile for tile in suffix_new if tile_bytes(gfx, tile) != bytes(32)]
    gate(suffix_ink, "dedicated suffix not painted")
    gate({294, 295, 298, 299} <= set(suffix_ink), f"bio suffix coverage {suffix_ink}")

    new_blob = bytes(prefix) + bytes(gfx) + palettes
    gate(len(new_blob) == hdr["size"] + EXTRA_TILES * 32, "clone size drift")
    _kind, _pal_count, gfx_rel, pal_rel, _anim_count = struct.unpack_from("<5I", new_blob, 0)
    new_tiles = (pal_rel - gfx_rel) // 32
    gate(new_tiles == NEW_SUFFIX_START + EXTRA_TILES, f"new tile count {new_tiles}")
    new_hdr = {"gfx_rel": gfx_rel, "pal_rel": pal_rel, "tiles": new_tiles}
    gate(new_hdr["gfx_rel"] == hdr["gfx_rel"], "gfx_rel moved")
    gate(new_hdr["pal_rel"] == new_pal_rel, "pal_rel not updated")
    gate(new_blob[new_pal_rel:] == palettes, "palettes drifted")

    save_plate(OUT / "biofield_after.png", bytes(gfx), bio_new, pal)
    save_plate(OUT / "ifield_hold_after.png", bytes(gfx), I_HOLD_IDS, pal)

    candidate = bytearray(parent)
    start = ability.ABILITY_CLONE
    candidate[start : start + len(new_blob)] = new_blob
    allowed = set(range(start, start + 20))
    allowed.update(range(start, start + hdr["gfx_rel"]))
    for tile in list(BIO_UNIQUE) + suffix_new:
        allowed.update(range(start + hdr["gfx_rel"] + tile * 32, start + hdr["gfx_rel"] + (tile + 1) * 32))
    allowed.update(range(start + new_pal_rel, start + len(new_blob)))
    changed = {i for i, (old, new) in enumerate(zip(parent, candidate)) if old != new}
    extra = set(range(len(parent), len(candidate))) if len(candidate) != len(parent) else set()
    gate(not extra, "ROM size changed")
    gate(changed <= allowed, f"unrelated writes {sorted(changed - allowed)[:20]} count={len(changed - allowed)}")
    gate(u32(bytes(candidate), ability.ABILITY_POINTER) == live_ptr, "ability pointer moved")

    WORK.write_bytes(bytes(candidate))
    sav_src = MAIN_TIP_ROM.with_suffix(".sav")
    if sav_src.exists():
        WORK.with_suffix(".sav").write_bytes(sav_src.read_bytes())
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_biofield_dedicated_suffix_20260912",
        "batch_id": "biofield-dedicated-suffix-20260912",
        "parent_sha256": sha256(parent),
        "output": {"path": advance_relative(WORK), "size": len(candidate), "sha256": sha256(bytes(candidate))},
        "bio_old_ids": BIO_IDS,
        "bio_new_ids": bio_new,
        "suffix_map": {str(old): new for old, new in zip(suffix_old, suffix_new)},
        "painted_tiles": painted,
        "changed_bytes": len(changed),
        "clone": {
            "old_size": hdr["size"],
            "new_size": len(new_blob),
            "old_tiles": hdr["tiles"],
            "new_tiles": new_hdr["tiles"],
            "slack_remaining": ability.ALLOCATION_END - (ability.ABILITY_CLONE + len(new_blob)),
        },
        "verification": {
            "result": "PASS",
            "bio_sequences_retargeted": replaced,
            "ifield_hold_tiles_preserved": True,
            "ifield_hold_sequences_preserved": True,
            "beam_coat_tail_preserved": True,
            "palettes_preserved": True,
            "unrelated_bytes_preserved": True,
        },
    }
    (OUT / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("output", "bio_new_ids", "suffix_map", "clone", "verification")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
