#!/usr/bin/env python3
"""Build a battle-weapon UI POC by overriding the original 8x16 JP font slots.

The battle weapon selector still renders Japanese mini labels (実/攻/命/弾 and
射/近 + 単/全) even though the status UI uses a separately patched graphics
atlas.  Screenshot measurement shows these battle labels have the exact
8x16-font geometry: one 8px-wide glyph for 実/攻/命/弾 and two adjacent 8px
cells for 射単/近単/射全/近全.  The canonical Korean main TIP intentionally
leaves the original 0x00094028 font bank untouched, so this POC changes only
those original glyph slots to native Galmuri7 Korean bitmaps.

No 12x12 font, text stream, palette, tilemap, compressed graphics atlas, or
expanded translation font is modified.  This makes the ROM suitable for a
focused in-game A/B check of the battle screen shown by the user.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from zipfile import ZipFile

from PIL import Image

import build_ggen_advance_ko_poc as ko
import test_ggen_advance_font_pair as fontpair
from ggen_advance_project_paths import ADVANCE_ROOT, FONT_ZIP, MAIN_TIP_MANIFEST, MAIN_TIP_ROM

JP_ROM = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Japan).gba"
DEFAULT_OUT = ADVANCE_ROOT / "outputs" / "20260829_ggen_advance_battle_ui" / "ggen_advance_battle_weapon_font_galmuri7_poc_20260829.gba"
DEFAULT_MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_battle_weapon_font_galmuri7_poc_20260829.json"
DEFAULT_PREVIEW = ADVANCE_ROOT / "outputs" / "20260829_ggen_advance_battle_ui" / "ggen_advance_battle_weapon_font_galmuri7_preview_20260829.png"

# Measured / identified 8x16 source slots.
# 0x00C0=弾 is supported by weapon/defence corpus frames such as 実体弾 and 無駄弾.
# 0x042B=単 is supported by the weapon-name frame <042B><00BB>砲 = 単装砲 and
# is also the strongest direct screenshot-shape match for the battle 射単 label.
# 全 has two independently verified 8x16 slots in the source font, so both are
# replaced to cover both UI consumers without guessing which duplicate is used.
BATTLE_GLYPHS = (
    (0x0323, "実", "실", "weapon_type_real"),
    (0x02B7, "攻", "공", "attack"),
    (0x00D0, "命", "명", "hit"),
    (0x00C0, "弾", "탄", "ammo"),
    (0x0324, "射", "사", "ranged"),
    (0x0248, "近", "근", "melee"),
    (0x042B, "単", "단", "single_target"),
    (0x00B9, "全", "전", "all_target_duplicate_a"),
    (0x05FE, "全", "전", "all_target_duplicate_b"),
)


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def gate(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"gate failed: {message}")


def render_galmuri7_8x16(char: str, font: fontpair.BdfFont) -> Image.Image:
    glyph = font.glyphs.get(ord(char))
    gate(glyph is not None, f"Galmuri7 glyph missing: {char}")
    gate(glyph.height == 7 and glyph.width in (6, 7), f"unexpected Galmuri7 BBX for {char}: {glyph.width}x{glyph.height}")
    native = font.render(char, glyph.width, glyph.height)
    canvas = Image.new("1", (8, 16), 0)
    x0 = (8 - native.width) // 2
    y0 = (16 - native.height) // 2
    canvas.paste(native, (x0, y0))
    return canvas


def render_preview(rows: list[dict[str, object]], out: Path) -> None:
    scale = 8
    cell_w, cell_h = 8 * scale, 16 * scale
    margin = 16
    width = margin * 2 + len(rows) * cell_w
    height = margin * 3 + cell_h * 2
    canvas = Image.new("RGB", (width, height), (30, 34, 40))
    for i, row in enumerate(rows):
        before = row["before_image"]
        after = row["after_image"]
        x = margin + i * cell_w
        canvas.paste(before.resize((cell_w, cell_h), Image.Resampling.NEAREST).convert("RGB"), (x, margin))
        canvas.paste(after.resize((cell_w, cell_h), Image.Resampling.NEAREST).convert("RGB"), (x, margin * 2 + cell_h))
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", type=Path, default=MAIN_TIP_ROM)
    ap.add_argument("--jp-rom", type=Path, default=JP_ROM)
    ap.add_argument("--font-zip", type=Path, default=FONT_ZIP)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--preview", type=Path, default=DEFAULT_PREVIEW)
    args = ap.parse_args()

    base = args.base.read_bytes()
    jp = args.jp_rom.read_bytes()
    gate(len(base) == 32 * 1024 * 1024, f"main TIP must be 32 MiB: {len(base)}")
    gate(len(jp) == 16 * 1024 * 1024, f"Japanese ROM must be 16 MiB: {len(jp)}")

    main_manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(main_manifest.get("sha256") == sha256(base), "main TIP hash differs from approved manifest")
    gate(main_manifest.get("canonical_path") == MAIN_TIP_ROM.name, "unexpected canonical main TIP path")

    # The current Korean build must still carry the original JP 8x16 glyphs at
    # these source slots.  If a future pipeline changes them, stop rather than
    # silently overwrite a different consumer.
    source_checks = []
    for slot, source_char, target_char, role in BATTLE_GLYPHS:
        off = ko.FONT_8X16_BASE + slot * ko.FONT_8X16_STRIDE
        jp_raw = jp[off : off + ko.FONT_8X16_STRIDE]
        base_raw = base[off : off + ko.FONT_8X16_STRIDE]
        gate(base_raw == jp_raw, f"battle source font slot already differs from JP: 0x{slot:04X}")
        source_checks.append({
            "slot": f"0x{slot:04X}",
            "source": source_char,
            "target": target_char,
            "role": role,
            "file_offset": f"0x{off:08X}",
            "source_sha256": sha256(jp_raw),
        })

    with ZipFile(args.font_zip) as archive:
        font7 = fontpair.load_bdf(archive, "Galmuri7.bdf")

    patched = bytearray(base)
    reports: list[dict[str, object]] = []
    preview_rows: list[dict[str, object]] = []
    changed_offsets: set[int] = set()
    for slot, source_char, target_char, role in BATTLE_GLYPHS:
        off = ko.FONT_8X16_BASE + slot * ko.FONT_8X16_STRIDE
        before_raw = bytes(patched[off : off + ko.FONT_8X16_STRIDE])
        before_image = ko.unpack_8x16(before_raw)
        after_image = render_galmuri7_8x16(target_char, font7)
        after_raw = ko.pack_8x16(after_image)
        gate(len(after_raw) == ko.FONT_8X16_STRIDE, "packed battle glyph size drift")
        patched[off : off + ko.FONT_8X16_STRIDE] = after_raw
        for i, (a, b) in enumerate(zip(before_raw, after_raw)):
            if a != b:
                changed_offsets.add(off + i)
        reports.append({
            "slot": f"0x{slot:04X}",
            "source": source_char,
            "target": target_char,
            "role": role,
            "file_offset": f"0x{off:08X}",
            "before_sha256": sha256(before_raw),
            "after_sha256": sha256(after_raw),
            "before_ink_pixels": sum(1 for y in range(16) for x in range(8) if before_image.getpixel((x, y))),
            "after_ink_pixels": sum(1 for y in range(16) for x in range(8) if after_image.getpixel((x, y))),
            "font": "Galmuri7.bdf",
            "placement": "native 6/7x7 glyph centered in unchanged 8x16 source-font cell",
        })
        preview_rows.append({"before_image": before_image, "after_image": after_image})

    output = bytes(patched)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(output)
    render_preview(preview_rows, args.preview)
    source_save = args.base.with_suffix(".sav")
    output_save = args.out.with_suffix(".sav")
    if source_save.is_file():
        shutil.copy2(source_save, output_save)
    else:
        output_save = None

    diffs = [i for i, (a, b) in enumerate(zip(base, output)) if a != b]
    gate(set(diffs) == changed_offsets, "unexpected bytes changed outside intended font slots")
    allowed_ranges = [
        (ko.FONT_8X16_BASE + slot * ko.FONT_8X16_STRIDE, ko.FONT_8X16_BASE + (slot + 1) * ko.FONT_8X16_STRIDE)
        for slot, *_ in BATTLE_GLYPHS
    ]
    gate(all(any(lo <= off < hi for lo, hi in allowed_ranges) for off in diffs), "font patch escaped allowed ranges")

    manifest = {
        "schema_version": 1,
        "kind": "ggen_advance_battle_weapon_font_galmuri7_poc",
        "result": "PASS",
        "base": {
            "path": args.base.name,
            "sha256": sha256(base),
            "approved_main_tip": True,
        },
        "output": {
            "path": str(args.out.relative_to(ADVANCE_ROOT)).replace('\\', '/'),
            "size": len(output),
            "sha256": sha256(output),
            "preview": str(args.preview.relative_to(ADVANCE_ROOT)).replace('\\', '/'),
            "save_copy": str(output_save.relative_to(ADVANCE_ROOT)).replace('\\', '/') if output_save else None,
        },
        "source_contract": {
            "font_8x16_base": f"0x{ko.FONT_8X16_BASE:08X}",
            "font_8x16_stride": ko.FONT_8X16_STRIDE,
            "original_slots_unchanged_before_patch": True,
            "checks": source_checks,
        },
        "glyphs": reports,
        "battle_screen_mapping": {
            "screenshot_layout": ["実", "攻", "命", "弾", "射単 / 近単 / 射全 / 近全"],
            "korean_targets": ["실", "공", "명", "탄", "사단 / 근단 / 사전 / 근전"],
            "full_target_slots": len(BATTLE_GLYPHS),
            "all_target_duplicate_slots": ["0x00B9", "0x05FE"],
            "ammo_slot_evidence": "0x00C0 corpus frames include 実体弾 and 無駄弾",
            "single_slot_evidence": "0x042B weapon-name frame <042B><00BB>砲 = 単装砲; strongest measured screenshot-shape candidate",
        },
        "verification": {
            "result": "PASS",
            "rom_size_unchanged": len(output) == len(base),
            "12x12_font_untouched": output[ko.FONT_12X12_BASE : ko.FONT_12X12_BASE + ko.FONT_12X12_COUNT * ko.FONT_12X12_STRIDE] == base[ko.FONT_12X12_BASE : ko.FONT_12X12_BASE + ko.FONT_12X12_COUNT * ko.FONT_12X12_STRIDE],
            "only_intended_8x16_slot_bytes_changed": True,
            "changed_bytes": len(diffs),
            "changed_file_offset_min": f"0x{min(diffs):08X}" if diffs else None,
            "changed_file_offset_max": f"0x{max(diffs):08X}" if diffs else None,
            "palette_untouched": True,
            "tilemaps_untouched": True,
            "status_graphics_atlas_untouched": True,
            "battle_d54_atlas_untouched": True,
        },
        "measurement_gate": "Do not promote until the battle weapon selector is measured in-game. If Japanese remains, the next target is the independent D54 graphics/VRAM consumer rather than broadening this font patch blindly.",
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "output": manifest["output"],
        "changed_bytes": len(diffs),
        "glyph_slots": [row["slot"] for row in reports],
        "base_sha256": sha256(base),
    }, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
