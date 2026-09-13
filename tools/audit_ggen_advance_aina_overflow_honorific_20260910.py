#!/usr/bin/env python3
"""Audit ss1-ss4 portrait overflow and Korean sibling-address gender."""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from ggen_advance_project_paths import TRANSLATION_MERGED_JSON  # noqa: E402

OUT = ROOT / "outputs" / "20260910_aina_overflow_honorific"
ANALYSIS = ROOT / "analysis" / "ggen_advance_aina_overflow_honorific_audit_20260910.json"
DIALOGUE_SCOPES = {"scenario_map_script", "scenario_main", "battle_event_dialogue"}
SS_IDS = {
    1: "GGA-MAPSCRIPT-00F7F729",
    2: "GGA-MAPSCRIPT-00F7F766",
    3: "GGA-MAPSCRIPT-00F7F7C3",
    4: "GGA-MAPSCRIPT-00F7F875",
}
JP_BROTHER = re.compile(r"お兄さま|お兄さん|お兄ちゃん|兄貴|兄さん|兄ちゃん|兄")
JP_SISTER = re.compile(r"お姉さま|お姉さん|お姉ちゃん|姉さん|姉ちゃん|姉")
KO_BROTHER = re.compile(r"오라버니|오빠|형님|형")
KO_SISTER = re.compile(r"누나|언니")
FEMALE_FIRST = re.compile(r"(私|あたし|わたし|わたくし|妾)")
MALE_FIRST = re.compile(r"(俺|オレ|僕|ボク|わし|ワシ|拙者)")
AINA_SPEAKER = "0x000A"

# Vocative / kinship 형, not 대형·신형·개량형.
KO_KIN_HYUNG = re.compile(r"(?<![가-힣])형(?![가-힣])")


def cells(text: str) -> int:
    return len(text.replace("\n", ""))


def jp_lines(text: str) -> list[str]:
    return [part for part in str(text).split("\\n") if part != ""]


def ko_lines(row: dict[str, Any]) -> list[str]:
    segments = [str(item) for item in (row.get("translation_segments") or []) if str(item)]
    if segments:
        return segments
    return [part for part in str(row.get("translation_ko") or "").split("\n") if part]


def yellow_box(img: Image.Image) -> dict[str, int]:
    pix = img.load()
    width, height = img.size
    yellow = []
    for y in range(height):
        for x in range(width):
            r, g, b = pix[x, y][:3]
            if r > 180 and g > 160 and b < 90:
                yellow.append((x, y))
    xs = [p[0] for p in yellow]
    ys = [p[1] for p in yellow]
    return {
        "x0": min(xs),
        "x1": max(xs),
        "y0": min(ys),
        "y1": max(ys),
        "inner_right_guess": max(xs) - 4,
    }


def rightmost_dark(img: Image.Image, box: dict[str, int], y0: int, y1: int) -> int:
    pix = img.load()
    right = -1
    for y in range(y0, y1):
        for x in range(box["x0"] + 40, min(img.size[0], box["x1"] + 1)):
            r, g, b = pix[x, y][:3]
            if r < 90 and g < 70 and b < 40:
                right = max(right, x)
    return right


def jp_kind(source: str) -> str:
    for token in ("お兄さま", "お兄さん", "お兄ちゃん", "兄貴", "兄さん", "兄ちゃん"):
        if token in source:
            return token
    if "兄" in source:
        return "兄"
    for token in ("お姉さま", "お姉さん", "お姉ちゃん", "姉さん", "姉ちゃん"):
        if token in source:
            return token
    if "姉" in source:
        return "姉"
    return ""


def ko_kind(text: str) -> str:
    for token in ("오라버니", "오빠", "형님", "누나", "언니"):
        if token in text:
            return token
    if KO_KIN_HYUNG.search(text) or "형" in text and not any(
        noise in text for noise in ("대형", "신형", "개량형", "시작형", "양산형", "육전형", "변형", "함형", "함형")
    ):
        if re.search(r"(형[,!\.…]|형 |형$|형은|형이|형을|형과|형께|형님|형아)", text):
            return "형"
    return ""


def speaker_gender_hint(source: str) -> str:
    female = bool(FEMALE_FIRST.search(source))
    male = bool(MALE_FIRST.search(source))
    if female and not male:
        return "female_pronoun"
    if male and not female:
        return "male_pronoun"
    if "お兄さま" in source or "お姉さま" in source:
        return "likely_female_honorific"
    return ""


