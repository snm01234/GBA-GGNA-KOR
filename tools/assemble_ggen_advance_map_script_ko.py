#!/usr/bin/env python3
"""Assemble chunk Korean drafts into the map-script KO map."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UNIQUE = ROOT / "analysis" / "map_script_ko_work" / "unique_complete_jp.json"
OUT_DIR = ROOT / "analysis" / "map_script_ko_work" / "out"
KO_MAP = ROOT / "analysis" / "ggen_advance_map_script_dialogue_ko_20260828.json"
KANA_RE = re.compile(r"[\u3040-\u30FA\u30FC-\u30FF]")


def fail(message: str) -> None:
    raise SystemExit(f"gate failed: {message}")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    unique = json.loads(UNIQUE.read_text(encoding="utf-8"))["records"]
    by_id = {int(item["id"]): item for item in unique}
    filled: dict[int, list[str]] = {}
    for path in sorted(OUT_DIR.glob("chunk_*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        records = payload["records"] if isinstance(payload, dict) else payload
        for item in records:
            item_id = int(item["id"])
            ko_parts = list(item["parts_ko"])
            jp_parts = list(item.get("parts_jp") or by_id[item_id]["parts_jp"])
            if item_id not in by_id:
                fail(f"unknown id {item_id} in {path.name}")
            if jp_parts != by_id[item_id]["parts_jp"]:
                fail(f"parts_jp mismatch for id {item_id} in {path.name}")
            if len(ko_parts) != len(jp_parts):
                fail(f"parts_ko length mismatch for id {item_id}")
            if any(KANA_RE.search(part or "") for part in ko_parts):
                fail(f"kana in KO id {item_id}: {ko_parts}")
            if item_id in filled and filled[item_id] != ko_parts:
                fail(f"conflicting KO for id {item_id}")
            filled[item_id] = ko_parts
    missing = sorted(item_id for item_id in by_id if item_id not in filled)
    if missing:
        fail(f"missing {len(missing)} unique ids; first: {missing[:12]}")
    records = []
    for item in unique:
        records.append(
            {
                "id": item["id"],
                "parts_jp": item["parts_jp"],
                "parts_ko": filled[int(item["id"])],
            }
        )
    KO_MAP.write_text(json.dumps({"records": records}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "unique": len(records), "output": str(KO_MAP)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
