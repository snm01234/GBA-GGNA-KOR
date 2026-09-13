"""Restore II-suffixed unit names wrongly rewritten as 비르고 II.

followup4 matched current.endswith(' II'), so 짐 캐논 II / 짐 II /
아프사라스 II / 블루 데스티니 II became 비르고 II. Keep real ビルゴⅡ.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import patch_ggen_profile_followup2_20260912 as f2  # noqa: E402
import patch_ggen_profile_followup3_20260912 as f3  # noqa: E402
import patch_ggen_profile_followup4_20260912 as f4  # noqa: E402
import build_ggen_advance_unified_rom_poc as unified  # noqa: E402
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
    ROM_BASE,
    expand_to_slots,
    load_dictionary,
    read_tokens,
)
from merge_ggen_advance_translation_overlays import digest  # noqa: E402
from patch_ggen_advance_apsaras_zentetsu_20260908 import hangul_chars  # noqa: E402
from patch_ggen_advance_intermission_text_consumers_20260904 import gate, sha256  # noqa: E402
from patch_ggen_advance_kimi_jane_to_neo_20260904 import (  # noqa: E402
    owner_offsets,
    update_payload_hash,
    update_translation_manifest,
)

BATCH_ID = "profile-followup6-virgo-ii-restore-20260912"
IDENTITY_KEY = "profile_followup6_virgo_ii_restore_20260912_sha256"
BATCH_KEY = "profile_followup6_virgo_ii_restore_20260912"
OUT = ROOT / "outputs" / "20260912_allclear_profile_followup6"
WORK = OUT / "ggen_profile_followup6_virgo_ii_restore_20260912.gba"
SNAPSHOT = ROOT / "analysis" / "ggen_advance_translation_merged_20260912_profile_followup6.json"
CAVE_START = 0x011350EC
CAVE_END = 0x01230000
UNIT_BASE = 0x001AFB5C
UNIT_STRIDE = 0x28
BODY_MAP = (
    ("ジムキャノンⅡ", "짐 캐논 II"),
    ("アプサラスⅡ", "아프사라스 II"),
    ("ジムⅡ", "짐 II"),
    ("BDⅡ", "블루 데스티니 II"),
)


def restore_ko(source: str, current: str) -> str | None:
    if "비르고" not in current or "ビルゴ" in source:
        return None
    icons = [match.group(0).upper().replace("0X", "") for match in f4.LEAD_ICON.finditer(source)]
    icons = [tag if tag.startswith("<") else f"<{tag}>" for tag in icons]
    rest = f4.LEAD_ICON.sub("", source)
    has_h = "<07FE>" in rest.upper()
    rest = re.sub(r"<07FE>", "", rest, flags=re.I)
    body = None
    for jp_name, ko_name in BODY_MAP:
        if rest == jp_name or rest.startswith(jp_name):
            body = ko_name
            break
    if body is None:
        return None
    if has_h:
        body += "<07FE>"
    return "".join(icons) + body


def patch_merged_row(row: dict[str, Any], ko: str) -> None:
    row["translation_ko"] = ko
    row["translation_status"] = "translated"
    row["translation_source"] = "user_verified"
    row["review_status"] = "user_verified"
    row["review_count"] = int(row.get("review_count") or 0) + 1
    row["reviewed_at"] = "2026-09-12"
    row["translator_notes"] = "profile followup6: restore non-Virgo II names; keep 빌고 II as 비르고 II"
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
    gate(all(b == 0 for b in parent[CAVE_START:CAVE_END]), "followup6 cave is not empty")

    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    jobs: list[dict[str, Any]] = []
    for row in merged["records"]:
        wanted = restore_ko(str(row.get("source_text") or ""), str(row.get("translation_ko") or ""))
        if not wanted:
            continue
        owners = list(owner_offsets(row))
        gate(owners, f"no owners {row['record_id']}")
        jobs.append({"record_id": str(row["record_id"]), "owners": owners, "ko": wanted, "source": row.get("source_text")})
    gate(len(jobs) == 24, f"unexpected restore count {len(jobs)} {[j['record_id'] for j in jobs]}")

    live8, live12 = unified.collect_live_slots(japan, merged["records"])
    verified8 = unified.load_verified_charmap(unified.CHARMAP_8X16_PATH)
    candidate = bytearray(parent)
    allowed: set[int] = set()
    painted: list[dict[str, str]] = []
    occupied: set[int] = set()
    hangul8 = {char for job in jobs for char in hangul_chars(job["ko"])}
    recovered8 = f2.recover_hangul(
        candidate, japan, hangul8, mode=8, live=live8, occupied=occupied, allowed=allowed, painted=painted
    )
    latin_i = f4.ensure_jp_glyph(candidate, japan, 0x00EA, live8, occupied, allowed, painted, "I")
    specials8 = {"I": latin_i, "<": f4.BRACKET_L, ">": f4.BRACKET_R}
    cursor = CAVE_START
    seen: set[int] = set()
    for job in jobs:
        encoded = f4.encode_mixed(job["ko"], recovered8, verified8, specials8)
        for owner in job["owners"]:
            if owner in seen:
                continue
            seen.add(owner)
            new_ptr, cursor = f3.cave_payload(candidate, owner, encoded, allowed, cursor)
            job.setdefault("new_ptrs", []).append(hex(new_ptr))

    hangul_live = f2.hangul_slot_map(candidate, mode=8)
    map8 = f2.slot_to_char_map(verified8, recovered8, hangul_live)
    dict8 = load_dictionary(bytes(candidate), DICT_8X16_BASE, DICT_8X16_END)

    def dec8(owner: int) -> str:
        return f2.decode_text(candidate, f2.u32(candidate, owner), dict8, map8)

    proofs = {
        "apsaras": dec8(UNIT_BASE + 5 * UNIT_STRIDE),
        "guncannon": dec8(UNIT_BASE + 37 * UNIT_STRIDE),
        "gm": dec8(UNIT_BASE + 43 * UNIT_STRIDE),
        "bd": dec8(UNIT_BASE + 46 * UNIT_STRIDE),
        "bd_h": dec8(UNIT_BASE + 47 * UNIT_STRIDE),
        "virgo_i": dec8(UNIT_BASE + 93 * UNIT_STRIDE),
        "virgo_ii": dec8(UNIT_BASE + 113 * UNIT_STRIDE),
    }
    gate(proofs["apsaras"] == "아프사라스 II", proofs)
    gate(proofs["guncannon"] == "짐 캐논 II", proofs)
    gate(proofs["gm"] == "짐 II", proofs)
    gate(proofs["bd"] == "블루 데스티니 II", proofs)
    gate("블루 데스티니 II" in proofs["bd_h"] and "비르고" not in proofs["bd_h"], proofs)
    gate(0x07FE in expand_to_slots(read_tokens(bytes(candidate), f2.u32(candidate, UNIT_BASE + 47 * UNIT_STRIDE) - ROM_BASE)[0], dict8), "BD II missing H badge")
    gate(proofs["virgo_i"] == "비르고 I", proofs)
    gate(proofs["virgo_ii"] == "비르고 II", proofs)
    gate(dec8(UNIT_BASE + 113 * UNIT_STRIDE + 0x24) == "비르고 II", "virgo II secondary drift")

    changed = {i for i, (old, new) in enumerate(zip(parent, candidate)) if old != new}
    gate(changed <= allowed, f"unrelated writes {len(changed - allowed)}")

    by_id = {str(row["record_id"]): row for row in merged["records"]}
    changed_ids = []
    for job in jobs:
        patch_merged_row(by_id[job["record_id"]], job["ko"])
        changed_ids.append(job["record_id"])
        gate("비르고" not in job["ko"] or "ビルゴ" in str(job["source"]), job)

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
    merged[BATCH_KEY] = {"batch_id": BATCH_ID, "changed_records": changed_ids, "restored": [job["ko"] for job in jobs]}
    payload_json = json.dumps(merged, ensure_ascii=False, indent=2) + "\n"
    SNAPSHOT.write_text(payload_json, encoding="utf-8")
    TRANSLATION_MERGED_JSON.write_text(payload_json, encoding="utf-8")
    update_translation_manifest(merged, SNAPSHOT)

    WORK.write_bytes(bytes(candidate))
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_profile_followup6_virgo_ii_restore",
        "batch_id": BATCH_ID,
        "parent_sha256": sha256(parent),
        "output": {"path": advance_relative(WORK), "size": len(candidate), "sha256": sha256(bytes(candidate))},
        "painted": painted,
        "cave": {"start": hex(CAVE_START), "end": hex(cursor), "capacity_end": hex(CAVE_END)},
        "changed_bytes": len(changed),
        "restored_records": len(jobs),
        "proofs": proofs,
        "verification": {
            "result": "PASS",
            "unrelated_bytes_preserved": True,
            "false_virgo_ii_restored": True,
            "real_virgo_ii_kept": True,
        },
    }
    (OUT / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("output", "cave", "restored_records", "proofs", "verification")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
