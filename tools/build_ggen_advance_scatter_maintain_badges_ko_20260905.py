#!/usr/bin/env python3
"""Koreanize the 散開 / 維持 command badges shown by current ss2/ss3.

Four direct 80x16 owners exist: normal 散開/維持 and focus 散開/維持.
The disabled state reuses the normal raster with a disabled palette, so changing
normal + focus graphics covers all three visual states without touching palette
logic.  Japanese glyphs and their contour are first removed by restoring each
row from a clean donor column, preserving the native vertical gradient/caps.
"""
from __future__ import annotations

import binascii
import hashlib
import json
import shutil
import struct
import sys
from pathlib import Path
from zipfile import ZipFile

from PIL import Image

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
import analyze_ggen_advance_intermission_cycle_states_20260830 as bg
import test_ggen_advance_font_pair as fontpair
from ggen_ss_tiles_common_20260905 import ROOT, direct, canvas_direct, gallery, raster
from ggen_advance_project_paths import FONT_ZIP, MAIN_TIP_MANIFEST, MAIN_TIP_ROM

OUT = ROOT / "outputs" / "20260905_ggen_advance_scatter_maintain_badges"
RESULT = OUT / "ggen_advance_scatter_maintain_badges_ko_candidate_20260905.gba"
MANIFEST = OUT / "manifest.json"

