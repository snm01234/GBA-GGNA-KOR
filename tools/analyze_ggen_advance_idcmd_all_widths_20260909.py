#!/usr/bin/env python3
"""Audit all ID-command text families against measured ss4/ss6 boxes."""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image

THIS = Path(__file__).resolve().parent
ROOT = THIS.parent
sys.path.insert(0, str(THIS))

from ggen_advance_project_paths import TRANSLATION_MERGED_JSON

OUT = ROOT / "outputs" / "20260909_idcmd_full_audit"
CATS = (
    "id_command_description",
    "id_command_name",
    "id_command_effect_summary",
    "inactive_id_command_placeholder",
    "id_command_fallback_text",
)


def visible_len(text: str) -> int:
    return len(text.replace("\n", ""))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))

    by_cat: dict[str, list[dict]] = defaultdict(list)
    for row in merged["records"]:
        cat = str(row.get("semantic_category") or "")
        if cat not in CATS:
            continue
        ko = str(row.get("translation_ko") or "")
        jp = str(row.get("source_text") or "")
        status = str(row.get("translation_status") or "")
        by_cat[cat].append(
            {
                "record_id": row["record_id"],
                "jp": jp,
                "ko": ko,
                "jp_len": visible_len(jp),
                "ko_len": visible_len(ko),
                "status": status,
                "delta": visible_len(ko) - visible_len(jp) if ko else None,
            }
        )

    report: dict = {}
    for cat, rows in by_cat.items():
        translated = [r for r in rows if r["status"] == "translated" and r["ko"]]
        hist = Counter(r["ko_len"] for r in translated)
        over17 = [r for r in translated if r["ko_len"] > 17]
        over_jp = [r for r in translated if r["jp_len"] and r["ko_len"] > r["jp_len"]]
        uniq_over17 = {}
        for r in over17:
            uniq_over17.setdefault((r["jp"], r["ko"]), []).append(r["record_id"])
        longest = sorted(translated, key=lambda r: (-r["ko_len"], r["record_id"]))[:20]
        report[cat] = {
            "total": len(rows),
            "translated": len(translated),
            "ko_len_hist": hist.most_common(),
            "jp_len_hist": Counter(r["jp_len"] for r in translated).most_common(),
            "over_17_records": len(over17),
            "over_17_unique": [
                {"jp": jp, "ko": ko, "jp_len": visible_len(jp), "ko_len": visible_len(ko), "count": len(ids)}
                for (jp, ko), ids in sorted(uniq_over17.items(), key=lambda kv: -visible_len(kv[0][1]))
            ],
            "longest": longest,
        }
        print(f"\n== {cat} total={len(rows)} translated={len(translated)} over17={len(over17)}")
        print("ko hist", hist.most_common())
        print("jp hist", Counter(r["jp_len"] for r in translated).most_common())
        print("longest:")
        for r in longest[:12]:
            print(f"  {r['ko_len']:2d}/{r['jp_len']:2d} {r['ko']!r} <= {r['jp']!r}")

    # Crop name/effect bands from existing composites if present
    prev = ROOT / "outputs" / "20260909_idcmd_desc_overflow" / "previews"
    for n in (4, 6):
        path = prev / f"ss{n}_composite.png"
        if not path.exists():
            continue
        im = Image.open(path)
        # list rows roughly y=48..120
        im.crop((0, 40 * 4, 240 * 4, 128 * 4)).save(OUT / f"ss{n}_list.png")
        im.crop((0, 128 * 4, 240 * 4, 160 * 4)).save(OUT / f"ss{n}_desc.png")

    (OUT / "audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
