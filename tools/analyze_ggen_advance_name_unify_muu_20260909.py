#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS))
from ggen_advance_project_paths import TRANSLATION_MERGED_JSON, MAIN_TIP_ROM


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    print("== ムウ JP rows")
    for row in merged["records"]:
        jp = str(row.get("source_text") or "")
        ko = str(row.get("translation_ko") or "")
        segs = " | ".join(str(item) for item in (row.get("translation_segments") or []) if item)
        if "ムウ" not in jp and "무의" not in ko and "무……" not in ko and "무 씨" not in ko:
            continue
        print(f"{row['record_id']} [{row.get('semantic_category')}] {row.get('translation_status')} scope={row.get('source_scope')}")
        print(f"  ko={ko!r}")
        if segs:
            print(f"  segs={segs!r}")
        print(f"  jp={jp[:140]!r}")

    print("\n== leftover 애너벨 / 노이에른 / 풍격 / 무 라")
    for row in merged["records"]:
        blob = str(row.get("translation_ko") or "") + "\n" + "\n".join(str(x) for x in (row.get("translation_segments") or []))
        if any(tok in blob for tok in ("애너벨", "노이에른", "왕자의 풍격", "무 라 프라가")):
            print(row["record_id"], row.get("semantic_category"), row.get("source_scope"), repr(row.get("translation_ko")))

    print("\n== regex standalone 무")
    pat = re.compile(r"(^|[^가-힣])무([^가-힣우]|$)")
    for row in merged["records"]:
        ko = str(row.get("translation_ko") or "")
        segs = row.get("translation_segments") or []
        texts = [ko] + [str(x) for x in segs]
        if not any(pat.search(t.replace("\\n", "\n")) for t in texts):
            continue
        jp = str(row.get("source_text") or "")
        if "ムウ" not in jp and "フラガ" not in jp:
            continue
        print(row["record_id"], repr(ko), "jp", jp[:80])

    rom = MAIN_TIP_ROM.read_bytes()
    print("\n== zero caves")
    for start in range(0x012B0000, 0x01380000, 0x1000):
        end = start + 0x800
        if end > len(rom):
            break
        if all(b == 0 for b in rom[start:end]):
            # extend
            real_end = start
            while real_end < len(rom) and rom[real_end] == 0:
                real_end += 1
            if real_end - start >= 0x800:
                print(f"  0x{start:08X}-0x{real_end:08X} size=0x{real_end-start:X}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
