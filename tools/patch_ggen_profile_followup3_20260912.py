"""Re-encode leftover 8x16 profile bodies as 12x12, fix Seed names, restore MA markers.

ss1: キラ・ヤマト(Seed) primary name was pending; 8x16 『SEED｣』 rendered as 갱
     under the 12x12 profile renderer.
ss2/ss3: 8x16 Korean lines longer than 18 12x12 cells clip mid-glyph instead of
     wrapping. Same leftover set as selector-0 bodies classified 'ko'.
ss4: translation_ko kept <07FD>/<07FE> as ASCII, which draws as (07FD).
"""
from __future__ import annotations

import json
import re
import struct
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import build_ggen_advance_unified_rom_poc as unified  # noqa: E402
import patch_ggen_profile_followup2_20260912 as f2  # noqa: E402
from analyze_ggen_advance_ui_matrix_expansion import FIXED16_MATRIX, FIXED40_MATRIX  # noqa: E402
from ggen_advance_project_paths import (  # noqa: E402
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
    ROM_BASE,
    expand_to_slots,
    load_dictionary,
    read_tokens,
)
from merge_ggen_advance_translation_overlays import digest  # noqa: E402
from patch_ggen_advance_apsaras_zentetsu_20260908 import hangul_chars  # noqa: E402
from patch_ggen_advance_intermission_text_consumers_20260904 import gate, sha256  # noqa: E402
from patch_ggen_advance_kimi_jane_to_neo_20260904 import (  # noqa: E402
    update_payload_hash,
    update_translation_manifest,
)

BATCH_ID = "profile-followup3-20260912"
IDENTITY_KEY = "profile_followup3_20260912_sha256"
BATCH_KEY = "profile_followup3_20260912"
OUT = ROOT / "outputs" / "20260912_allclear_profile_followup3"
WORK = OUT / "ggen_profile_followup3_20260912.gba"
SNAPSHOT = ROOT / "analysis" / "ggen_advance_translation_merged_20260912_profile_followup3.json"
LEFTOVER = OUT / "leftover_matrix.json"
CAVE_START = 0x01124240
CAVE_END = 0x01230000
ALLCLEAR = ROOT / "SD Gundam GGeneration Advance (Korean)_allclear.gba"
WIDTH = 18
SEED_SUFFIX = bytes.fromhex("e0540d1111e018e055")
BRACKET_L = bytes.fromhex("e054")
BRACKET_R = bytes.fromhex("e055")
RESERVED_TAG = re.compile(r"<(07F[8BCDE])>", re.IGNORECASE)
NAME_JOBS = [
    {"owner": 0x001ABFBC, "ko": "아스란 자라", "suffix": SEED_SUFFIX, "record_id": "GGA-TEXT-00185637", "sheet": "아스란 자라(Seed)"},
    {"owner": 0x001AC19C, "ko": "키라 야마토", "suffix": SEED_SUFFIX, "record_id": "GGA-TEXT-00185852", "sheet": "키라 야마토(Seed)"},
    {"owner": 0x001AC45C, "ko": "도몬 캇슈", "inner": "명경지술", "record_id": "GGA-TEXT-00185B74", "sheet": "도몬 캇슈<명경지술>"},
    {"owner": 0x001AC5BC, "ko": "포우 에이지", "inner": "울음", "record_id": "GGA-TEXT-00185D26", "sheet": "포우 에이지<울음>"},
    {"owner": 0x001AC6BC, "ko": "유 카지마1", "suffix": b"", "record_id": "GGA-TEXT-00185E4A", "sheet": "유 카지마1"},
]


def clean_ko(text: str) -> str:
    text = (
        text.replace("｣", "」")
        .replace("『", "「")
        .replace("갱", "」")
        .replace("·", "・")
        .replace(".", "。")
        .replace(",", "、")
        .replace("!", "！")
        .replace("?", "？")
    )
    if text.endswith("・"):
        text = text[:-1] + "。"
    return text.strip()


def fold_ko(text: str) -> str:
    return f2.fold_width(text).replace("。", ".").replace("、", ",").replace("・", ".")


