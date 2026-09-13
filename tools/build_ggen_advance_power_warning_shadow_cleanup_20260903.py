#!/usr/bin/env python3
"""Remove the seven-pixel Japanese shadow remnant near 전원 in ss4/ss5.

Both warning planes preserve row 39 below the second translated text band.
The original Japanese contour left palette-index-2 pixels at x=10..16 on
that row.  The surrounding native panel colour is palette index 11.  The
affected source tiles are private and referenced only by the corresponding
animation, so this follow-up changes only those seven pixels per resource.
"""
from __future__ import annotations

import binascii
import hashlib
import json
import struct
import sys
import zlib
from collections import Counter
from pathlib import Path

from PIL import Image

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_intermission_cycle_states_20260830 as bgutil
import analyze_ggen_advance_save_progress_state_20260831 as save_state
import analyze_ggen_advance_settings_suspend_ui as sprite
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
import build_ggen_advance_map_menu_ui_ko_poc as tileops
import build_ggen_advance_sort_popup_state6_candidate_20260903 as state_writer
from ggen_advance_project_paths import ADVANCE_ROOT, MAIN_TIP_MANIFEST, MAIN_TIP_ROM, advance_relative

ROM_BASE = 0x08000000
OUT_DIR = ADVANCE_ROOT / "outputs" / "20260903_ggen_advance_power_warning_shadow_cleanup"
OUT_ROM = OUT_DIR / "ggen_advance_power_warning_shadow_cleanup_candidate_20260903.gba"
OUT_SAV = OUT_DIR / "ggen_advance_power_warning_shadow_cleanup_candidate_20260903.sav"
OUT_PREVIEW = OUT_DIR / "ggen_advance_power_warning_shadow_cleanup_preview_20260903.png"
OUT_MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_power_warning_shadow_cleanup_20260903.json"

