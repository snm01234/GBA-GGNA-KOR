"""Patch character/unit profile first-lines and scroll bodies as 12x12 Korean.

Selector 0 was aliased to 8x16 production text, so the 12x12 profile renderer
showed leftover Japanese. Extra selectors (character 6+, unit 5+) were never
promoted, so scrolling kept the original Japanese (with Hangul-painted slot
leak). This retargets only matrix owners and leaves other consumers intact.
"""
from __future__ import annotations

import json
import shutil
import struct
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import build_ggen_advance_ko_poc as fontops  # noqa: E402
import build_ggen_advance_unified_rom_poc as unified  # noqa: E402
import ggen_advance_painted_glyph_identity as glyph  # noqa: E402
from analyze_ggen_advance_ui_matrix_expansion import FIXED16_MATRIX, FIXED40_MATRIX
from ggen_advance_painted_glyph_identity import FONT12_RELOCATED, load_galmuri12, packed_12x12, slot_raw
from ggen_advance_project_paths import MAIN_TIP_MANIFEST, MAIN_TIP_ROM, ORIGINAL_ROM, TRANSLATION_MERGED_JSON, advance_relative
from ggen_advance_text_codec import DICT_12X12_BASE, DICT_12X12_END, ROM_BASE, expand_to_slots, load_dictionary, read_tokens
from patch_ggen_advance_apsaras_zentetsu_20260908 import choose_free_12x12, hangul_chars, paint_12x12, recover_or_paint
from patch_ggen_advance_intermission_text_consumers_20260904 import gate, sha256

OUT = ROOT / "outputs" / "20260912_allclear_profile_desc"
BATCH_DIR = OUT / "work_batches"
NEED = OUT / "profile_pages_need_ko.json"
WORK = ROOT / "outputs" / "20260912_allclear_profile_desc" / "ggen_profile_desc_ko_20260912.gba"
ALLCLEAR = ROOT / "SD Gundam GGeneration Advance (Korean)_allclear.gba"
CAVE_START = 0x01118000
CAVE_END = 0x01230000
MATRIX_OWNERS = set()
for spec in (FIXED16_MATRIX, FIXED40_MATRIX):
    for i in range(spec["count"]):
        base = spec["base_file"] + i * spec["stride"]
        for sel in range(spec["selector_count"]):
            MATRIX_OWNERS.add(base + sel * 4)


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def normalize(text: str) -> str:
    return (
        text.replace("·", "・")
        .replace("-", "・")
        .replace("′", "")
        .replace("\u2019", "")
        .replace("\u2018", "")
    )


def fold_width(text: str) -> str:
    out = []
    for char in text:
        code = ord(char)
        if 0xFF01 <= code <= 0xFF5E:
            char = chr(code - 0xFEE0)
        out.append(char)
    return "".join(out).replace("』", "」").replace("『", "「")


def decode_ko(rom: bytes, ptr: int, dictionary, slot_to_char: dict[int, str]) -> str:
    if not (ROM_BASE <= ptr < ROM_BASE + len(rom)):
        return ""
    tokens, _raw = read_tokens(rom, ptr - ROM_BASE)
    slots = expand_to_slots(tokens, dictionary)
    return "".join(slot_to_char.get(s, f"<{s:04X}>") for s in slots)


def hangul_slot_map(rom: bytes, font) -> dict[int, str]:
    by_glyph: dict[bytes, list[int]] = {}
    for slot in range(fontops.FONT_12X12_COUNT):
        by_glyph.setdefault(slot_raw(rom, FONT12_RELOCATED, slot, fontops.FONT_12X12_STRIDE), []).append(slot)
    out: dict[int, str] = {}
    for code in range(ord("가"), ord("힣") + 1):
        ch = chr(code)
        try:
            packed = packed_12x12(ch, font)
        except Exception:
            continue
        hits = by_glyph.get(packed, [])
        if len(hits) == 1:
            out[hits[0]] = ch
    return out


