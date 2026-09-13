import json, re
from pathlib import Path
root = Path("outputs/20260912_allclear_profile_desc/work_batches")
jp_kana = re.compile(r"[\u3040-\u30ff]")
issues = []
count = 0
for i in range(4):
    src = json.loads((root / f"batch{i}.json").read_text(encoding="utf-8"))
    ko = json.loads((root / f"batch{i}_ko.json").read_text(encoding="utf-8"))
    if len(src) != len(ko):
        issues.append(f"batch{i} len {len(src)} vs {len(ko)}")
    for s, t in zip(src, ko):
        count += 1
        key = f"{t.get('kind', s['kind'])}{t.get('index', s['index'])}p{t.get('page', s['page'])}"
        if s["fix_only"]:
            lines = t.get("ko_fix")
            expect = len(s["fix_selectors"])
            field = "ko_fix"
        else:
            lines = t.get("ko_lines")
            expect = s["n_lines"]
            field = "ko_lines"
        if lines is None:
            issues.append(f"missing {field} {key}")
            continue
        if len(lines) != expect:
            issues.append(f"{field} len {key} {len(lines)}!={expect}")
        for ln in lines:
            if len(ln) > 18:
                issues.append(f"width {len(ln)} {key} {ln}")
            if not str(ln).strip():
                issues.append(f"empty {key}")
            if jp_kana.search(ln):
                issues.append(f"kana {key} {ln}")
print("items", count, "issues", len(issues))
for x in issues[:40]:
    print(x)
for i in range(4):
    ko = json.loads((root / f"batch{i}_ko.json").read_text(encoding="utf-8"))
    for t in ko:
        if t.get("kind") == "char" and t.get("index") == 0:
            print("AISHA", t.get("page"), t.get("ko_fix") or t.get("ko_lines"))
        if t.get("kind") == "unit" and t.get("index") == 165:
            print("ARGAMA", t.get("page"), t.get("fix_only"), t.get("fix_selectors"), t.get("ko_fix") or t.get("ko_lines"))
