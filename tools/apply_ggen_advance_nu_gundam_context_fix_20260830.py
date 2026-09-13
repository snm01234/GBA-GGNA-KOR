#!/usr/bin/env python3
"""Correct only the context-proven Nu Gundam unit-name rows.

The reconstructed glyph is ambiguous in these name banks, so the gate uses
the immediately following Nu Gundam weapon rows (New Hyper Bazooka and Fin
Funnel) plus exact record identities.  Turn A's ∀99/월광접 variants and all
Turn A scenario dialogue are explicitly protected.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MERGED_PATH = ROOT / "integrated" / "translation" / "ggen_advance_translation_merged.json"
MANIFEST_PATH = ROOT / "integrated" / "translation" / "ggen_advance_translation_manifest.json"
REPORT_PATH = ROOT / "analysis" / "ggen_advance_nu_gundam_context_fix_20260830.json"
BATCH_ID = "user-confirmed-nu-gundam-context-fix-20260830"
TARGET_IDS = (
    "GGA-TEXT-0017A5F2",
    "GGA-TEXT-0017A60D",
    "GGA-TEXT-0017ABE3",
    "GGA-TEXT-0017ABEC",
    "GGA-UI-EXT-0017B273",
    "GGA-UI-EXT-0017B27C",
    "GGA-TEXT-0017D6CD",
    "GGA-TEXT-0017D6DB",
)
PROTECTED_TURN_A_IDS = (
    "GGA-TEXT-0017A70E",
    "GGA-TEXT-0017A734",
    "GGA-TEXT-0017AC78",
    "GGA-TEXT-0017AC8B",
    "GGA-UI-EXT-0017B308",
    "GGA-UI-EXT-0017B31B",
    "GGA-TEXT-0017D7BF",
    "GGA-TEXT-0017D7E1",
)


def check(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"gate failed: {message}")


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def payload_digest(row: dict[str, Any]) -> str:
    return digest({
        "record_id": row["record_id"],
        "batch_id": row["overlay_batch_id"],
        "translation_ko": row.get("translation_ko") or "",
        "translation_segments": row.get("translation_segments"),
        "translation_status": row.get("translation_status") or "",
        "translation_source": row.get("translation_source") or "",
        "source_model": row.get("source_model") or "",
        "prompt_version": row.get("prompt_version") or "",
        "review_status": row.get("review_status") or "",
        "review_count": row.get("review_count") or 0,
        "reviewed_at": row.get("reviewed_at") or "",
        "translator_notes": row.get("translator_notes") or "",
        "qa_status": row.get("qa_status") or "",
    })


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=MERGED_PATH)
    parser.add_argument("--out", type=Path, default=MERGED_PATH)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    args = parser.parse_args()

    root = json.loads(args.source.read_text(encoding="utf-8"))
    records = root.get("records")
    check(isinstance(records, list), "merged records are not a list")
    by_id = {str(row.get("record_id")): row for row in records}
    check(len(by_id) == len(records), "duplicate record IDs")
    check(all(record_id in by_id for record_id in TARGET_IDS + PROTECTED_TURN_A_IDS), "target/protected record set drift")

    # Static semantic gate: these weapons belong to Nu Gundam, not Turn A.
    check(by_id["GGA-TEXT-0017A5FB"].get("source_text") == "ニューハイパーバズーカ", "Nu weapon context drift")
    check(by_id["GGA-TEXT-0017A602"].get("source_text") == "フィン・ファンネル<0813>", "Fin Funnel context drift")
    check(all(by_id[rid].get("translation_ko") == "턴에이 건담" for rid in TARGET_IDS), "Nu target translation precondition drift")
    check(all("턴에이 건담" in str(by_id[rid].get("translation_ko") or "") for rid in PROTECTED_TURN_A_IDS), "protected Turn A translation drift")
    protected_before = {rid: canonical_json(by_id[rid]) for rid in PROTECTED_TURN_A_IDS}

    parent_identity = str(root.get("identity", {}).get("translation_overlay_identity_sha256") or "")
    check(bool(parent_identity), "parent translation overlay identity missing")
    changes = []
    for record_id in TARGET_IDS:
        row = by_id[record_id]
        before = {key: row.get(key) for key in (
            "translation_ko", "translation_status", "translation_source", "review_status",
            "review_count", "reviewed_at", "overlay_batch_id", "translator_notes",
        )}
        row["translation_ko"] = "ν건담"
        row["translation_status"] = "translated"
        row["translation_source"] = "user_verified"
        row["source_model"] = ""
        row["prompt_version"] = ""
        row["review_status"] = "user_verified"
        row["review_count"] = int(row.get("review_count") or 0) + 1
        row["reviewed_at"] = "2026-08-30"
        row["overlay_batch_id"] = BATCH_ID
        note = str(row.get("translator_notes") or "").rstrip()
        addition = "context-confirmed ν건담: adjacent New Hyper Bazooka / Fin Funnel; Turn A variants protected"
        row["translator_notes"] = f"{note}; {addition}".lstrip("; ")
        row["translation_payload_sha256"] = payload_digest(row)
        changes.append({
            "record_id": record_id,
            "target_file_offset": row.get("target_file_offset"),
            "source_text": row.get("source_text"),
            "owner_ids": row.get("owner_ids", []),
            "before": before,
            "after": {key: row.get(key) for key in before},
            "translation_payload_sha256": row["translation_payload_sha256"],
        })

    check(all(canonical_json(by_id[rid]) == protected_before[rid] for rid in PROTECTED_TURN_A_IDS), "protected Turn A record changed")
    identity = digest({
        "parent": parent_identity,
        "batch_id": BATCH_ID,
        "records": [{"record_id": row["record_id"], "payload": row["translation_payload_sha256"]} for row in changes],
    })
    root.setdefault("identity", {})["parent_translation_overlay_identity_sha256"] = parent_identity
    root["identity"]["user_confirmed_nu_gundam_context_fix_identity_sha256"] = identity
    root["identity"]["translation_overlay_identity_sha256"] = identity
    statuses = Counter(str(row.get("translation_status", "")) for row in records)
    reviews = Counter(str(row.get("review_status", "")) for row in records)
    root["merged_translation_status_counts"] = dict(sorted(statuses.items()))
    root.setdefault("summary", {})["merged_translation_status_counts"] = dict(sorted(statuses.items()))
    root["summary"]["merged_review_status_counts"] = dict(sorted(reviews.items()))
    root["summary"]["translation_overlay_identity_sha256"] = identity
    root["summary"]["nu_gundam_context_fix_records"] = len(changes)
    root["nu_gundam_context_fix"] = {
        "batch_id": BATCH_ID,
        "changed_records": len(changes),
        "translation": "context-proven ν Gundam rows: 턴에이 건담 → ν건담",
        "protected_turn_a_records": len(PROTECTED_TURN_A_IDS),
        "identity_sha256": identity,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(root, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.out.resolve() == MERGED_PATH.resolve():
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        output_sha = sha256_file(args.out)
        manifest.update({
            "sha256": output_sha,
            "source_sha256": output_sha,
            "record_count": len(records),
            "record_identity_sha256": root.get("identity", {}).get("record_identity_sha256"),
            "translation_overlay_identity_sha256": identity,
            "record_translation_status_counts": dict(sorted(statuses.items())),
            "source_summary_translation_status_counts": dict(sorted(statuses.items())),
        })
        MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_nu_gundam_context_fix",
        "result": "PASS",
        "batch_id": BATCH_ID,
        "identity_sha256": identity,
        "changed_records": changes,
        "protected_turn_a_record_ids": list(PROTECTED_TURN_A_IDS),
        "verification": {
            "nu_weapon_context_verified": True,
            "changed_record_count": len(changes),
            "protected_turn_a_records_unchanged": True,
        },
        "output_sha256": sha256_file(args.out),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "changed_records": len(changes), "protected_turn_a_records": len(PROTECTED_TURN_A_IDS), "identity_sha256": identity}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