def load_jobs() -> list[dict[str, Any]]:
    need = { (p["kind"], p["index"], p["page"]): p for p in json.loads(NEED.read_text(encoding="utf-8"))["pages"] }
    jobs = []
    for i in range(4):
        ko_rows = json.loads((BATCH_DIR / f"batch{i}_ko.json").read_text(encoding="utf-8"))
        for row in ko_rows:
            src = need[(row["kind"], row["index"], row["page"])]
            if src["lines"] and row.get("fix_only"):
                texts = row["ko_fix"]
                gate(len(texts) == len(src["lines"]) or len(texts) == len([ln for ln in src["lines"] if ln["status"] != "ko"]), "fix_only length drift")
                bad = [ln for ln in src["lines"] if ln["status"] != "ko"]
                gate(len(texts) == len(bad), f"ko_fix != bad lines {src['kind']}{src['index']}p{src['page']}")
                pairs = list(zip(bad, texts))
            else:
                texts = row.get("ko_lines") or row.get("ko_fix")
                gate(len(texts) == len(src["lines"]), f"ko_lines != page lines {src['kind']}{src['index']}p{src['page']}")
                pairs = list(zip(src["lines"], texts))
            for line, text in pairs:
                text = normalize(text)
                gate(1 <= len(text) <= 18, f"width {len(text)} {text}")
                owner = int(line["owner"], 16)
                gate(owner in MATRIX_OWNERS, f"owner outside matrix {hex(owner)}")
                jobs.append({"kind": src["kind"], "index": src["index"], "page": src["page"], "selector": line["selector"], "owner": owner, "jp": line["jp"], "ko": text, "role": line["role"]})
    return jobs


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(exist_ok=True)
    parent = MAIN_TIP_ROM.read_bytes()
    japan = ORIGINAL_ROM.read_bytes()
    manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(parent) == manifest["sha256"], "main TIP sha mismatch")
    jobs = load_jobs()
    gate(len(jobs) == 1689 or len(jobs) >= 1600, f"unexpected job count {len(jobs)}")
    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    font12 = load_galmuri12()
    hangul = {ch for job in jobs for ch in hangul_chars(job["ko"])}
    live8, live12 = unified.collect_live_slots(japan, merged["records"])
    candidate = bytearray(parent)
    allowed: set[int] = set()
    occupied: set[int] = set()
    painted: list[dict[str, str]] = []
    recovered: dict[str, int] = {}
    for char in sorted(hangul):
        recovered[char] = recover_or_paint(
            candidate,
            japan,
            font12,
            char,
            choose_free=choose_free_12x12,
            paint=paint_12x12,
            packed=packed_12x12,
            live=live12,
            occupied=occupied,
            allowed=allowed,
            painted=painted,
            label="12x12",
            relocated=FONT12_RELOCATED,
            stride=fontops.FONT_12X12_STRIDE,
            count=fontops.FONT_12X12_COUNT,
        )
    verified12 = unified.load_verified_charmap(unified.CHARMAP_12X12_PATH)
    cursor = CAVE_START
    gate(all(b == 0 for b in parent[CAVE_START:CAVE_END]), "profile text cave is not empty")
    applied = []
    missing_total: Counter[str] = Counter()
    for job in jobs:
        encoded, missing = unified.encode_korean_text(job["ko"], recovered, verified_charmap=verified12, strict_punctuation=True)
        if missing:
            missing_total.update(missing)
            raise SystemExit(f"missing glyphs {missing} in {job}")
        assert encoded and encoded.endswith(b"\x00")
        cursor = (cursor + 3) & ~3
        gate(cursor + len(encoded) <= CAVE_END, "profile text cave overflow")
        candidate[cursor : cursor + len(encoded)] = encoded
        allowed.update(range(cursor, cursor + len(encoded)))
        owner = job["owner"]
        old = u32(parent, owner)
        struct.pack_into("<I", candidate, owner, ROM_BASE + cursor)
        allowed.update(range(owner, owner + 4))
        job = dict(job, old_ptr=hex(old), new_ptr=hex(ROM_BASE + cursor), encoded_hex=encoded.hex())
        applied.append(job)
        cursor += len(encoded)

    changed = {i for i, (a, b) in enumerate(zip(parent, candidate)) if a != b}
    gate(changed <= allowed, f"unrelated writes {len(changed - allowed)}")
    # Decode roundtrip for Aisha/Argama using painted Hangul.
    inv = {1: " "}
    for char, slot in verified12.items():
        inv.setdefault(slot, char)
    for char, token in unified.SPECIAL_CHAR_TOKENS.items():
        if token >= 0xE000:
            inv.setdefault((token - 0xDF20) & 0xFFFF, char)
        else:
            inv.setdefault(token, char)
    for char, slot in recovered.items():
        inv[slot] = char
    slot_to_char = inv
    ko_dict = load_dictionary(bytes(candidate), DICT_12X12_BASE, DICT_12X12_END)
    proofs = []
    for job in applied:
        got = decode_ko(bytes(candidate), u32(candidate, job["owner"]), ko_dict, slot_to_char)
        gate(fold_width(got) == fold_width(job["ko"]), f"roundtrip {job['kind']}{job['index']}s{job['selector']}: {got!r} != {job['ko']!r}")
        if job["kind"] == "char" and job["index"] == 0:
            proofs.append({"id": "aisha", **{k: job[k] for k in ("selector", "ko", "new_ptr")}})
        if job["kind"] == "unit" and job["index"] == 165:
            proofs.append({"id": "argama", **{k: job[k] for k in ("selector", "ko", "new_ptr")}})

    WORK.write_bytes(candidate)
    backup = OUT / "parent_main_tip.gba"
    if not backup.exists():
        shutil.copy2(MAIN_TIP_ROM, backup)
    shutil.copy2(WORK, MAIN_TIP_ROM)
    shutil.copy2(WORK, ALLCLEAR)
    report = {
        "parent_sha256": sha256(parent),
        "output_sha256": sha256(bytes(candidate)),
        "jobs": len(applied),
        "painted_12x12": painted,
        "cave": {"start": hex(CAVE_START), "end": hex(cursor), "capacity_end": hex(CAVE_END)},
        "changed_bytes": len(changed),
        "proofs": proofs,
        "paths": {
            "candidate": advance_relative(WORK),
            "main_tip": advance_relative(MAIN_TIP_ROM),
            "allclear": advance_relative(ALLCLEAR),
        },
        "verification": {
            "result": "PASS",
            "matrix_owners_only": True,
            "roundtrip_all_jobs": True,
            "unrelated_bytes_preserved": True,
        },
    }
    (OUT / "profile_desc_patch_manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "profile_desc_applied.json").write_text(json.dumps(applied, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("output_sha256", "jobs", "painted_12x12", "cave", "changed_bytes", "proofs", "paths", "verification")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
