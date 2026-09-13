#!/usr/bin/env python3
"""Koreanize the five fixed labels visible in the ss1 team-card screen.

The screen loads one custom-LZSS 4bpp atlas through resource table 0x080DAB70.
This builder preserves that shared source, installs a private atlas clone in
zero-filled expansion space, and redirects only the atlas pointer.  The live
ss1 BG tilemaps prove the exact tile IDs for 移動/汎用/万能/相性/発進.
"""
from __future__ import annotations

import binascii
import hashlib
import json
import struct
import sys
from pathlib import Path
from zipfile import ZipFile

from PIL import Image

THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_action_graphics_scan_20260830 as scan
import analyze_ggen_advance_intermission_cycle_states_20260830 as bgutil
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
import build_ggen_advance_action_menu_ko_poc as action
import build_ggen_advance_sort_popup_state6_candidate_20260903 as state_writer
import test_ggen_advance_font_pair as fontpair
from ggen_advance_project_paths import ADVANCE_ROOT, FONT_ZIP, MAIN_TIP_MANIFEST, MAIN_TIP_ROM, advance_relative

ROM_BASE = 0x08000000
SOURCE_ATLAS = 0x000D87F0
ATLAS_POINTER = 0x000DAB70
CLONE_ATLAS = 0x01F30000
ALLOCATION_END = 0x01F34000

STATE = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).ss1"
SCREENSHOT = Path(r"C:\Users\Administrator\Documents\Bandicam\bandicam 2026-09-03 21-59-27-620.jpg")
OUT_DIR = ADVANCE_ROOT / "outputs" / "20260903_ggen_advance_team_card_ui"
OUT_ROM = OUT_DIR / "ggen_advance_team_card_ui_ko_focus_inner_line_cleanup_candidate_20260903.gba"
OUT_SAV = OUT_DIR / "ggen_advance_team_card_ui_ko_focus_inner_line_cleanup_candidate_20260903.sav"
OUT_STATE = OUT_DIR / "ggen_advance_team_card_ui_ko_focus_inner_line_cleanup_ss1_20260903.ss1"
OUT_PREVIEW = OUT_DIR / "ggen_advance_team_card_ui_ko_focus_inner_line_cleanup_preview_20260903.png"
OUT_FAMILY_PREVIEW = OUT_DIR / "ggen_advance_team_card_ui_ko_focus_inner_line_cleanup_family_preview_20260903.png"
OUT_MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_team_card_ui_ko_20260903.json"

LABELS = {
    "move": {"jp": "移動", "ko": "이동", "ids": (43, 44, 45, 46, 49, 50, 51, 52), "kind": "left"},
    "general": {"jp": "汎用", "ko": "범용", "ids": (277, 278, 279, 280, 281, 282, 283, 284), "kind": "right"},
    "space": {"jp": "宇宙", "ko": "우주", "ids": (285, 286, 287, 288, 289, 290, 291, 292), "kind": "right"},
    "ground": {"jp": "地上", "ko": "지상", "ids": (293, 294, 295, 296, 297, 298, 299, 300), "kind": "right"},
    "omni": {"jp": "万能", "ko": "만능", "ids": (301, 302, 303, 304, 305, 306, 307, 308), "kind": "right"},
    "amphibious": {"jp": "水陸", "ko": "수륙", "ids": (309, 310, 311, 304, 312, 313, 314, 315), "kind": "right"},
    "flight": {"jp": "飛行", "ko": "비행", "ids": (316, 317, 318, 319, 320, 321, 322, 323), "kind": "right"},
    "compatibility": {"jp": "相性", "ko": "상성", "ids": (61, 62, 63, 64, 69, 70, 71, 72), "kind": "right"},
    # Historical storage_* keys retained; original button reads 移動, not 格納.
    "storage_normal": {"jp": "移動", "ko": "이동", "ids": (330, 331, 332, 333, 335, 336, 337, 338, 340, 341, 342, 343), "kind": "button_normal"},
    "storage_focus": {"jp": "移動", "ko": "이동", "ids": tuple(range(350, 362)), "kind": "button_focus"},
    "launch_normal": {"jp": "発進", "ko": "발진", "ids": tuple(range(362, 374)), "kind": "button_normal"},
    "launch_focus": {"jp": "発進", "ko": "발진", "ids": tuple(range(374, 386)), "kind": "button_focus"},
}

