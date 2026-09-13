#!/usr/bin/env python3
"""Repaint battle-evade Hangul glyphs with canonical Galmuri11-Condensed.

The promoted BtlCmd labels already point at the Korean tokens for 완전회피 and
회피.  This follow-up verifies that their four 8x16 slot payloads differ from
the canonical native Galmuri11-Condensed BDF, then repaints only those slots.
The 12x12 font path, BtlCmd strings/table/bytecode, palettes, and graphics
atlases remain byte-identical.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from zipfile import ZipFile

from PIL import Image, ImageDraw

import build_ggen_advance_ko_poc as fontops
from ggen_advance_project_paths import ADVANCE_ROOT, FONT_ZIP
import test_ggen_advance_font_pair as fontpair


MAIN_ROM = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).gba"
MAIN_SAV = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).sav"
JP_ROM = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Japan).gba"
MAIN_MANIFEST = ADVANCE_ROOT / "integrated/main_tip/ggen_advance_main_tip_manifest.json"
CHARMAP = ADVANCE_ROOT / "legacy/analysis/ggen_advance_korean_apply_charmap_20260843.json"
OUT_DIR = ADVANCE_ROOT / "outputs/20260831_ggen_advance_battle_forecast"
OUT_ROM = OUT_DIR / "ggen_advance_battle_forecast_evade_galmuri11condensed_candidate_20260831.gba"
OUT_SAV = OUT_ROM.with_suffix(".sav")
OUT_PREVIEW = OUT_DIR / "ggen_advance_battle_forecast_evade_galmuri11condensed_preview_20260831.png"
OUT_MANIFEST = ADVANCE_ROOT / "legacy/analysis/ggen_advance_battle_forecast_evade_galmuri11condensed_20260831.json"

EXPECTED_MAIN_SHA256 = "e9319c1a5d2b6b6c4d42788ed27f0b76b053cd9cc550c153f90b39a883bc862c"
EXPECTED_JP_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"
FONT_MEMBER = "Galmuri11-Condensed.bdf"

KO_SLOTS = {"완": 0x0689, "전": 0x07AD, "회": 0x0755, "피": 0x074D}
KO_TOKENS = {"완": 0xE5A9, "전": 0xE6CD, "회": 0xE675, "피": 0xE66D}
JP_SLOTS = {"完": 0x04BF, "全": 0x01A4, "回": 0x01A3, "避": 0x04F0}
LABELS = (
    ("JP FULL EVADE", "完全回避", "KO FULL EVADE", "완전회피"),
    ("JP EVADE", "回避", "KO EVADE", "회피"),
)
BTLCMD_LABELS = {
    0x00FC9ECC: bytes.fromhex("E5 A9 E6 CD E6 75 E6 6D 00"),
    0x00FC9ED5: bytes.fromhex("E5 A9 E6 CD E6 75 E6 6D 00"),
    0x00FC9EDE: bytes.fromhex("E6 75 E6 6D 00"),
}


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def decode_8x16(raw: bytes) -> list[list[bool]]:
    gate(len(raw) == fontops.FONT_8X16_STRIDE, "8x16 payload length drift")
    return [[bool((raw[y * 2 + x // 4] >> (2 * (x & 3))) & 3) for x in range(8)] for y in range(16)]


def slot_payload(data: bytes | bytearray, slot: int) -> bytes:
    start = fontops.FONT_8X16_BASE + slot * fontops.FONT_8X16_STRIDE
    return bytes(data[start : start + fontops.FONT_8X16_STRIDE])


def label_mask(data: bytes | bytearray, text: str, slots: dict[str, int]) -> list[list[bool]]:
    out = [[False] * (len(text) * 8) for _ in range(16)]
    for index, char in enumerate(text):
        glyph = decode_8x16(slot_payload(data, slots[char]))
        for y in range(16):
            for x in range(8):
                out[y][index * 8 + x] = glyph[y][x]
    return out


def render_badge(mask: list[list[bool]], scale: int = 6) -> Image.Image:
    glyph_width = len(mask[0])
    width = glyph_width + 8
    height = 20
    image = Image.new("RGB", (width, height), (255, 180, 42))
    px = image.load()
    # Native-color preview: pale-yellow face and brown shadow/contour.
    face = (253, 255, 143)
    shadow = (123, 99, 35)
    points = {(4 + x, 2 + y) for y in range(16) for x in range(glyph_width) if mask[y][x]}
    contour = set()
    for x, y in points:
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1)):
            q = (x + dx, y + dy)
            if q not in points and 0 <= q[0] < width and 0 <= q[1] < height:
                contour.add(q)
    for x, y in contour:
        px[x, y] = shadow
    for x, y in points:
        px[x, y] = face
    return image.resize((width * scale, height * scale), Image.Resampling.NEAREST)


def build_preview(jp: bytes, patched: bytes, path: Path) -> None:
    rendered = []
    for left_caption, jp_text, right_caption, ko_text in LABELS:
        left = render_badge(label_mask(jp, jp_text, JP_SLOTS))
        right = render_badge(label_mask(patched, ko_text, KO_SLOTS))
        rendered.append((left_caption, left, right_caption, right))
    width = max(24 + left.width + 80 + right.width + 24 for _, left, _, right in rendered)
    height = 44 + sum(max(left.height, right.height) + 42 for _, left, _, right in rendered)
    canvas = Image.new("RGB", (width, height), (25, 29, 35))
    draw = ImageDraw.Draw(canvas)
    draw.text((12, 10), "JP SOURCE  ->  KO / GALMURI11-CONDENSED.BDF", fill=(245, 245, 245))
    y = 42
    for left_caption, left, right_caption, right in rendered:
        draw.text((12, y), left_caption, fill=(220, 220, 220))
        left_y = y + 18
        canvas.paste(left, (12, left_y))
        arrow_x = 28 + left.width
        draw.text((arrow_x, left_y + left.height // 2 - 5), "---->", fill=(255, 230, 100))
        right_x = arrow_x + 54
        draw.text((right_x, y), right_caption, fill=(220, 220, 220))
        canvas.paste(right, (right_x, left_y))
        y += max(left.height, right.height) + 42
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--main", type=Path, default=MAIN_ROM)
    ap.add_argument("--main-sav", type=Path, default=MAIN_SAV)
    ap.add_argument("--jp", type=Path, default=JP_ROM)
    ap.add_argument("--out", type=Path, default=OUT_ROM)
    ap.add_argument("--out-sav", type=Path, default=OUT_SAV)
    ap.add_argument("--preview", type=Path, default=OUT_PREVIEW)
    ap.add_argument("--manifest", type=Path, default=OUT_MANIFEST)
    args = ap.parse_args()

    main = args.main.read_bytes()
    jp = args.jp.read_bytes()
    gate(len(main) == 32 * 1024 * 1024 and sha256(main) == EXPECTED_MAIN_SHA256, f"main TIP identity drift: {sha256(main)}")
    gate(len(jp) == 16 * 1024 * 1024 and sha256(jp) == EXPECTED_JP_SHA256, "Japanese reference identity drift")
    manifest = json.loads(MAIN_MANIFEST.read_text(encoding="utf-8"))
    gate(manifest.get("sha256") == EXPECTED_MAIN_SHA256, "main manifest hash drift")
    for off, expected in BTLCMD_LABELS.items():
        gate(main[off : off + len(expected)] == expected, f"promoted Korean BtlCmd label drift: 0x{off:08X}")

    assignment_rows = {row["char"]: row for row in json.loads(CHARMAP.read_text(encoding="utf-8"))["assignments"]}
    for char, slot in KO_SLOTS.items():
        row = assignment_rows.get(char)
        gate(row is not None and int(row["slot"], 16) == slot and int(row["token"], 16) == KO_TOKENS[char], f"assignment drift: {char}")

    with ZipFile(FONT_ZIP) as archive:
        font = fontpair.load_bdf(archive, FONT_MEMBER)

    patched = bytearray(main)
    allowed = set()
    reports = []
    preserved_12x12 = {}
    for char, slot in KO_SLOTS.items():
        glyph = fontpair.render_condensed_8x16_basic(char, font)
        gate(glyph.size == (8, 16), f"condensed cell drift: {char}")
        expected = fontops.pack_8x16(glyph)
        before = slot_payload(main, slot)
        gate(before != expected, f"slot is already canonical Galmuri11-Condensed: {char}")
        start = fontops.FONT_8X16_BASE + slot * fontops.FONT_8X16_STRIDE
        patched[start : start + fontops.FONT_8X16_STRIDE] = expected
        allowed.update(range(start, start + fontops.FONT_8X16_STRIDE))
        start12 = fontops.FONT_12X12_BASE + slot * fontops.FONT_12X12_STRIDE
        preserved_12x12[char] = bytes(main[start12 : start12 + fontops.FONT_12X12_STRIDE])
        glyph_info = font.glyphs[ord(char)]
        reports.append({
            "char": char,
            "slot": f"0x{slot:04X}",
            "token": f"0x{KO_TOKENS[char]:04X}",
            "font_8x16_file_offset": f"0x{start:08X}",
            "bdf_bbx": [glyph_info.width, glyph_info.height, glyph_info.x_offset, glyph_info.y_offset],
            "before_sha256": sha256(before),
            "after_sha256": sha256(expected),
            "exact_bdf_pack_verified": True,
        })

    changed = [i for i, (a, b) in enumerate(zip(main, patched)) if a != b]
    gate(changed and all(i in allowed for i in changed), "changes escaped the four 8x16 Hangul slots")
    for char, slot in KO_SLOTS.items():
        start12 = fontops.FONT_12X12_BASE + slot * fontops.FONT_12X12_STRIDE
        gate(bytes(patched[start12 : start12 + fontops.FONT_12X12_STRIDE]) == preserved_12x12[char], f"12x12 slot changed: {char}")
    for off, expected in BTLCMD_LABELS.items():
        gate(bytes(patched[off : off + len(expected)]) == expected, f"BtlCmd label changed: 0x{off:08X}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(patched)
    shutil.copy2(args.main_sav, args.out_sav)
    gate(args.out_sav.read_bytes() == args.main_sav.read_bytes(), "candidate SAV is not byte-exact")
    build_preview(jp, bytes(patched), args.preview)

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_battle_forecast_evade_galmuri11condensed",
        "result": "PASS",
        "source": {"path": args.main.name, "size": len(main), "sha256": sha256(main)},
        "font": {"archive": str(FONT_ZIP.relative_to(ADVANCE_ROOT)), "member": FONT_MEMBER, "render": "native BDF pixels centered in 8x16; no scaling"},
        "glyphs": reports,
        "scope": {
            "labels": ["完全回避 -> 완전회피", "回避 -> 회피"],
            "shared_8x16_hangul_slots_corrected": list(KO_SLOTS),
            "note": "These four Korean characters now use the canonical condensed face in every 8x16 consumer; 12x12 consumers are unchanged.",
        },
        "output": {"path": str(args.out.relative_to(ADVANCE_ROOT)), "size": len(patched), "sha256": sha256(patched)},
        "save": {"path": str(args.out_sav.relative_to(ADVANCE_ROOT)), "size": args.out_sav.stat().st_size, "sha256": sha256(args.out_sav.read_bytes()), "copied_byte_exact": True},
        "preview": str(args.preview.relative_to(ADVANCE_ROOT)),
        "verification": {
            "result": "PASS",
            "main_tip_and_manifest_hash_gated": True,
            "japanese_reference_hash_gated": True,
            "four_slots_rebuilt_from_galmuri11_condensed_bdf": True,
            "packed_8x16_payloads_match_bdf_exactly": True,
            "changes_restricted_to_four_8x16_slot_payloads": True,
            "font_12x12_slots_preserved": True,
            "btlcmd_korean_labels_preserved": True,
            "japanese_shadow_not_copied": True,
            "preview_labels_are_ascii_and_visible": True,
            "copied_sav_byte_exact": True,
            "canonical_main_tip_modified": False,
        },
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "output": report["output"], "changed_bytes": len(changed), "preview": str(args.preview), "manifest": str(args.manifest)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