def classify(row: dict[str, Any]) -> dict[str, Any] | None:
    source = str(row.get("source_text") or "")
    ko = str(row.get("translation_ko") or "")
    jp = jp_kind(source)
    ko_addr = ko_kind(ko)
    if not jp and not ko_addr:
        return None
    if jp not in {"お兄さま", "お兄さん", "お兄ちゃん", "兄貴", "兄さん", "兄ちゃん", "兄", "お姉さま", "お姉さん", "お姉ちゃん", "姉さん", "姉ちゃん", "姉"}:
        if not ko_addr:
            return None
    speaker = str(row.get("speaker_id") or "")
    hint = speaker_gender_hint(source)
    aina = speaker == AINA_SPEAKER or "アイナ" in source or "아이나" in ko
    expected = ""
    bucket = "review"
    if jp in {"お兄さま", "お兄さん", "お兄ちゃん", "兄貴", "兄さん", "兄ちゃん", "兄"}:
        if aina or hint in {"female_pronoun", "likely_female_honorific"}:
            expected = "오빠"
            if ko_addr == "오빠" or ko_addr == "오라버니":
                bucket = "female_brother_ok"
            elif ko_addr in {"형", "형님"}:
                bucket = "female_brother_wrong"
            else:
                bucket = "female_brother_other"
        elif hint == "male_pronoun":
            expected = "형/형님"
            if ko_addr in {"형", "형님"}:
                bucket = "male_brother_ok"
            elif ko_addr == "오빠":
                bucket = "male_brother_wrong"
            else:
                bucket = "male_brother_other"
        else:
            if ko_addr == "오빠":
                bucket = "brother_rendered_female"
            elif ko_addr in {"형", "형님"}:
                bucket = "brother_rendered_male"
            else:
                bucket = "brother_unspecified"
    elif jp in {"お姉さま", "お姉さん", "お姉ちゃん", "姉さん", "姉ちゃん", "姉"}:
        if hint in {"female_pronoun", "likely_female_honorific"} or aina:
            expected = "언니"
            if ko_addr == "언니":
                bucket = "female_sister_ok"
            elif ko_addr == "누나":
                bucket = "female_sister_wrong"
            else:
                bucket = "female_sister_other"
        elif hint == "male_pronoun":
            expected = "누나"
            if ko_addr == "누나":
                bucket = "male_sister_ok"
            elif ko_addr == "언니":
                bucket = "male_sister_wrong"
            else:
                bucket = "male_sister_other"
        else:
            if ko_addr == "언니":
                bucket = "sister_rendered_female"
            elif ko_addr == "누나":
                bucket = "sister_rendered_male"
            else:
                bucket = "sister_unspecified"
    return {
        "record_id": row["record_id"],
        "source_scope": row.get("source_scope"),
        "speaker_id": speaker,
        "jp_term": jp,
        "ko_term": ko_addr,
        "expected": expected,
        "bucket": bucket,
        "gender_hint": hint,
        "aina_scene": aina,
        "source_text": source,
        "translation_ko": ko,
        "ko_line_cells": [cells(line) for line in ko_lines(row)],
        "jp_line_cells": [len(line) for line in jp_lines(source)],
    }