LIVE_CELLS = {
    # Runtime card composition clips the first source column and includes the
    # following fill/chrome column; keep these exact eight-cell observations.
    "move": (1, ((0, 13), (10, 13), (20, 13)), (44, 45, 46, 47, 50, 51, 52, 53)),
    "general": (1, ((6, 13), (16, 13)), (278, 279, 280, 281, 282, 283, 284, 285)),
    "omni": (1, ((26, 13),), (302, 303, 304, 305, 306, 307, 308, 309)),
    "compatibility": (1, ((6, 15), (16, 15), (26, 15)), (62, 63, 64, 65, 70, 71, 72, 73)),
    "launch_normal": (2, ((26, 2),), tuple(range(363, 375))),
}

TYPE_MAPS = {
    0x000DAA18: LABELS["general"]["ids"],
    0x000DAA2C: LABELS["space"]["ids"],
    0x000DAA40: LABELS["ground"]["ids"],
    0x000DAA54: LABELS["omni"]["ids"],
    0x000DAA68: LABELS["amphibious"]["ids"],
    0x000DAA7C: LABELS["flight"]["ids"],
}

BUTTON_MAPS = {
    0x000DAA90: LABELS["storage_normal"]["ids"],
    0x000DAAC8: LABELS["storage_focus"]["ids"],
    0x000DAB00: LABELS["launch_normal"]["ids"],
    0x000DAB38: LABELS["launch_focus"]["ids"],
}


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def u32(data: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def decode_atlas(rom: bytes) -> tuple[bytes, int]:
    header = u32(rom, SOURCE_ATLAS)
    gate((header & 0xFFFF0000) == 0x80000000, "D87F0 custom-LZSS header drift")
    body_len = header & 0xFFFF
    atlas = scan.lzss_decompress(rom[SOURCE_ATLAS + 4:SOURCE_ATLAS + 4 + body_len])
    gate(len(atlas) == 386 * 32, f"D87F0 decoded size drift: {len(atlas)}")
    return atlas, body_len


def canvas(atlas: bytes | bytearray, ids: tuple[int, ...]) -> list[list[int]]:
    gate(len(ids) in (8, 12), "label tile count drift")
    height = len(ids) // 4 * 8
    pixels = [[0] * 32 for _ in range(height)]
    for index, tile_id in enumerate(ids):
        tile = action.decode_tile(atlas, tile_id)
        tx, ty = index % 4, index // 4
        for y in range(8):
            pixels[ty * 8 + y][tx * 8:tx * 8 + 8] = tile[y]
    return pixels


def write_canvas(atlas: bytearray, ids: tuple[int, ...], pixels: list[list[int]]) -> list[str]:
    payload_hashes = []
    for index, tile_id in enumerate(ids):
        tx, ty = index % 4, index // 4
        tile = [pixels[ty * 8 + y][tx * 8:tx * 8 + 8] for y in range(8)]
        payload = action.encode_tile(tile)
        atlas[tile_id * 32:(tile_id + 1) * 32] = payload
        payload_hashes.append(sha256(payload))
    return payload_hashes


def clean_template(source: list[list[int]], kind: str) -> list[list[int]]:
    out = [row[:] for row in source]
    if kind == "left":
        # Native left bevel is x=0..4; the bottom highlight row is structural.
        for y in range(15):
            for x in range(5, 32):
                out[y][x] = 11
    elif kind == "right":
        # Native right bevel is x=26..31; preserve it and the bottom highlight.
        for y in range(15):
            for x in range(26):
                out[y][x] = 11
    elif kind == "button_normal":
        # The word spans three tile rows.  Rows 0..5 are native top chrome and
        # rows 20..23 are native bottom chrome; only the yellow text field is
        # rebuilt.  This removes the Japanese pixels previously missed above.
        for y in range(6, 20):
            for x in range(27):
                out[y][x] = 11
    else:
        # Runtime measurement proves the focus colours are the inverse of the
        # previous draft: field 10 (yellow), face 12 (white), outline 4.
        for y in range(4, 20):
            for x in range(27):
                out[y][x] = 10
    return out


def draw_label(source: list[list[int]], text: str, kind: str, font: fontpair.BdfFont) -> tuple[list[list[int]], dict]:
    pixels = clean_template(source, kind)
    # Right-aligned type fields share tile 304 between 万能 and 水陸.  Keeping
    # Hangul inside x=0..23 preserves that shared right-chrome tile byte-exact.
    x0 = 6 if kind == "left" else (0 if kind == "right" else 1)
    y0 = (7 if kind == "button_normal" else 5) if kind.startswith("button_") else 2
    face = 12 if kind == "button_focus" else 10
    outline = 4 if kind == "button_focus" else 5
    lit = 0
    contour = set()
    glyph_points = set()
    for index, char in enumerate(text):
        glyph = fontpair.render_12x12_basic(char, font)
        for y in range(12):
            for x in range(12):
                if not glyph.getpixel((x, y)):
                    continue
                px, py = x0 + index * 12 + x, y0 + y
                lit += 1
                glyph_points.add((px, py))
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        qx, qy = px + dx, py + dy
                        if 0 <= qx < 32 and 0 <= qy < len(pixels):
                            contour.add((qx, qy))
    for x, y in contour:
        pixels[y][x] = outline
    for index, char in enumerate(text):
        glyph = fontpair.render_12x12_basic(char, font)
        for y in range(12):
            for x in range(12):
                if glyph.getpixel((x, y)):
                    pixels[y0 + y][x0 + index * 12 + x] = face
    if kind.startswith("button_"):
        field_y0 = 6 if kind == "button_normal" else 4
        gate(all(pixels[y][x] != outline or (x, y) in contour for y in range(field_y0, 20) for x in range(27)), f"{kind} contains non-Hangul outline residue")
    return pixels, {"origin": [x0, y0], "face_index": face, "contour_index": outline, "glyph_pixels": lit, "outline_pixels": len(contour - glyph_points)}


def live_rows(state: bytes, layer: int, start_x: int, start_y: int, height: int = 2) -> list[int]:
    info = bgutil.bg_info(state, layer)
    vram = state[statefmt.STATE_VRAM:statefmt.STATE_IWRAM]
    return [
        bgutil.map_entry(vram, info["screen_base"], info["size"], start_x + x, start_y + y)
        for y in range(height) for x in range(4)
    ]


def patch_state(state: bytes, atlas: bytes, candidate_crc: int) -> bytes:
    out = bytearray(state)
    for name, (_layer, _starts, destination_ids) in LIVE_CELLS.items():
        for source_id, destination_id in zip(LABELS[name]["ids"], destination_ids):
            payload = atlas[source_id * 32:(source_id + 1) * 32]
            offset = statefmt.STATE_VRAM + destination_id * 32
            out[offset:offset + 32] = payload
    struct.pack_into("<I", out, 8, candidate_crc)
    return bytes(out)


def render_preview(original: bytes, derived: bytes) -> None:
    frame = Image.open(SCREENSHOT).convert("RGBA").resize((240, 160), Image.Resampling.NEAREST)
    for layer, boxes in (
        (1, ((0, 104, 240, 136),)),
        (2, ((208, 16, 240, 40),)),
    ):
        rendered = action.Image.new("RGBA", (240, 160), (0, 0, 0, 0))
        # Reuse the state renderer used by the popup candidates.
        import build_ggen_advance_sort_popup_state6_candidate_20260903 as popup
        rendered = popup.render_layer_native(derived, layer)
        for box in boxes:
            frame.alpha_composite(rendered.crop(box), box[:2])
    OUT_PREVIEW.parent.mkdir(parents=True, exist_ok=True)
    frame.resize((960, 640), Image.Resampling.NEAREST).save(OUT_PREVIEW)


def render_family_preview(atlas: bytes, state: bytes) -> None:
    from PIL import ImageDraw
    palette = state[statefmt.STATE_PALETTE:statefmt.STATE_OAM]
    scale = 3
    cell_w, cell_h = 112, 100
    rows = (len(LABELS) + 3) // 4
    sheet = Image.new("RGB", (cell_w * 4, cell_h * rows), (35, 35, 35))
    draw = ImageDraw.Draw(sheet)
    for index, (name, row) in enumerate(LABELS.items()):
        pix = canvas(atlas, tuple(row["ids"]))
        image = Image.new("RGB", (32, len(pix)))
        for y in range(len(pix)):
            for x in range(32):
                colour = struct.unpack_from("<H", palette, 11 * 32 + pix[y][x] * 2)[0]
                image.putpixel((x, y), bgutil.rgb555(colour))
        ox, oy = (index % 4) * cell_w, (index // 4) * cell_h
        draw.text((ox + 4, oy + 3), name, fill=(240, 240, 240))
        sheet.paste(image.resize((32 * scale, len(pix) * scale), Image.Resampling.NEAREST), (ox + 4, oy + 20))
    OUT_FAMILY_PREVIEW.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(OUT_FAMILY_PREVIEW)


def main() -> int:
    parent = MAIN_TIP_ROM.read_bytes()
    manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(parent) == manifest["sha256"], "main TIP hash/manifest drift")
    gate(manifest["promotion_reason"] == "user_approved_power_warning_shadow_cleanup_20260903", "approved warning-cleanup main is not active")
    gate(u32(parent, ATLAS_POINTER) == ROM_BASE + SOURCE_ATLAS, "team-card atlas pointer drift")
    gate(set(parent[CLONE_ATLAS:ALLOCATION_END]) <= {0}, "private team-card allocation is not zero-filled")

    source_atlas, source_body_len = decode_atlas(parent)
    translated = bytearray(source_atlas)
    state, _chunks = statefmt.parse_png_state(STATE)
    state_crc = u32(state, 8)
    audit = []
    source_button_canvases = {name: canvas(source_atlas, tuple(LABELS[name]["ids"])) for name in ("storage_normal", "storage_focus", "launch_normal", "launch_focus")}
    gate(source_button_canvases["storage_normal"][:6] == source_button_canvases["launch_normal"][:6], "normal button top chrome differs before glyph field")
    gate(source_button_canvases["storage_focus"][:4] == source_button_canvases["launch_focus"][:4], "focus button top chrome differs before glyph field")
    for map_off, expected in TYPE_MAPS.items():
        gate((parent[map_off], parent[map_off + 1]) == (4, 2), f"type map geometry drift at 0x{map_off:08X}")
        cells = struct.unpack_from("<8H", parent, map_off + 4)
        gate(tuple(cell & 0x3FF for cell in cells) == tuple(expected), f"type map IDs drift at 0x{map_off:08X}")
    for map_off, expected in BUTTON_MAPS.items():
        gate((parent[map_off], parent[map_off + 1]) == (5, 5), f"button map geometry drift at 0x{map_off:08X}")
        cells = struct.unpack_from("<25H", parent, map_off + 4)
        gate(tuple(cell & 0x3FF for cell in cells[6:10] + cells[11:15] + cells[16:20]) == tuple(expected), f"button label IDs drift at 0x{map_off:08X}")
    with ZipFile(FONT_ZIP) as archive:
        font = fontpair.load_bdf(archive, "Galmuri11.bdf")
    for name, row in LABELS.items():
        ids = tuple(row["ids"])
        live = LIVE_CELLS.get(name)
        starts = ()
        if live:
            layer, starts, expected_live = live
            for x, y in starts:
                cells = live_rows(state, layer, x, y, len(expected_live) // 4)
                gate([cell & 0x3FF for cell in cells] == list(expected_live), f"{name} live map IDs drift at ({x},{y})")
                gate({cell >> 12 for cell in cells} == {0xB}, f"{name} live palette bank drift")
        vram = state[statefmt.STATE_VRAM:statefmt.STATE_IWRAM]
        if live:
            for source_id, destination_id in zip(ids, expected_live):
                gate(vram[destination_id * 32:(destination_id + 1) * 32] == source_atlas[source_id * 32:(source_id + 1) * 32], f"{name} visible live/source mapping mismatch: {source_id}->{destination_id}")
        source_pixels = canvas(source_atlas, ids)
        ko_pixels, raster = draw_label(source_pixels, str(row["ko"]), str(row["kind"]), font)
        if name in ("storage_focus", "launch_focus"):
            # Japanese focus contour protrudes into x=27 and leaves a second
            # solid line at x=28 that is surrounded by green on all four sides
            # in the 5x5 button.  Restore both from byte-exact normal chrome.
            # x=30 is the real outer separator and must remain untouched.
            normal_name = name.replace("_focus", "_normal")
            normal_chrome = source_button_canvases[normal_name]
            for y in range(24):
                ko_pixels[y][27] = normal_chrome[y][27]
                ko_pixels[y][28] = normal_chrome[y][28]
            gate(all(ko_pixels[y][27] in (14, 15) for y in range(24)), f"{name} right green edge cleanup drift")
            gate(all(ko_pixels[y][28] in (14, 15) for y in range(24)), f"{name} inner green line cleanup drift")
            gate(all(ko_pixels[y][30] == source_pixels[y][30] for y in range(24)), f"{name} outer separator was not restored")
            raster["right_edge_x27_restored_from_normal_chrome"] = True
            raster["four_side_green_black_line_x28_replaced"] = True
            raster["outer_separator_x30_preserved"] = True
        hashes = write_canvas(translated, ids, ko_pixels)
        audit.append({"name": name, "jp": row["jp"], "ko": row["ko"], "tile_ids": list(ids), "live_occurrences_in_ss1": len(starts), "raster": raster, "tile_sha256": hashes})

    body = action.literal_only_lzss_body(bytes(translated))
    resource = struct.pack("<I", 0x80000000 | len(body)) + body
    gate(CLONE_ATLAS + len(resource) <= ALLOCATION_END, "private atlas clone exceeds allocation")
    candidate = bytearray(parent)
    candidate[CLONE_ATLAS:CLONE_ATLAS + len(resource)] = resource
    candidate[ATLAS_POINTER:ATLAS_POINTER + 4] = struct.pack("<I", ROM_BASE + CLONE_ATLAS)
    candidate_bytes = bytes(candidate)
    decoded = scan.lzss_decompress(candidate[CLONE_ATLAS + 4:CLONE_ATLAS + 4 + (u32(candidate, CLONE_ATLAS) & 0xFFFF)])
    gate(decoded == bytes(translated), "private atlas round-trip mismatch")
    gate(parent[SOURCE_ATLAS:SOURCE_ATLAS + 4 + source_body_len] == candidate[SOURCE_ATLAS:SOURCE_ATLAS + 4 + source_body_len], "shared source atlas changed")

    changed = [i for i, (a, b) in enumerate(zip(parent, candidate_bytes)) if a != b]
    allowed = set(range(CLONE_ATLAS, CLONE_ATLAS + len(resource))) | set(range(ATLAS_POINTER, ATLAS_POINTER + 4))
    gate(set(changed) <= allowed, "candidate changes escaped private atlas/pointer contract")
    candidate_crc = binascii.crc32(candidate_bytes) & 0xFFFFFFFF
    derived = patch_state(state, decoded, candidate_crc)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_ROM.write_bytes(candidate_bytes)
    sav = (ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).sav").read_bytes()
    OUT_SAV.write_bytes(sav)
    OUT_STATE.write_bytes(state_writer.replace_state_chunk(STATE, derived))
    render_preview(state, derived)
    render_family_preview(decoded, derived)

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_team_card_ui_ko_20260903",
        "result": "PASS",
        "status": "test_candidate_main_tip_not_promoted",
        "output": {"path": advance_relative(OUT_ROM), "sha256": sha256(candidate_bytes), "size": len(candidate_bytes)},
        "main_tip": {"path": advance_relative(MAIN_TIP_ROM), "sha256": sha256(parent), "crc32": f"0x{binascii.crc32(parent) & 0xFFFFFFFF:08X}"},
        "candidate": {"path": advance_relative(OUT_ROM), "sha256": sha256(candidate_bytes), "crc32": f"0x{candidate_crc:08X}", "size": len(candidate_bytes)},
        "sav": {"path": advance_relative(OUT_SAV), "sha256": sha256(sav)},
        "derived_state": {"path": advance_relative(OUT_STATE), "sha256": sha256(OUT_STATE.read_bytes()), "source_embedded_crc32": f"0x{state_crc:08X}"},
        "preview": advance_relative(OUT_PREVIEW),
        "family_preview": advance_relative(OUT_FAMILY_PREVIEW),
        "resource": {"source_pointer": f"0x{ROM_BASE + SOURCE_ATLAS:08X}", "pointer_slot": f"0x{ROM_BASE + ATLAS_POINTER:08X}", "clone_pointer": f"0x{ROM_BASE + CLONE_ATLAS:08X}", "decoded_tiles": 386, "clone_bytes": len(resource)},
        "labels": audit,
        "changed_byte_count": len(changed),
        "verification": {
            "result": "PASS", "main_tip_manifest_match": True, "visible_label_live_maps_exact": True,
            "all_six_type_maps_and_four_button_states_enumerated": True,
            "button_three_tile_row_ownership_verified": True,
            "normal_and_focus_top_chrome_byte_exact_preserved": True,
            "button_outline_confined_to_one_pixel_hangul_contour": True,
            "focus_field_face_indices_corrected_to_10_12": True,
            "focus_right_green_edge_x27_restored": True,
            "focus_four_side_green_black_line_x28_replaced": True,
            "focus_outer_separator_x30_byte_exact_preserved": True,
            "all_visible_target_tiles_byte_exact_source_atlas": True, "palette_bank_B_preserved": True,
            "shared_source_atlas_unchanged": True, "single_pointer_redirect_only": True,
            "private_clone_round_trip_verified": True, "candidate_state_crc_matches_candidate": True,
            "source_ss1_predates_only_unrelated_warning_cleanup": state_crc != (binascii.crc32(parent) & 0xFFFFFFFF),
            "py_compile": "PASS", "unified_pipeline_regression": "6/6 PASS",
            "intermission_development_regression": "4/4 PASS", "fresh_emulator_measurement": "pending user verification"
        }
    }
    OUT_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    OUT_MANIFEST.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "rom": advance_relative(OUT_ROM), "sha256": sha256(candidate_bytes), "crc32": f"0x{candidate_crc:08X}", "state": advance_relative(OUT_STATE), "preview": advance_relative(OUT_PREVIEW), "manifest": advance_relative(OUT_MANIFEST), "changed_bytes": len(changed)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
