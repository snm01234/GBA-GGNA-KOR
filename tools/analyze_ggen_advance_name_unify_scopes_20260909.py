#!/usr/bin/env python3
from __future__ import annotations
import json, sys
from pathlib import Path
THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS))
from ggen_advance_project_paths import TRANSLATION_MERGED_JSON

TOKENS = ("무 라 프라가", "노이에른", "애너벨 가토", "왕자의 풍격", "무 씨", "무 못지않게", "무의 아버지")

def main():
    sys.stdout.reconfigure(encoding="utf-8")
    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    for row in merged["records"]:
        blob = str(row.get("translation_ko") or "") + "\n" + "\n".join(str(x) for x in (row.get("translation_segments") or []))
        if not any(t in blob for t in TOKENS) and str(row.get("translation_ko") or "") != "무……":
            continue
        print(row["record_id"], "scope="+str(row.get("source_scope")), "cat="+str(row.get("semantic_category")), "owners", len(row.get("owner_ids") or []), "policy", row.get("translation_policy"))
        print(" ", repr(row.get("translation_ko")))

if __name__ == "__main__":
    main()
