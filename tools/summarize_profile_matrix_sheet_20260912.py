"""Summarize merged-sheet coverage vs live ROM for profile matrices."""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from ggen_advance_project_paths import TRANSLATION_MERGED_JSON

OUT = ROOT / "outputs" / "20260912_allclear_profile_desc"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    fam = defaultdict(lambda: Counter())
    sel = defaultdict(lambda: Counter())
    samples = []
    extra_translated = []
    sel0_translated = []
    missing_ko = []
    for row in merged["records"]:
        family = row.get("ui_family") or (row.get("source_families") or [None])[0]
        if family not in ("fixed16_option_matrix", "fixed40_option_matrix"):
            continue
        selector = row.get("selector")
        status = row.get("translation_status") or "none"
        ko = (row.get("translation_ko") or "").strip()
        fam[family][status] += 1
        key = f"{family}:sel{selector}"
        sel[key][status] += 1
        if ko:
            if selector == 0 and len(sel0_translated) < 8:
                sel0_translated.append({"family": family, "index": row.get("record_index"), "selector": selector, "owner": (row.get("owner_ids") or [None])[0], "jp_src": row.get("source_text", "")[:80], "ko": ko})
            rendered_limit = 6 if family == "fixed16_option_matrix" else 5
            if selector is not None and selector >= rendered_limit and len(extra_translated) < 8:
                extra_translated.append({"family": family, "index": row.get("record_index"), "selector": selector, "ko": ko, "jp_src": row.get("source_text", "")[:80]})
        else:
            if len(missing_ko) < 8:
                missing_ko.append({"family": family, "index": row.get("record_index"), "selector": selector, "status": status, "src": (row.get("source_text") or "")[:80]})
    report = {
        "by_family_status": {k: dict(v) for k, v in fam.items()},
        "by_selector_status": {k: dict(v) for k, v in sorted(sel.items())},
        "sel0_translated_samples": sel0_translated,
        "extra_translated_samples": extra_translated,
        "missing_ko_samples": missing_ko,
        "n_records": sum(sum(v.values()) for v in fam.values()),
    }
    (OUT / "merged_matrix_coverage.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["by_family_status"], ensure_ascii=False, indent=2))
    print("--- selector buckets ---")
    # collapse selectors into rendered vs extra
    buckets = Counter()
    for row in merged["records"]:
        family = row.get("ui_family") or (row.get("source_families") or [None])[0]
        if family not in ("fixed16_option_matrix", "fixed40_option_matrix"):
            continue
        selector = row.get("selector")
        rendered_limit = 6 if family == "fixed16_option_matrix" else 5
        bucket = "rendered" if selector is not None and selector < rendered_limit else "extra"
        has_ko = bool((row.get("translation_ko") or "").strip())
        buckets[f"{family}:{bucket}:{'ko' if has_ko else 'no_ko'}:{row.get('translation_status')}"] += 1
    print(json.dumps(dict(buckets), ensure_ascii=False, indent=2))
    print("--- sel0 samples ---")
    print(json.dumps(sel0_translated, ensure_ascii=False, indent=2))
    print("--- extra samples ---")
    print(json.dumps(extra_translated, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
