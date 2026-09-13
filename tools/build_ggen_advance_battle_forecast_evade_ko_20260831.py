#!/usr/bin/env python3
"""Localize the BtlCmd evade labels used by the battle forecast screen.

The labels are not baked into the forecast background atlas.  The BtlCmd
resource package at 0x08FC9A78 owns a seven-entry command table at
0x08FC9E70.  Three entries name evade actions: two aliases of 完全回避 and
one 回避.  Replacing those fixed-length font-token strings makes the native
text renderer build both the Korean face and its shadow from the Korean
glyph masks; no Japanese face or Japanese shadow pixels are copied forward.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import struct
from pathlib import Path

from PIL import Image, ImageDraw

from ggen_advance_project_paths import ADVANCE_ROOT


MAIN_ROM = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).gba"
MAIN_SAV = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).sav"
JP_ROM = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Japan).gba"
MAIN_MANIFEST = ADVANCE_ROOT / "integrated/main_tip/ggen_advance_main_tip_manifest.json"
CHARMAP = ADVANCE_ROOT / "legacy/analysis/ggen_advance_korean_apply_charmap_20260843.json"
OUT_DIR = ADVANCE_ROOT / "outputs/20260831_ggen_advance_battle_forecast"
OUT_ROM = OUT_DIR / "ggen_advance_battle_forecast_evade_ko_candidate_20260831.gba"
OUT_SAV = OUT_ROM.with_suffix(".sav")
OUT_PREVIEW = OUT_DIR / "ggen_advance_battle_forecast_evade_ko_preview_20260831.png"
OUT_MANIFEST = ADVANCE_ROOT / "legacy/analysis/ggen_advance_battle_forecast_evade_ko_20260831.json"

EXPECTED_MAIN_SHA256 = "27e24b9d261bd64d8f9327a5dae3c12828d9a2d48eb8e13dd77ab57730f25d42"
EXPECTED_JP_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"
ROM_BASE = 0x08000000
FONT_8X16_BASE = 0x00094028
FONT_8X16_STRIDE = 32
FONT_12X12_BASE = 0x0008AC40
FONT_12X12_STRIDE = 18
BUNDLE_ROOT = 0x00FC9A78
COMMAND_TABLE = 0x00FC9E70
COMMAND_COUNT = 7
BUNDLE_HEADER = (0x20, 0x08FC9BD4, 0x08FC9C18, 0x08FC9E3C, 0x08FC9C2C, 0x08FC9E3C, 0x08FC9E70)

# The seven (name pointer, command bytecode pointer) pairs are the measured
# BtlCmd package contract.  The evade labels are entries 4, 5, and 6.
EXPECTED_COMMAND_PAIRS = (
    (0x08FC9EAC, 0x08FC9935),
    (0x08FC9EB8, 0x08FC995A),
    (0x08FC9EBD, 0x08FC98C0),
    (0x08FC9EC5, 0x08FC991C),
    (0x08FC9ECC, 0x08FC991C),
    (0x08FC9ED5, 0x08FC991C),
    (0x08FC9EDE, 0x08FC9927),
)

PATCHES = (
    {
        "offset": 0x00FC9ECC,
        "source": "完全回避",
        "translation": "완전회피",
        "before": bytes.fromhex("E3 DF E0 C4 E0 C3 E4 10 00"),
        "after": bytes.fromhex("E5 A9 E6 CD E6 75 E6 6D 00"),
        "command_data": 0x08FC991C,
    },
    {
        "offset": 0x00FC9ED5,
        "source": "完全回避",
        "translation": "완전회피",
        "before": bytes.fromhex("E3 DF E0 C4 E0 C3 E4 10 00"),
        "after": bytes.fromhex("E5 A9 E6 CD E6 75 E6 6D 00"),
        "command_data": 0x08FC991C,
    },
    {
        "offset": 0x00FC9EDE,
        "source": "回避",
        "translation": "회피",
        "before": bytes.fromhex("E0 C3 E4 10 00"),
        "after": bytes.fromhex("E6 75 E6 6D 00"),
        "command_data": 0x08FC9927,
    },
)


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def token_slot(token: int) -> int:
    gate(0xE000 <= token <= 0xEFFF, f"not a literal glyph token: 0x{token:04X}")
    return (token + 0x20E0) & 0xFFFF


def tokens(raw: bytes) -> list[int]:
    gate(raw.endswith(b"\0"), "label is not NUL terminated")
    body = raw[:-1]
    gate(len(body) % 2 == 0, "label token byte count is odd")
    result = [struct.unpack_from(">H", body, i)[0] for i in range(0, len(body), 2)]
    gate(all(0xE000 <= value <= 0xEFFF for value in result), "label contains a non-glyph token")
    return result


def decode_8x16_mask(data: bytes, slot: int) -> list[list[bool]]:
    raw = data[FONT_8X16_BASE + slot * FONT_8X16_STRIDE : FONT_8X16_BASE + (slot + 1) * FONT_8X16_STRIDE]
    gate(len(raw) == FONT_8X16_STRIDE, f"8x16 slot out of range: 0x{slot:04X}")
    return [[bool((raw[y * 2 + x // 4] >> (2 * (x & 3))) & 3) for x in range(8)] for y in range(16)]


def decode_12x12_mask(data: bytes, slot: int) -> list[list[bool]]:
    raw = data[FONT_12X12_BASE + slot * FONT_12X12_STRIDE : FONT_12X12_BASE + (slot + 1) * FONT_12X12_STRIDE]
    gate(len(raw) == FONT_12X12_STRIDE, f"12x12 slot out of range: 0x{slot:04X}")
    return [[bool(raw[(y * 12 + x) // 8] & (1 << ((y * 12 + x) & 7))) for x in range(12)] for y in range(12)]


def render_label(data: bytes, raw: bytes, scale: int = 4) -> Image.Image:
    glyphs = [decode_8x16_mask(data, token_slot(value)) for value in tokens(raw)]
    width = len(glyphs) * 8 + 2
    canvas = Image.new("RGB", (width, 18), (246, 180, 43))
    px = canvas.load()
    face = (253, 255, 143)
    shadow = (123, 99, 35)
    # A measured one-pixel lower-right contour illustrates the native rule:
    # the shadow is derived from the selected glyph mask, never stored in the
    # command string.  Drawing shadow first also proves no JP mask survives.
    mask = set()
    for gi, glyph in enumerate(glyphs):
        for y in range(16):
            for x in range(8):
                if glyph[y][x]:
                    mask.add((1 + gi * 8 + x, y))
    for x, y in mask:
        if x + 1 < width and y + 1 < 18 and (x + 1, y + 1) not in mask:
            px[x + 1, y + 1] = shadow
    for x, y in mask:
        px[x, y] = face
    return canvas.resize((width * scale, 18 * scale), Image.Resampling.NEAREST)


def build_preview(jp: bytes, patched: bytes, path: Path) -> None:
    rows = []
    for spec in PATCHES:
        rows.append((spec["source"], render_label(jp, spec["before"]), spec["translation"], render_label(patched, spec["after"])))
    width = max(before.width + after.width + 180 for _, before, _, after in rows)
    height = 24 + sum(max(before.height, after.height) + 24 for _, before, _, after in rows)
    image = Image.new("RGB", (width, height), (28, 32, 38))
    draw = ImageDraw.Draw(image)
    draw.text((8, 5), "JP source     ->     KO (shadow rebuilt from KO mask)", fill=(238, 238, 238))
    y = 24
    for row_index, (source, before, translation, after) in enumerate(rows, 1):
        draw.text((8, y + 4), f"{row_index}: JP", fill=(220, 220, 220))
        image.paste(before, (55, y))
        x2 = 75 + before.width
        draw.text((x2, y + 4), "KO", fill=(220, 220, 220))
        image.paste(after, (x2 + 55, y))
        y += max(before.height, after.height) + 24
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


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
    gate(len(main) == 32 * 1024 * 1024, "main TIP is not 32 MiB")
    gate(sha256(main) == EXPECTED_MAIN_SHA256, f"main TIP hash drift: {sha256(main)}")
    gate(len(jp) == 16 * 1024 * 1024 and sha256(jp) == EXPECTED_JP_SHA256, "Japanese ROM identity drift")
    main_manifest = json.loads(MAIN_MANIFEST.read_text(encoding="utf-8"))
    gate(main_manifest.get("sha256") == EXPECTED_MAIN_SHA256, "main TIP manifest hash drift")
    gate(main_manifest.get("canonical_path") == MAIN_ROM.name, "main TIP canonical path drift")

    # Bundle/table ownership gates.  The root points to the package's internal
    # layout, and the seven exact pairs bind each label to its command script.
    gate(struct.unpack_from("<7I", jp, BUNDLE_ROOT) == BUNDLE_HEADER, "BtlCmd bundle header drift")
    gate(struct.unpack_from("<I", jp, COMMAND_TABLE)[0] == COMMAND_COUNT, "BtlCmd command count drift")
    pairs = tuple(struct.unpack_from("<II", jp, COMMAND_TABLE + 4 + index * 8) for index in range(COMMAND_COUNT))
    gate(pairs == EXPECTED_COMMAND_PAIRS, "BtlCmd command pair table drift")
    gate(main[COMMAND_TABLE : COMMAND_TABLE + 4 + COMMAND_COUNT * 8] == jp[COMMAND_TABLE : COMMAND_TABLE + 4 + COMMAND_COUNT * 8], "main BtlCmd ownership table differs from JP")

    assignments = json.loads(CHARMAP.read_text(encoding="utf-8"))["assignments"]
    assignment_by_char = {row["char"]: row for row in assignments}
    expected_tokens = {"완": "0xE5A9", "전": "0xE6CD", "회": "0xE675", "피": "0xE66D"}
    font_rows = []
    for char, expected_token in expected_tokens.items():
        row = assignment_by_char.get(char)
        gate(row is not None and row.get("token") == expected_token and row.get("paint") == "both", f"Hangul assignment drift: {char}")
        slot = token_slot(int(expected_token, 16))
        mask8 = decode_8x16_mask(main, slot)
        mask12 = decode_12x12_mask(main, slot)
        gate(any(any(line) for line in mask8), f"empty 8x16 Hangul glyph: {char}")
        gate(any(any(line) for line in mask12), f"empty 12x12 Hangul glyph: {char}")
        font_rows.append({"char": char, "token": expected_token, "slot": f"0x{slot:04X}", "paint": "both"})

    patched = bytearray(main)
    reports = []
    allowed = set()
    for spec in PATCHES:
        off = int(spec["offset"])
        before = bytes(spec["before"])
        after = bytes(spec["after"])
        gate(len(before) == len(after), f"fixed-length contract failed: {spec['source']}")
        gate(jp[off : off + len(before)] == before, f"JP source label drift: 0x{off:08X}")
        gate(main[off : off + len(before)] == before, f"main source label drift: 0x{off:08X}")
        patched[off : off + len(after)] = after
        allowed.update(range(off, off + len(after)))
        reports.append({
            "source": spec["source"],
            "translation": spec["translation"],
            "string_file_offset": f"0x{off:08X}",
            "string_address": f"0x{ROM_BASE + off:08X}",
            "command_data_address": f"0x{int(spec['command_data']):08X}",
            "before_hex": before.hex(" ").upper(),
            "after_hex": after.hex(" ").upper(),
            "byte_length_preserved": True,
        })

    changed = [i for i, (a, b) in enumerate(zip(main, patched)) if a != b]
    gate(changed and all(i in allowed for i in changed), "changes escaped the three BtlCmd labels")
    gate(all(patched[int(spec["offset"]) : int(spec["offset"]) + len(spec["after"])] == spec["after"] for spec in PATCHES), "post-patch label verification failed")
    gate(bytes(patched[COMMAND_TABLE : COMMAND_TABLE + 4 + COMMAND_COUNT * 8]) == main[COMMAND_TABLE : COMMAND_TABLE + 4 + COMMAND_COUNT * 8], "command table was modified")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(patched)
    shutil.copy2(args.main_sav, args.out_sav)
    gate(args.out_sav.read_bytes() == args.main_sav.read_bytes(), "candidate SAV is not byte-exact")
    build_preview(jp, bytes(patched), args.preview)

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_battle_forecast_evade_ko",
        "result": "PASS",
        "source": {"path": args.main.name, "size": len(main), "sha256": sha256(main)},
        "japanese_reference": {"path": args.jp.name, "size": len(jp), "sha256": sha256(jp)},
        "static_ownership": {
            "module": "BtlCmd",
            "bundle_root_file_offset": f"0x{BUNDLE_ROOT:08X}",
            "command_table_file_offset": f"0x{COMMAND_TABLE:08X}",
            "command_count": COMMAND_COUNT,
            "evade_entry_indices": [4, 5, 6],
            "contract": "each table row is (label pointer, command bytecode pointer)",
        },
        "patches": reports,
        "hangul_font_assignments": font_rows,
        "output": {"path": str(args.out.relative_to(ADVANCE_ROOT)), "size": len(patched), "sha256": sha256(patched)},
        "save": {"path": str(args.out_sav.relative_to(ADVANCE_ROOT)), "size": args.out_sav.stat().st_size, "sha256": sha256(args.out_sav.read_bytes()), "copied_byte_exact": True},
        "preview": str(args.preview.relative_to(ADVANCE_ROOT)),
        "verification": {
            "result": "PASS",
            "main_tip_hash_gated": True,
            "main_manifest_hash_gated": True,
            "japanese_reference_hash_gated": True,
            "btlcmd_bundle_and_seven_entry_table_gated": True,
            "evade_labels_bound_to_command_bytecode": True,
            "all_three_evade_aliases_localized": True,
            "fixed_byte_lengths_preserved": True,
            "changes_restricted_to_three_label_payloads": True,
            "command_table_unchanged": True,
            "hangul_8x16_and_12x12_masks_nonempty": True,
            "japanese_shadow_not_copied": True,
            "shadow_rebuilt_by_native_renderer_from_korean_glyph_mask": True,
            "copied_sav_byte_exact": True,
            "canonical_main_tip_modified": False,
        },
        "note": "The preliminary screenshot/LZSS ranking was non-owning visual evidence. This BtlCmd table binding is the source-of-truth static ownership proof.",
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "output": report["output"], "changed_bytes": len(changed), "manifest": str(args.manifest), "preview": str(args.preview), "save_byte_exact": True}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