def measure_states() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    measured = {}
    for n in range(1, 5):
        path = ROOT / f"SD Gundam GGeneration Advance (Korean).ss{n}"
        img = Image.open(path).convert("RGB")
        preview = img.resize((img.width * 4, img.height * 4), Image.Resampling.NEAREST)
        preview.save(OUT / f"ss{n}_preview.png")
        box = yellow_box(img)
        line1 = rightmost_dark(img, box, box["y0"] + 18, min(box["y1"] - 16, box["y0"] + 34))
        line2 = rightmost_dark(img, box, box["y0"] + 34, box["y1"] - 4)
        inner = box["x1"] - 3
        measured[str(n)] = {
            "size": list(img.size),
            "box": box,
            "line1_rightmost_text_px": line1,
            "line2_rightmost_text_px": line2,
            "inner_right_px": inner,
            "line2_overflow_px": max(0, line2 - inner),
            "cells_from_x52": round((inner - 52) / 12, 2),
        }
    return measured


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    measured = measure_states()
    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    by_id = {str(row["record_id"]): row for row in merged["records"]}

    ss_rows = []
    for n, record_id in SS_IDS.items():
        row = by_id[record_id]
        jp = jp_lines(str(row.get("source_text") or ""))
        ko = ko_lines(row)
        ss_rows.append(
            {
                "ss": n,
                "record_id": record_id,
                "speaker_id": row.get("speaker_id"),
                "overlay_batch_id": row.get("overlay_batch_id"),
                "source_text": row.get("source_text"),
                "translation_ko": row.get("translation_ko"),
                "jp_cells": [len(line) for line in jp],
                "ko_cells": [cells(line) for line in ko],
                "contains_apsaras": "아프사라스" in str(row.get("translation_ko") or ""),
                "contains_hyung": "형" in str(row.get("translation_ko") or ""),
                "notes": row.get("translator_notes"),
            }
        )

    dialogue_hist: Counter[int] = Counter()
    over_14 = []
    over_15 = []
    exact_15 = []
    apsaras_15 = []
    for row in merged["records"]:
        if row.get("source_scope") not in DIALOGUE_SCOPES:
            continue
        if row.get("scope_status") == "alias":
            continue
        if row.get("translation_status") != "translated":
            continue
        for line in ko_lines(row):
            n = cells(line)
            dialogue_hist[n] += 1
            item = {
                "record_id": row["record_id"],
                "source_scope": row.get("source_scope"),
                "speaker_id": row.get("speaker_id"),
                "line": line,
                "cells": n,
                "jp": row.get("source_text"),
                "overlay_batch_id": row.get("overlay_batch_id"),
            }
            if n > 15:
                over_15.append(item)
            elif n == 15:
                exact_15.append(item)
                if "아프사라스" in line:
                    apsaras_15.append(item)
            if n > 14:
                over_14.append(item)

    honorifics = []
    for row in merged["records"]:
        if row.get("scope_status") == "alias":
            continue
        item = classify(row)
        if item:
            honorifics.append(item)
    buckets = Counter(item["bucket"] for item in honorifics)
    aina_wrong = [item for item in honorifics if item["bucket"] == "female_brother_wrong"]
    aina_ok = [
        item
        for item in honorifics
        if item["aina_scene"] and item["bucket"] == "female_brother_ok"
    ]

    aina_map = [
        {
            "record_id": row["record_id"],
            "translation_ko": row.get("translation_ko"),
            "source_text": row.get("source_text"),
            "ko_cells": [cells(line) for line in ko_lines(row)],
            "jp_cells": [len(line) for line in jp_lines(str(row.get("source_text") or ""))],
        }
        for row in merged["records"]
        if row.get("speaker_id") == AINA_SPEAKER
        and row.get("source_scope") == "scenario_map_script"
        and ("兄" in str(row.get("source_text") or "") or "형" in str(row.get("translation_ko") or "") or "오빠" in str(row.get("translation_ko") or ""))
    ]

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_aina_overflow_honorific_audit_20260910",
        "visual_limit_cells": 14,
        "current_gate_cells": 15,
        "states": measured,
        "ss_rows": ss_rows,
        "dialogue_line_cell_histogram": dict(sorted(dialogue_hist.items())),
        "counts": {
            "dialogue_lines": sum(dialogue_hist.values()),
            "exact_15": len(exact_15),
            "over_15": len(over_15),
            "over_14": len(over_14),
            "apsaras_exact_15": len(apsaras_15),
            "honorific_records": len(honorifics),
            "female_brother_wrong": buckets.get("female_brother_wrong", 0),
            "female_brother_ok": buckets.get("female_brother_ok", 0),
            "male_brother_wrong": buckets.get("male_brother_wrong", 0),
            "male_sister_wrong": buckets.get("male_sister_wrong", 0),
            "female_sister_wrong": buckets.get("female_sister_wrong", 0),
        },
        "buckets": dict(buckets),
        "apsaras_exact_15": apsaras_15,
        "exact_15_aina_or_ss_scene": [
            item
            for item in exact_15
            if item["record_id"] in SS_IDS.values()
            or item.get("speaker_id") == AINA_SPEAKER
            or "아프사라스" in item["line"]
        ],
        "aina_brother_map": aina_map,
        "honorifics": honorifics,
        "aina_wrong": aina_wrong,
        "aina_ok_samples": aina_ok[:12],
        "exact_15": exact_15,
        "over_15": over_15,
    }
    ANALYSIS.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "states": {k: {"overflow": v["line2_overflow_px"], "cells_from_x52": v["cells_from_x52"]} for k, v in measured.items()},
                "ss_rows": [{k: row[k] for k in ("ss", "record_id", "ko_cells", "jp_cells", "contains_apsaras", "contains_hyung")} for row in ss_rows],
                "counts": report["counts"],
                "buckets": dict(buckets),
                "aina_brother_map": len(aina_map),
                "analysis": str(ANALYSIS),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