# owner, Korean label, cleanup rectangle, clean donor x, text origin, focus?
TARGETS = [
    (0x00A9C264, "산개", (40, 0, 72, 16), 20, (43, 2), False),
    (0x00A9C43C, "유지", (32, 0, 64, 16), 20, (35, 2), False),
    (0x00A9CA24, "산개", (40, 0, 72, 16), 20, (43, 2), True),
    (0x00A9CBFC, "유지", (32, 0, 64, 16), 20, (35, 2), True),
]


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def u16(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def clone_canvas(c: list[list[int]]) -> list[list[int]]:
    return [row[:] for row in c]


def restore_rows(c: list[list[int]], box: tuple[int, int, int, int], donor_x: int, source: list[list[int]]) -> list[int]:
    x0, y0, x1, y1 = box
    rows = [source[y][donor_x] for y in range(y0, y1)]
    for y in range(y0, y1):
        value = rows[y - y0]
        for x in range(x0, x1):
            c[y][x] = value
    return rows


def paint(c: list[list[int]], text: str, x: int, y: int, font, face: int, edge: int, clip: tuple[int, int] | None = None) -> dict:
    ink, width, height = raster.native_ink(font, text)
    ink = {(a + x, b + y) for a, b in ink}
    outline = raster.dilate(ink, len(c[0]), len(c))

    def valid(a: int, b: int) -> bool:
        return 0 <= b < len(c) and 0 <= a < len(c[0]) and (clip is None or clip[0] <= a < clip[1])

    for pts, colour in ((outline, edge), (ink, face)):
        for a, b in pts:
            if valid(a, b):
                c[b][a] = colour
    return {"text": text, "origin": [x, y], "face": face, "outline": edge, "ink_width": width, "ink_height": height, "ink_pixels": len(ink)}


def tile_updates(before: list[list[int]], after: list[list[int]], m: dict) -> dict[int, bytes]:
    updates: dict[int, bytes] = {}
    for index, cell in enumerate(m["cells"]):
        x = index % m["width"] * 8
        y = index // m["width"] * 8
        tile = [row[x:x + 8] for row in after[y:y + 8]]
        if cell & 0x400:
            tile = [list(reversed(row)) for row in tile]
        if cell & 0x800:
            tile = list(reversed(tile))
        payload = raster.encode_tile(tile)
        tid = cell & 1023
        if tid in updates:
            assert updates[tid] == payload, ("shared tile conflict", tid)
        updates[tid] = payload
    return updates


def live_raws(state: bytes, label: str) -> list[bytes]:
    # Native screen rows identified from current ss2/ss3.
    ys = (120, 128) if label == "산개" else (136, 144)
    info = bg.bg_info(state, 2)
    vram = state[statefmt.STATE_VRAM:statefmt.STATE_IWRAM]
    rows = []
    for sy in ys:
        for sx in range(24, 80, 8):
            wx, wy = sx + info["scroll_x"], sy + info["scroll_y"]
            entry = bg.map_entry(vram, info["screen_base"], info["size"], wx // 8, wy // 8)
            tid = entry & 0x3FF
            off = info["char_base"] + tid * 32
            rows.append(bytes(vram[off:off + 32]))
    return rows


def source_tile_set(rom: bytes, owner: int) -> set[bytes]:
    m = direct(rom, owner)
    return {
        bytes(rom[m["graphics_offset"] + i * 32:m["graphics_offset"] + (i + 1) * 32])
        for i in range(m["size"] // 32)
    }


def state_style_scores(parent: bytes) -> dict:
    normal = {"산개": 0x00A9C264, "유지": 0x00A9C43C}
    focus = {"산개": 0x00A9CA24, "유지": 0x00A9CBFC}
    source_sets = {
        (label, style): source_tile_set(parent, owner)
        for style, table in (("normal", normal), ("focus", focus))
        for label, owner in table.items()
    }
    result = {}
    for n in (2, 3):
        state, _ = statefmt.parse_png_state(ROOT / f"SD Gundam GGeneration Advance (Korean).ss{n}")
        result[str(n)] = {}
        for label in ("산개", "유지"):
            raws = live_raws(state, label)
            result[str(n)][label] = {
                style: sum(raw in source_sets[(label, style)] for raw in raws)
                for style in ("normal", "focus")
            }
    return result


def main() -> int:
    parent = MAIN_TIP_ROM.read_bytes()
    meta = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    assert sha256(parent) == meta["sha256"], "main TIP/manifest hash drift"
    parent_crc = binascii.crc32(parent) & 0xFFFFFFFF

    style_scores = state_style_scores(parent)
    # ss2: scatter is focus, maintain is normal. ss3: scatter is disabled and
    # therefore normal raster, maintain is focus. Require a strict winner.
    assert style_scores["2"]["산개"]["focus"] > style_scores["2"]["산개"]["normal"], style_scores
    assert style_scores["2"]["유지"]["normal"] > style_scores["2"]["유지"]["focus"], style_scores
    assert style_scores["3"]["산개"]["normal"] > style_scores["3"]["산개"]["focus"], style_scores
    assert style_scores["3"]["유지"]["focus"] > style_scores["3"]["유지"]["normal"], style_scores

    with ZipFile(FONT_ZIP) as archive:
        font = fontpair.load_bdf(archive, "Galmuri11.bdf")

    candidate = bytearray(parent)
    replacements: dict[bytes, bytes] = {}
    allowed: list[tuple[int, int]] = []
    reports = []
    previews = []

    for owner, text, box, donor, origin, focus in TARGETS:
        m = direct(parent, owner)
        assert (m["width"], m["height"]) == (10, 2), (hex(owner), m["width"], m["height"])
        before = canvas_direct(parent, m)
        clean = clone_canvas(before)
        gradient_rows = restore_rows(clean, box, donor, before)
        x0, y0, x1, y1 = box
        assert all(clean[y][x] == gradient_rows[y - y0] for y in range(y0, y1) for x in range(x0, x1))
        after = clone_canvas(clean)
        info = paint(
            after, text, origin[0], origin[1], font,
            12 if focus else 10,
            1 if focus else 5,
            clip=(x0, x1),
        )
        assert all(before[y][x] == after[y][x] for y in range(16) for x in range(80) if not (x0 <= x < x1 and y0 <= y < y1))
        changes = []
        for tid, new in tile_updates(before, after, m).items():
            off = m["graphics_offset"] + tid * 32
            old = bytes(parent[off:off + 32])
            if old == new:
                continue
            assert bytes(candidate[off:off + 32]) == old
            candidate[off:off + 32] = new
            allowed.append((off, off + 32))
            if old in replacements:
                assert replacements[old] == new, ("ambiguous live tile replacement", hex(owner), tid)
            replacements[old] = new
            changes.append({"source_tile": tid, "file_offset": f"0x{off:08X}"})
        colours = raster.palette_rgb(parent[m["palette_offset"]:m["palette_offset"] + 32])
        previews.extend([
            (f"{text} {'focus' if focus else 'normal'} before", raster.render_canvas(before, colours)),
            (f"{text} {'focus' if focus else 'normal'} clean", raster.render_canvas(clean, colours)),
            (f"{text} {'focus' if focus else 'normal'} after", raster.render_canvas(after, colours)),
        ])
        reports.append({
            "owner": f"0x{owner:08X}", "label": text, "style": "focus" if focus else "normal_and_disabled",
            "cleanup_box": list(box), "background_donor_x": donor, "gradient_rows": gradient_rows,
            "graphics_offset": f"0x{m['graphics_offset']:08X}", "changed_tiles": changes, **info,
        })

    # Scope gate: only four direct-resource graphics ranges may differ.
    mask = bytearray(len(parent))
    for a, b in allowed:
        mask[a:b] = b"\1" * (b - a)
    assert all(mask[i] for i, (a, b) in enumerate(zip(parent, candidate)) if a != b)

    OUT.mkdir(parents=True, exist_ok=True)
    RESULT.write_bytes(candidate)
    shutil.copy2(MAIN_TIP_ROM.with_suffix(".sav"), RESULT.with_suffix(".sav"))
    gallery(previews, OUT / "scatter_maintain_before_clean_after.png", 5)

    # Derived states replace already-decoded live/cache tiles so the supplied
    # ss2/ss3 can be loaded directly against the candidate ROM.
    state_reports = []
    candidate_crc = binascii.crc32(candidate) & 0xFFFFFFFF
    for n in (2, 3):
        src = ROOT / f"SD Gundam GGeneration Advance (Korean).ss{n}"
        state, _ = statefmt.parse_png_state(src)
        assert u32(state, 8) == parent_crc
        fixed = bytearray(state)
        vram_hits = 0
        cache_hits = []
        for off in range(statefmt.STATE_VRAM, statefmt.STATE_IWRAM, 32):
            raw = bytes(state[off:off + 32])
            if raw in replacements:
                fixed[off:off + 32] = replacements[raw]
                vram_hits += 1
        for off in range(statefmt.STATE_IWRAM, len(state) - 31, 4):
            raw = bytes(state[off:off + 32])
            if raw in replacements:
                fixed[off:off + 32] = replacements[raw]
                cache_hits.append(f"0x{off:05X}")
        struct.pack_into("<I", fixed, 8, candidate_crc)
        dst = RESULT.with_suffix(f".ss{n}")
        dst.write_bytes(raster.replace_state_chunk(src, bytes(fixed)))
        state_reports.append({"state": n, "updated_vram_tiles": vram_hits, "updated_cached_tile_offsets": cache_hits})

    manifest = {
        "kind": "ggen_advance_scatter_maintain_badges_ko_candidate_20260905",
        "parent": {"path": str(MAIN_TIP_ROM.relative_to(ROOT)), "sha256": sha256(parent), "crc32": f"0x{parent_crc:08X}"},
        "output": {"path": str(RESULT.relative_to(ROOT)), "sha256": sha256(candidate), "crc32": f"0x{candidate_crc:08X}", "size": len(candidate)},
        "targets": reports,
        "state_style_proof": {
            "scores": style_scores,
            "interpretation": {
                "ss2": "scatter=focus raster, maintain=normal raster",
                "ss3": "scatter=normal raster with disabled palette, maintain=focus raster",
                "coverage": "normal + focus direct owners cover disabled because disabled reuses normal graphics",
            },
        },
        "derived_states": state_reports,
        "verification": {
            "result": "PASS",
            "gradient_cleanup": "Japanese glyph and contour region replaced row-for-row from native clean donor before Korean paint",
            "font": "Galmuri11 Regular",
            "normal_palette_indices": {"face": 10, "outline": 5},
            "focus_palette_indices": {"face": 12, "outline": 1},
            "disabled": "no separate raster write; verified ss3 disabled scatter uses normal raster and palette-only styling",
            "writes_restricted_to_target_graphics_tiles": True,
            "runtime": "derived ss2/ss3 prepared; emulator visual confirmation pending user test",
        },
        "allowed_ranges": [[f"0x{a:08X}", f"0x{b:08X}"] for a, b in allowed],
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(RESULT.relative_to(ROOT)),
        "sha256": sha256(candidate),
        "style_scores": style_scores,
        "targets": [{"owner": r["owner"], "label": r["label"], "style": r["style"], "changed_tiles": len(r["changed_tiles"])} for r in reports],
        "states": state_reports,
        "preview": str((OUT / "scatter_maintain_before_clean_after.png").relative_to(ROOT)),
        "manifest": str(MANIFEST.relative_to(ROOT)),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
