#!/usr/bin/env python3
"""Dump every ムウ / アナベル / ノイエン / 風格 row with ids and lengths."""
from __future__ import annotations

import json
import sys
from pathlib import Path

THIS = Path(__file__).resolve().parent
ROOT = THIS.parent
sys.path.insert(0, str(THIS))
from ggen_advance_project_paths import TRANSLATION_MERGED_JSON


def vis(text: str) -> int:
    return max((len(line) for line in text.replace("\\n", "\n").split("\n")), default=0)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    keys = ("ムウ", "フラガ", "アナベル", "ガトー", "ノイエン", "ビッター", "風格", "風だ", "애너벨", "노이에른", "무 라", "왕자의")
    print("== targeted rows")
    for row in merged["records"]:
        ko = str(row.get("translation_ko") or "")
        segs = "\n".join(str(item) for item in (row.get("translation_segments") or []))
        jp = str(row.get("source_text") or "")
        blob = ko + "\n" + segs + "\n" + jp
        if not any(key in blob for key in keys):
            continue
        interesting = any(
            token in blob
            for token in (
                "ムウ",
                "アナベル",
                "애너벨",
                "노이에른",
                "ノイエン",
                "風格",
                "왕자의",
                "무 라",
                "무 씨",
                "무……",
                "무의",
                "무 못",
            )
        )
        if not interesting:
            continue
        status = row.get("translation_status")
        print(
            f"{row['record_id']} [{row.get('semantic_category')}] {status} "
            f"ko_len={vis(ko)} font={row.get('font_mode') or row.get('render_font')}"
        )
        print(f"  ko={ko!r}")
        print(f"  jp={jp[:160]!r}")
        if segs and segs != ko:
            print(f"  segs={segs!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
