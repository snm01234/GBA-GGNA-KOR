"""Stop Beam Coat from showing I-Field's trailing ㅡ.

Korean 빔코트 is shorter than Japanese ビームコート and does not ink the
last 8px column. Those cells are tiles 106/118/130, which I-Field intro,
mid, and hold reuse as the right edge of 아이필드. I-Field was painted
later, so Beam Coat reads as 빔코트ㅡ. Retarget only the three Beam Coat
12-id sequences so the last cell is filler tile 6. I-Field and Bio Field
keep the shared graphics.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import build_ggen_advance_turn_ability_overlays_20260905 as ability  # noqa: E402
from ggen_advance_project_paths import MAIN_TIP_MANIFEST, MAIN_TIP_ROM, advance_relative
from patch_ggen_advance_biofield_dedicated_suffix_20260912 import (
    BIO_SEQ_HITS,
    HOLD_SEQ_HITS,
    count_seq,
    pack_ids,
    replace_seq,
    tile_bytes,
)
from patch_ggen_advance_intermission_text_consumers_20260904 import gate, sha256
from patch_ggen_advance_ss123_zeon_nt001_biofield_20260912 import I_HOLD_IDS, save_plate, u32

OUT = ROOT / "outputs" / "20260912_beam_coat_dash"
WORK = OUT / "ggen_beam_coat_dash_20260912.gba"
FILLER = 6
BEAM_FRAMES = [
    list(range(95, 107)),
    list(range(107, 119)),
    list(range(119, 131)),
]
BEAM_HITS = [1, 1, 4]
BIO_NEW = [240, 241, 242, 294, 243, 244, 245, 295, 296, 297, 298, 299, 300, 301]
I_FIELD_INTRO = [131, 132, 6, 133, 134, 135, 136, 137, 138, 106]
I_FIELD_MID = [139, 140, 141, 142, 143, 144, 145, 146, 147, 118]


def beam_new(ids: list[int]) -> list[int]:
    return ids[:-1] + [FILLER]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    parent = MAIN_TIP_ROM.read_bytes()
    manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(parent) == str(manifest.get("sha256") or ""), "main TIP sha mismatch")
    live_ptr = u32(parent, ability.ABILITY_POINTER)
    gate(live_ptr == ability.ROM_BASE + ability.ABILITY_CLONE, "ability clone pointer drift")
    hdr, blob = ability.resource_blob(parent, live_ptr)
    gate(hdr["tiles"] == 302, f"tile count drift {hdr['tiles']}")

    prefix = bytearray(blob[: hdr["gfx_rel"]])
    orig_prefix = bytes(prefix)
    gfx = bytes(blob[hdr["gfx_rel"] : hdr["pal_rel"]])
    palettes = bytes(blob[hdr["pal_rel"] :])
    pal = palettes[:32]
    for index, ids in enumerate(BEAM_FRAMES, 1):
        save_plate(OUT / f"beam_ko_{index}.png", gfx, ids, pal)
    save_plate(OUT / "ifield_hold_before.png", gfx, I_HOLD_IDS, pal)

    gate(count_seq(prefix, BIO_NEW) == BIO_SEQ_HITS, "bio sequence drift")
    gate(count_seq(prefix, I_HOLD_IDS) == HOLD_SEQ_HITS, "I-hold sequence drift")
    gate(count_seq(prefix, I_FIELD_INTRO) == 1, "I-field intro sequence drift")
    gate(count_seq(prefix, I_FIELD_MID) == 1, "I-field mid sequence drift")

    replaced = []
    expected_prefix: set[int] = set()
    for ids, expect in zip(BEAM_FRAMES, BEAM_HITS):
        gate(count_seq(prefix, ids) == expect, f"beam sequence {ids[0]} count drift")
        needle = pack_ids(ids)
        cursor = 0
        while True:
            found = bytes(prefix).find(needle, cursor)
            if found < 0:
                break
            expected_prefix.update(range(found + len(needle) - 2, found + len(needle)))
            cursor = found + len(needle)
        hits = replace_seq(prefix, ids, beam_new(ids))
        gate(hits == expect, f"beam retarget {ids[0]} hits {hits}")
        gate(count_seq(prefix, ids) == 0, f"old beam sequence {ids[0]} remains")
        gate(count_seq(prefix, beam_new(ids)) == expect, f"new beam sequence {ids[0]} missing")
        replaced.append({"start": ids[0], "old_tail": ids[-1], "new_tail": FILLER, "hits": hits})

    prefix_changed = {i for i, (old, new) in enumerate(zip(orig_prefix, prefix)) if old != new}
    gate(prefix_changed <= expected_prefix, f"anim prefix escape {sorted(prefix_changed - expected_prefix)}")
    gate(len(prefix_changed) == sum(BEAM_HITS), f"beam tail byte count {len(prefix_changed)}")
    gate(count_seq(prefix, BIO_NEW) == BIO_SEQ_HITS, "bio sequence rewritten")
    gate(count_seq(prefix, I_HOLD_IDS) == HOLD_SEQ_HITS, "I-hold sequence rewritten")
    gate(count_seq(prefix, I_FIELD_INTRO) == 1, "I-field intro rewritten")
    gate(count_seq(prefix, I_FIELD_MID) == 1, "I-field mid rewritten")

    new_blob = bytes(prefix) + gfx + palettes
    gate(len(new_blob) == len(blob), "clone size changed")
    gate(new_blob[hdr["gfx_rel"] :] == blob[hdr["gfx_rel"] :], "ability graphics/palettes changed")
    for tile in I_HOLD_IDS:
        gate(tile_bytes(gfx, tile) == tile_bytes(blob[hdr["gfx_rel"] : hdr["pal_rel"]], tile), f"I-hold tile {tile} drifted")

    for index, ids in enumerate(BEAM_FRAMES, 1):
        save_plate(OUT / f"beam_after_{index}.png", gfx, beam_new(ids), pal)
    save_plate(OUT / "ifield_hold_after.png", gfx, I_HOLD_IDS, pal)

    candidate = bytearray(parent)
    start = ability.ABILITY_CLONE
    candidate[start : start + len(new_blob)] = new_blob
    allowed = {start + off for off in prefix_changed}
    changed = {i for i, (old, new) in enumerate(zip(parent, candidate)) if old != new}
    gate(changed == allowed, f"unrelated writes {sorted(changed - allowed)[:20]} count={len(changed - allowed)}")

    WORK.write_bytes(bytes(candidate))
    sav_src = MAIN_TIP_ROM.with_suffix(".sav")
    if sav_src.exists():
        WORK.with_suffix(".sav").write_bytes(sav_src.read_bytes())
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_beam_coat_dash_20260912",
        "batch_id": "beam-coat-dash-20260912",
        "parent_sha256": sha256(parent),
        "output": {"path": advance_relative(WORK), "size": len(candidate), "sha256": sha256(bytes(candidate))},
        "replaced": replaced,
        "changed_bytes": len(changed),
        "verification": {
            "result": "PASS",
            "beam_tails_retargeted_to_filler": True,
            "ifield_sequences_preserved": True,
            "biofield_sequences_preserved": True,
            "graphics_unchanged": True,
            "unrelated_bytes_preserved": True,
        },
    }
    (OUT / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("output", "replaced", "verification")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
