#!/usr/bin/env python3
"""Find Mu/Gato/Neuen/Master-Asia wording that needs unification."""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

THIS = Path(__file__).resolve().parent
ROOT = THIS.parent
sys.path.insert(0, str(THIS))
from ggen_advance_project_paths import TRANSLATION_MERGED_JSON


NEEDLES = (
    "무 라 프라가",
    "무우 라 프라가",
    "무라 프라가",
    "무우라",
    "프라가",
    "노이에른",
    "노이엔",
    "애너벨",
    "아나벨",
    "가토",
    "왕자의 풍격",
    "왕자의 바람",
    "동방불패는",
    "풍격",
)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    hits: dict[str, list[dict]] = defaultdict(list)
    mu_candidates = []
    for row in merged["records"]:
        ko = str(row.get("translation_ko") or "")
        segs = row.get("translation_segments") or []
        blob = ko + "\n" + "\n".join(str(item) for item in segs)
        jp = str(row.get("source_text") or "")
        for needle in NEEDLES:
            if needle in blob or needle in jp:
                hits[needle].append(row)
        if re.search(r"(^|[^\w가-힣])무($|[^\w가-힣우])", blob) or "ムウ" in jp or "フラガ" in jp:
            if "무" in blob or "ムウ" in jp or "フラガ" in jp:
                mu_candidates.append(row)

    for needle, rows in hits.items():
        uniq = Counter()
        print(f"\n== {needle!r} records={len(rows)}")
        shown = 0
        for row in rows:
            ko = str(row.get("translation_ko") or "")
            key = (row.get("semantic_category"), ko)
            uniq[key] += 1
        for (cat, ko), n in uniq.most_common(40):
            print(f"  x{n:3d} [{cat}] {ko!r}")
            shown += 1
        if len(uniq) > 40:
            print(f"  ... {len(uniq) - 40} more unique")

    print("\n== standalone-ish 무 / JP ムウ samples")
    seen = set()
    for row in mu_candidates:
        ko = str(row.get("translation_ko") or "")
        jp = str(row.get("source_text") or "")
        if "무 라" in ko or "무우" in ko or "ムウ" in jp or re.search(r"(^|[\\n、。！？\s「」『』（）])무([!！?？、。\s]|$)", ko):
            key = (ko, jp[:80])
            if key in seen:
                continue
            seen.add(key)
            print(f"  [{row.get('semantic_category')}] {row['record_id']}")
            print(f"    ko={ko!r}")
            print(f"    jp={jp[:120]!r}")
            if len(seen) >= 80:
                break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