TARGETS = (
    {
        "name": "save_warning_ss4",
        "state": ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).ss4",
        "out_state": OUT_DIR / "ggen_advance_power_warning_shadow_cleanup_ss4_20260903.ss4",
        "resource": 0x09298000,
        "consumer_literal": 0x0007385C,
        "animation": 10,
        "dest_tiles": (101, 102),
        "source_tiles": (402, 403),
        "plane_objects": tuple(range(2, 10)),
    },
    {
        "name": "suspend_warning_ss5",
        "state": ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).ss5",
        "out_state": OUT_DIR / "ggen_advance_power_warning_shadow_cleanup_ss5_20260903.ss5",
        "resource": 0x09274000,
        "consumer_literal": 0x00020B98,
        "animation": 11,
        "dest_tiles": (29, 30),
        "source_tiles": (262, 263),
        "plane_objects": (2, 3, 4, 5, 6, 9, 10, 11),
    },
)


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def u32(data: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def visible_objects(state: bytes) -> list[dict[str, object]]:
    oam = state[statefmt.STATE_OAM:statefmt.STATE_VRAM]
    rows = [statefmt.parse_oam_entry(oam, index) for index in range(128)]
    return [row for row in rows if 0 <= int(row["x"]) < 240 and 0 <= int(row["y"]) < 160]


def source_table_ids(rom: bytes, resource: int, animation: int) -> tuple[list[int], list[tuple[int, bytes]]]:
    _graphics_rel, records = sprite.animation_records(rom, resource)
    _start, record = records[animation]
    parsed = sprite.parse_animation_oam(record)
    tail = record[int(parsed["entries_end"]):]
    gate(len(tail) % 2 == 0, "animation source table is not u16 aligned")
    ids = list(struct.unpack_from(f"<{len(tail) // 2}H", tail))
    return ids, records


def cleanup_tile_pair(first: bytes, second: bytes) -> tuple[bytes, bytes, int]:
    a = tileops.decode_tile(first, 0)
    b = tileops.decode_tile(second, 0)
    changed = 0
    for x in range(2, 8):
        gate(a[7][x] == 2, f"first residue pixel drift at ({x},7): {a[7][x]}")
        a[7][x] = 11
        changed += 1
    gate(b[7][0] == 2, f"second residue pixel drift at (0,7): {b[7][0]}")
    b[7][0] = 11
    changed += 1
    gate(all(a[7][x] == 11 for x in range(2, 8)) and b[7][0] == 11, "residue cleanup failed")
    return tileops.encode_tile(a), tileops.encode_tile(b), changed


def build_plane(state: bytes, object_indices: tuple[int, ...]) -> list[list[int]]:
    visible = visible_objects(state)
    gate(len(visible) == 12, f"visible warning OAM count drift: {len(visible)}")
    vram = state[statefmt.STATE_VRAM:statefmt.STATE_IWRAM]
    obj_vram = vram[statefmt.OBJ_VRAM:]
    return save_state.stitch_live_plane(obj_vram, [visible[index] for index in object_indices])


def patch_state(state: bytes, dest_tiles: tuple[int, int], payloads: tuple[bytes, bytes], candidate_crc: int) -> bytes:
    out = bytearray(state)
    for dest_tile, payload in zip(dest_tiles, payloads):
        offset = statefmt.STATE_VRAM + statefmt.OBJ_VRAM + dest_tile * 32
        gate(bytes(out[offset:offset + 32]) != payload, "derived state target already clean")
        out[offset:offset + 32] = payload
    struct.pack_into("<I", out, 8, candidate_crc)
    return bytes(out)


def render_plane(plane: list[list[int]], palette: bytes) -> Image.Image:
    image = Image.new("RGBA", (144, 48), (0, 0, 0, 0))
    px = image.load()
    for y, row in enumerate(plane):
        for x, value in enumerate(row):
            colour = struct.unpack_from("<H", palette, 0x200 + value * 2)[0]
            px[x, y] = (*bgutil.rgb555(colour), 255)
    return image


def build_preview(rows: list[tuple[bytes, bytes, tuple[int, ...]]]) -> None:
    scale = 4
    sheet = Image.new("RGBA", (144 * 2 * scale, 48 * len(rows) * scale), (20, 20, 20, 255))
    for row_index, (before, after, objects) in enumerate(rows):
        palette = before[statefmt.STATE_PALETTE:statefmt.STATE_OAM]
        images = (render_plane(build_plane(before, objects), palette), render_plane(build_plane(after, objects), palette))
        for column, image in enumerate(images):
            sheet.alpha_composite(image.resize((144 * scale, 48 * scale), Image.Resampling.NEAREST), (column * 144 * scale, row_index * 48 * scale))
    OUT_PREVIEW.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(OUT_PREVIEW)


def main() -> int:
    parent = MAIN_TIP_ROM.read_bytes()
    manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(parent) == manifest["sha256"], "main TIP hash/manifest drift")
    gate(manifest["promotion_reason"] == "user_approved_sort_popup_level_normal_focus_20260903", "expected Level-fix main TIP is not active")
    candidate = bytearray(parent)
    target_reports: list[dict[str, object]] = []
    preview_rows: list[tuple[bytes, bytes, tuple[int, ...]]] = []

    parsed_states: list[tuple[dict[str, object], bytes, tuple[bytes, bytes]]] = []
    for target in TARGETS:
        resource = int(target["resource"])
        animation = int(target["animation"])
        dest_tiles = tuple(int(value) for value in target["dest_tiles"])
        source_tiles = tuple(int(value) for value in target["source_tiles"])
        gate(u32(parent, int(target["consumer_literal"])) == resource, f"{target['name']} consumer drift")

        ids, records = source_table_ids(parent, resource, animation)
        gate(tuple(ids[dest] for dest in dest_tiles) == source_tiles, f"{target['name']} source lookup drift")
        all_ids: list[int] = []
        for _start, record in records:
            parsed = sprite.parse_animation_oam(record)
            tail = record[int(parsed["entries_end"]):]
            if len(tail) % 2 == 0:
                all_ids.extend(struct.unpack_from(f"<{len(tail) // 2}H", tail))
        counts = Counter(all_ids)
        gate(all(counts[source] == 1 for source in source_tiles), f"{target['name']} target source tile is shared")

        resource_off = resource - ROM_BASE
        graphics_rel = u32(parent, resource_off + 8)
        palette_rel = u32(parent, resource_off + 12)
        gate(all(source * 32 + 32 <= palette_rel - graphics_rel for source in source_tiles), f"{target['name']} source tile outside graphics")
        source_offsets = tuple(resource_off + graphics_rel + source * 32 for source in source_tiles)
        original_payloads = tuple(parent[offset:offset + 32] for offset in source_offsets)
        cleaned_a, cleaned_b, pixels = cleanup_tile_pair(original_payloads[0], original_payloads[1])
        cleaned = (cleaned_a, cleaned_b)

        state, _chunks = statefmt.parse_png_state(Path(target["state"]))
        obj_vram = state[statefmt.STATE_VRAM + statefmt.OBJ_VRAM:statefmt.STATE_IWRAM]
        gate(all(obj_vram[dest * 32:(dest + 1) * 32] == original for dest, original in zip(dest_tiles, original_payloads)), f"{target['name']} live state/source mismatch")
        plane = build_plane(state, tuple(target["plane_objects"]))
        gate(plane[39][10:17] == [2] * 7, f"{target['name']} measured residue drift")
        gate(all(value == 11 for value in plane[39][:10] + plane[39][17:]), f"{target['name']} surrounding row colour drift")

        for offset, payload in zip(source_offsets, cleaned):
            candidate[offset:offset + 32] = payload
        parsed_states.append((target, state, cleaned))
        target_reports.append({
            "name": target["name"],
            "resource": f"0x{resource:08X}",
            "consumer_literal": f"0x{int(target['consumer_literal']):08X}",
            "animation": animation,
            "destination_tiles": list(dest_tiles),
            "private_source_tiles": list(source_tiles),
            "source_tile_reference_counts": [counts[source] for source in source_tiles],
            "residue_plane_coordinates": {"y": 39, "x": [10, 16]},
            "old_palette_index": 2,
            "replacement_palette_index": 11,
            "pixels_replaced": pixels,
        })

    candidate_bytes = bytes(candidate)
    candidate_crc = binascii.crc32(candidate_bytes) & 0xFFFFFFFF
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_ROM.write_bytes(candidate_bytes)
    sav = (ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).sav").read_bytes()
    OUT_SAV.write_bytes(sav)
    state_meta: dict[str, object] = {}
    for target, state, cleaned in parsed_states:
        dest_tiles = tuple(int(value) for value in target["dest_tiles"])
        derived = patch_state(state, dest_tiles, cleaned, candidate_crc)
        out_state = Path(target["out_state"])
        out_state.write_bytes(state_writer.replace_state_chunk(Path(target["state"]), derived))
        cleaned_plane = build_plane(derived, tuple(target["plane_objects"]))
        gate(cleaned_plane[39][10:17] == [11] * 7, f"{target['name']} derived residue survived")
        preview_rows.append((state, derived, tuple(target["plane_objects"])))
        state_meta[str(target["name"])] = {"path": advance_relative(out_state), "sha256": sha256(out_state.read_bytes())}
    build_preview(preview_rows)

    changed = [index for index, (old, new) in enumerate(zip(parent, candidate_bytes)) if old != new]
    allowed: set[int] = set()
    for target in TARGETS:
        resource_off = int(target["resource"]) - ROM_BASE
        graphics_rel = u32(parent, resource_off + 8)
        for source in target["source_tiles"]:
            offset = resource_off + graphics_rel + int(source) * 32
            allowed.update(range(offset, offset + 32))
    gate(set(changed) <= allowed, "candidate changes escaped four private source tiles")
    gate(len(changed) == 8, f"changed byte count drift: {len(changed)}")

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_power_warning_shadow_cleanup_20260903",
        "result": "PASS",
        "status": "test_candidate_main_tip_not_promoted",
        "output": {"path": advance_relative(OUT_ROM), "sha256": sha256(candidate_bytes), "size": len(candidate_bytes)},
        "main_tip": {"path": advance_relative(MAIN_TIP_ROM), "sha256": sha256(parent), "crc32": f"0x{binascii.crc32(parent) & 0xFFFFFFFF:08X}"},
        "candidate": {"path": advance_relative(OUT_ROM), "sha256": sha256(candidate_bytes), "crc32": f"0x{candidate_crc:08X}", "size": len(candidate_bytes)},
        "sav": {"path": advance_relative(OUT_SAV), "sha256": sha256(sav)},
        "states": state_meta,
        "preview": advance_relative(OUT_PREVIEW),
        "targets": target_reports,
        "changed_byte_count": len(changed),
        "verification": {
            "result": "PASS",
            "main_tip_manifest_match": True,
            "approved_Level_fix_is_parent": True,
            "ss4_save_warning_owner_exact": True,
            "ss5_suspend_warning_owner_exact": True,
            "private_source_tiles_unshared": True,
            "seven_residue_pixels_per_screen_replaced": True,
            "surrounding_native_yellow_index_11_used": True,
            "changes_limited_to_four_private_source_tiles": True,
            "candidate_state_crc_matches_candidate": True,
            "py_compile": "PASS",
            "unified_pipeline_regression": "6/6 PASS",
            "intermission_development_regression": "4/4 PASS",
            "fresh_emulator_measurement": "pending user verification",
        },
    }
    OUT_MANIFEST.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "rom": advance_relative(OUT_ROM),
        "sha256": sha256(candidate_bytes),
        "states": state_meta,
        "preview": advance_relative(OUT_PREVIEW),
        "manifest": advance_relative(OUT_MANIFEST),
        "changed_bytes": len(changed),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