def greedy_wrap(text: str, width: int) -> list[str]:
    breaks = set(" \u3000、。・，,")
    lines: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        if n - i <= width:
            tail = text[i:].rstrip()
            if tail:
                lines.append(tail)
            break
        chunk = text[i : i + width]
        br = max((j for j, char in enumerate(chunk) if char in breaks), default=-1)
        if br <= 0:
            lines.append(chunk)
            i += width
        elif chunk[br] in "、。・，,":
            lines.append(chunk[: br + 1].rstrip())
            i += br + 1
        else:
            lines.append(chunk[:br].rstrip())
            i += br + 1
        while i < n and text[i] == " ":
            i += 1
    return [line for line in lines if line]


def fit_n_lines(text: str, count: int, width: int = WIDTH) -> list[str]:
    compact = re.sub(r" {2,}", " ", text).strip()
    while " " in compact and len(compact) > count * width:
        compact = compact[::-1].replace(" ", "", 1)[::-1]
    if len(compact) > count * width:
        compact = compact.replace(" ", "")
    gate(len(compact) <= count * width, f"page too long {len(compact)}>{count * width}: {compact[:48]}")
    lines = greedy_wrap(compact, width)
    if len(lines) > count:
        lines = [compact[i : i + width] for i in range(0, len(compact), width)]
    gate(len(lines) <= count, f"still {len(lines)}>{count} for {compact[:48]}")
    while len(lines) < count:
        idx = max(range(len(lines)), key=lambda i: len(lines[i]))
        src = lines[idx]
        if len(src) < 2:
            break
        mid = max(1, len(src) // 2)
        for pos in range(mid, 0, -1):
            if src[pos - 1] in " \u3000、。・":
                mid = pos
                break
        left, right = src[:mid].rstrip(), src[mid:].lstrip()
        if not left or not right:
            left, right = src[: len(src) // 2], src[len(src) // 2 :]
        lines[idx : idx + 1] = [left, right]
    gate(len(lines) == count, f"could not split to {count}: {lines}")
    for line in lines:
        gate(1 <= len(line) <= width, f"width {len(line)} {line}")
    return lines


def join_parts(parts: list[str]) -> str:
    out = ""
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if out and out[-1] not in "。、・」「" and part[0] not in "。、・」":
            out += part
        else:
            out += part
    return out


def cave_payload(candidate: bytearray, owner: int, encoded: bytes, allowed: set[int], cursor: int) -> tuple[int, int]:
    gate(encoded.endswith(b"\x00"), "encoded payload missing NUL")
    cursor = (cursor + 3) & ~3
    gate(cursor + len(encoded) <= CAVE_END, "followup3 cave overflow")
    candidate[cursor : cursor + len(encoded)] = encoded
    allowed.update(range(cursor, cursor + len(encoded)))
    new_ptr = ROM_BASE + cursor
    struct.pack_into("<I", candidate, owner, new_ptr)
    allowed.update(range(owner, owner + 4))
    return new_ptr, cursor + len(encoded)


def encode_reserved(text: str, recovered: dict[str, int], verified: dict[str, int]) -> bytes:
    out = bytearray()
    pos = 0
    for match in RESERVED_TAG.finditer(text):
        body = text[pos : match.start()]
        if body:
            encoded, missing = unified.encode_korean_text(body, recovered, verified_charmap=verified, strict_punctuation=True)
            gate(encoded and not missing, f"reserved body {body!r} {missing}")
            out.extend(encoded[:-1])
        slot = int(match.group(1), 16)
        token = 0xDF20 + slot
        out.extend(token.to_bytes(2, "big"))
        pos = match.end()
    rest = text[pos:]
    if rest:
        encoded, missing = unified.encode_korean_text(rest, recovered, verified_charmap=verified, strict_punctuation=True)
        gate(encoded and not missing, f"reserved rest {rest!r} {missing}")
        out.extend(encoded[:-1])
    out.append(0)
    return bytes(out)


def jp_nonempty(jp: bytes, dictionary, slot_to_char: dict[int, str], owner: int) -> bool:
    ptr = f2.u32(jp, owner)
    if not (ROM_BASE <= ptr < ROM_BASE + len(jp)):
        return False
    text = f2.decode_text(jp, ptr, dictionary, slot_to_char)
    return bool(text)


def patch_merged_row(row: dict[str, Any], ko: str) -> None:
    row["translation_ko"] = ko
    row["translation_status"] = "translated"
    row["translation_source"] = "user_verified"
    row["review_status"] = "user_verified"
    row["review_count"] = int(row.get("review_count") or 0) + 1
    row["reviewed_at"] = "2026-09-12"
    row["translator_notes"] = "profile followup3: 12x12 body / Seed name / reserved MA marker"
    row["qa_status"] = "static_consumer_verified"
    row["overlay_batch_id"] = BATCH_ID
    row["pointer_recalc_required"] = True
    update_payload_hash(row)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    parent = MAIN_TIP_ROM.read_bytes()
    japan = ORIGINAL_ROM.read_bytes()
    manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(parent) == manifest["sha256"], "main TIP sha mismatch")
    gate(all(b == 0 for b in parent[CAVE_START:CAVE_END]), "followup3 cave is not empty")
    leftover = json.loads(LEFTOVER.read_text(encoding="utf-8"))
    leftover_owners = {int(row["owner"], 16) for row in leftover}
    leftover_t12 = {int(row["owner"], 16): row["t12"] for row in leftover}
    gate(len(leftover_owners) == 1293, f"leftover drift {len(leftover_owners)}")

    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    sheet_by_owner: dict[int, str] = {}
    tag_rows: list[dict[str, Any]] = []
    by_id = {str(row["record_id"]): row for row in merged["records"]}
    for row in merged["records"]:
        family = row.get("ui_family") or ""
        if family in ("fixed16_option_matrix", "fixed40_option_matrix"):
            ko_text = str(row.get("translation_ko") or "")
            for owner_id in row.get("owner_ids") or []:
                if str(owner_id).startswith("OWNER-U32-") and ko_text:
                    sheet_by_owner[int(str(owner_id).split("-")[-1], 16)] = ko_text
        ko_text = str(row.get("translation_ko") or "")
        if RESERVED_TAG.search(ko_text):
            tag_rows.append(row)
    gate(len(tag_rows) == 12, f"reserved tag row drift {len(tag_rows)}")

    import analyze_ggen_advance_pending_decode as decode  # noqa: E402

    jp12 = decode.merge_maps([decode.DEFAULT_MAP12], apply_kana=True)
    jp_dict12 = load_dictionary(japan, DICT_12X12_BASE, DICT_12X12_END)
    live8, live12 = unified.collect_live_slots(japan, merged["records"])
    hangul8_map = f2.hangul_slot_map(parent, mode=8)
    hangul12_map = f2.hangul_slot_map(parent, mode=12)
    map12_now = f2.slot_to_char_map(unified.load_verified_charmap(unified.CHARMAP_12X12_PATH), {}, hangul12_map)
    dict12_now = load_dictionary(parent, DICT_12X12_BASE, DICT_12X12_END)

    pages: list[dict[str, Any]] = []
    for kind, spec in (("char", FIXED16_MATRIX), ("unit", FIXED40_MATRIX)):
        for index in range(spec["count"]):
            base = spec["base_file"] + index * spec["stride"]
            current: list[tuple[int, int]] = []
            for sel in range(spec["selector_count"]):
                owner = base + sel * 4
                if jp_nonempty(japan, jp_dict12, jp12, owner):
                    current.append((sel, owner))
                elif current:
                    if any(owner in leftover_owners for _sel, owner in current):
                        pages.append({"kind": kind, "index": index, "cells": current})
                    current = []
            if current and any(owner in leftover_owners for _sel, owner in current):
                pages.append({"kind": kind, "index": index, "cells": current})

    page_jobs: list[dict[str, Any]] = []
    for page in pages:
        parts = []
        for _sel, owner in page["cells"]:
            if owner in leftover_owners:
                text = sheet_by_owner.get(owner) or leftover_t12[owner]
                parts.append(clean_ko(text))
            else:
                ptr = f2.u32(parent, owner)
                parts.append(clean_ko(f2.decode_text(parent, ptr, dict12_now, map12_now)))
        joined = join_parts(parts)
        lines = fit_n_lines(joined, len(page["cells"]))
        for (sel, owner), line in zip(page["cells"], lines, strict=True):
            page_jobs.append({"kind": page["kind"], "index": page["index"], "selector": sel, "owner": owner, "ko": line, "mode": 12})

    hangul12 = {ch for job in page_jobs for ch in hangul_chars(job["ko"])}
    hangul8 = set()
    for job in NAME_JOBS:
        hangul8.update(hangul_chars(job["ko"]))
        hangul8.update(hangul_chars(job.get("inner") or ""))
    for row in tag_rows:
        hangul8.update(hangul_chars(RESERVED_TAG.sub("", str(row.get("translation_ko") or ""))))

    candidate = bytearray(parent)
    allowed: set[int] = set()
    painted: list[dict[str, str]] = []
    recovered12 = f2.recover_hangul(candidate, japan, hangul12, mode=12, live=live12, occupied=set(), allowed=allowed, painted=painted)
    recovered8 = f2.recover_hangul(candidate, japan, hangul8, mode=8, live=live8, occupied=set(), allowed=allowed, painted=painted)
    verified12 = unified.load_verified_charmap(unified.CHARMAP_12X12_PATH)
    verified8 = unified.load_verified_charmap(unified.CHARMAP_8X16_PATH)
    cursor = CAVE_START
    applied = []

    for job in page_jobs:
        encoded, missing = unified.encode_korean_text(job["ko"], recovered12, verified_charmap=verified12, strict_punctuation=True)
        gate(encoded and not missing, f"encode 12 {job} {missing}")
        new_ptr, cursor = cave_payload(candidate, job["owner"], encoded, allowed, cursor)
        applied.append({**job, "owner": hex(job["owner"]), "old_ptr": hex(f2.u32(parent, job["owner"])), "new_ptr": hex(new_ptr), "cells": len(job["ko"])})

    for job in NAME_JOBS:
        encoded, missing = unified.encode_korean_text(job["ko"], recovered8, verified_charmap=verified8, strict_punctuation=True)
        gate(encoded and not missing, f"encode name {job['ko']} {missing}")
        payload = encoded[:-1]
        if job.get("inner"):
            inner, missing_inner = unified.encode_korean_text(job["inner"], recovered8, verified_charmap=verified8, strict_punctuation=True)
            gate(inner and not missing_inner, f"encode inner {job['inner']} {missing_inner}")
            payload += BRACKET_L + inner[:-1] + BRACKET_R
        else:
            payload += job.get("suffix") or b""
        payload += b"\x00"
        new_ptr, cursor = cave_payload(candidate, job["owner"], payload, allowed, cursor)
        applied.append({"id": "name", "owner": hex(job["owner"]), "ko": job["sheet"], "mode": 8, "old_ptr": hex(f2.u32(parent, job["owner"])), "new_ptr": hex(new_ptr)})

    for row in tag_rows:
        owners = [int(str(oid).split("-")[-1], 16) for oid in row.get("owner_ids") or [] if str(oid).startswith("OWNER-U32-")]
        gate(owners, f"no owners {row['record_id']}")
        encoded = encode_reserved(str(row["translation_ko"]), recovered8, verified8)
        for owner in owners:
            new_ptr, cursor = cave_payload(candidate, owner, encoded, allowed, cursor)
            applied.append({"id": row["record_id"], "owner": hex(owner), "ko": row["translation_ko"], "mode": 8, "old_ptr": hex(f2.u32(parent, owner)), "new_ptr": hex(new_ptr)})

    hangul12_live = f2.hangul_slot_map(candidate, mode=12)
    hangul8_live = f2.hangul_slot_map(candidate, mode=8)
    map12 = f2.slot_to_char_map(verified12, recovered12, hangul12_live)
    map8 = f2.slot_to_char_map(verified8, recovered8, hangul8_live)
    dict12 = load_dictionary(bytes(candidate), DICT_12X12_BASE, DICT_12X12_END)
    dict8 = load_dictionary(bytes(candidate), DICT_8X16_BASE, DICT_8X16_END)

    kira0 = f2.decode_text(candidate, f2.u32(candidate, 0x001AD51C), dict12, map12)
    gate("갱" not in kira0, f"kira still has 갱: {kira0}")
    gate(len(kira0) <= WIDTH, f"kira sel0 width {len(kira0)} {kira0}")
    mirai1 = f2.decode_text(candidate, f2.u32(candidate, 0x001AEEA0), dict12, map12)
    gate(len(mirai1) <= WIDTH, f"mirai sel1 width {len(mirai1)} {mirai1}")
    kira_name = f2.decode_text(candidate, f2.u32(candidate, 0x001AC19C), dict8, map8)
    gate(kira_name.startswith("키라 야마토"), f"kira name {kira_name}")
    gaza_slots = expand_to_slots(read_tokens(bytes(candidate), f2.u32(candidate, 0x001B0210) - ROM_BASE)[0], dict8)
    gate(0x07FD in gaza_slots, f"gaza missing 07FD {gaza_slots}")
    gate(0x0134 not in gaza_slots, f"gaza still has ASCII < {gaza_slots}")

    for job in page_jobs:
        got = f2.decode_text(candidate, f2.u32(candidate, job["owner"]), dict12, map12)
        gate(fold_ko(got) == fold_ko(job["ko"]), f"roundtrip {job['kind']}{job['index']}s{job['selector']}: {got!r} != {job['ko']!r}")

    changed = {i for i, (a, b) in enumerate(zip(parent, candidate)) if a != b}
    gate(changed <= allowed, f"unrelated writes {len(changed - allowed)}")

    changed_ids: list[str] = []
    for job in NAME_JOBS:
        if job["record_id"] and job["record_id"] in by_id:
            patch_merged_row(by_id[job["record_id"]], job["sheet"])
            changed_ids.append(job["record_id"])
    for row in tag_rows:
        body = RESERVED_TAG.sub("", str(row["translation_ko"]))
        tags = [f"0x{m.group(1)}" for m in RESERVED_TAG.finditer(str(row["translation_ko"]))]
        row["source_reserved_slots"] = sorted(set(str(s).lower() for s in (row.get("source_reserved_slots") or []) + tags))
        patch_merged_row(row, str(row["translation_ko"]))
        changed_ids.append(str(row["record_id"]))

    parent_identity = str(merged.get("identity", {}).get("translation_overlay_identity_sha256") or "")
    new_identity = digest({"parent": parent_identity, "batch_id": BATCH_ID, "records": changed_ids})
    identity = merged.setdefault("identity", {})
    identity["parent_translation_overlay_identity_sha256"] = parent_identity
    identity[IDENTITY_KEY] = new_identity
    identity["translation_overlay_identity_sha256"] = new_identity
    status_counts = dict(sorted(Counter(str(row.get("translation_status") or "") for row in merged["records"]).items()))
    summary = merged.setdefault("summary", {})
    summary["merged_translation_status_counts"] = status_counts
    summary["translation_overlay_identity_sha256"] = new_identity
    merged[BATCH_KEY] = {"batch_id": BATCH_ID, "changed_records": changed_ids}
    payload_json = json.dumps(merged, ensure_ascii=False, indent=2) + "\n"
    SNAPSHOT.write_text(payload_json, encoding="utf-8")
    TRANSLATION_MERGED_JSON.write_text(payload_json, encoding="utf-8")
    update_translation_manifest(merged, SNAPSHOT)

    WORK.write_bytes(bytes(candidate))
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_profile_followup3",
        "batch_id": BATCH_ID,
        "parent_sha256": sha256(parent),
        "output": {"path": advance_relative(WORK), "size": len(candidate), "sha256": sha256(bytes(candidate))},
        "painted": painted,
        "cave": {"start": hex(CAVE_START), "end": hex(cursor), "capacity_end": hex(CAVE_END)},
        "changed_bytes": len(changed),
        "page_jobs": len(page_jobs),
        "pages": len(pages),
        "proofs": {
            "kira_sel0": kira0,
            "mirai_sel1": mirai1,
            "kira_name": kira_name,
            "gaza_slots": [hex(s) for s in gaza_slots],
        },
        "verification": {
            "result": "PASS",
            "roundtrip_page_jobs": True,
            "unrelated_bytes_preserved": True,
            "no_갱_on_kira": True,
            "lines_le_18": True,
            "gaza_has_07fd_slot": True,
        },
    }
    (OUT / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("output", "painted", "cave", "changed_bytes", "page_jobs", "pages", "proofs", "verification")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
