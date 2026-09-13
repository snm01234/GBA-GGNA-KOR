#!/usr/bin/env python3
"""Grade short_label_a remaining 8x16 slots by trusted exact short-label match.

Read-only.  Does not modify charmap, unified source, or ROM.

Method follows progress §22.46 (地下基地 / 月光蝶 / 森林 / 少年・一年戦争):
align production/UI short labels against already-decoded same-ROM Japanese
by exact visible length and known 8x16 anchors.  Suffix-only unique
candidates and Viterbi-only votes are never treated as exact / grade A.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import analyze_ggen_advance_8x16_language_rerank as lang
import analyze_ggen_advance_8x16_multi_exact_wildcard as multi
import rebuild_ggen_advance_japanese_charmap as rebuild

ROOT = Path(__file__).resolve().parent.parent
ANALYSIS = ROOT / "analysis"
SLICES_DEFAULT = ANALYSIS / "ggen_advance_8x16_remaining_683_work_slices_20260829.json"
CATALOG_DEFAULT = ANALYSIS / "ggen_advance_8x16_remaining_683_catalog_20260829.json"
MAP8_DEFAULT = ANALYSIS / "ggen_advance_8x16_charmap_supplement_20260828.json"
MAP12_DEFAULT = ANALYSIS / "ggen_advance_12x12_identified_charmap_20260828.json"
MERGED_DEFAULT = ANALYSIS / "ggen_advance_translation_merged_20260828.json"
MAPSCRIPT_DEFAULT = ANALYSIS / "ggen_advance_map_script_translation_source_20260828.json"
PROD_KO_DEFAULT = ANALYSIS / "_tmp_ko_production.json"
OUT_DEFAULT = ANALYSIS / "ggen_advance_8x16_remaining_683_grade_short_label_a_20260829.json"
VITERBI_DEFAULT = ANALYSIS / "ggen_advance_8x16_remaining_683_viterbi_20260829.json"

AGENT = "short_label_a"
QUARANTINE = {0x03D9, 0x0101, 0x05F2, 0x0514, 0x0652}
NON_8X16 = {"configuration_option_text"}
SHORT_LABEL_CATEGORIES = {
    "series_title",
    "stage_location_name",
    "stage_code",
    "unit_name",
    "unit_name_alternate",
    "weapon_name",
    "weapon_name_alias",
    "character_name",
    "upgrade_part_name",
    "unit_defense_ability",
    "unit_ai_type",
}
JP_RE = re.compile(r"[ぁ-んァ-ヶ一-龯々ー・∀α]")
SANDWICH_RE = re.compile(r"[ぁ-んァ-ヶ一-龯][A-Za-z][ぁ-んァ-ヶ一-龯]")
MARKER_TOKEN_RE = re.compile(r"¤[0-9A-Fa-f]{4}¤")
SLOT_MARK_RE = re.compile(r"¤([0-9A-Fa-f]{4})¤")
CJK_RE = re.compile(r"[ぁ-んァ-ヶ一-龯々ー]")
TYPE_SPAN_RE = re.compile(r"ま(?P<body>.+?)(?:MS|MA|戦艦)")
CTRL_RE = re.compile(r"<0(?:7F[8BCDE]|813)>", re.IGNORECASE)
SHORT_EXACT_MAX_LEN = 16
SHORT_EXACT_MAX_UNRESOLVED = 3
SHORT_EXACT_MAX_TRAILING_UNKNOWN = 2


def refuse_outside(path: Path) -> Path:
    path = path.resolve()
    try:
        path.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise SystemExit(f"refused path outside advance workspace: {path}") from exc
    return path


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_map12_chars(path: Path) -> dict[int, str]:
    payload = load_json(path)
    return {int(str(k), 16): str(v) for k, v in payload.get("verified_charmap", {}).items()}


def is_clean_label(text: str) -> bool:
    if not text or SANDWICH_RE.search(text):
        return False
    jp = len(JP_RE.findall(text))
    if jp == 0:
        return any(ch.isascii() and ch.isalnum() for ch in text) and len(text) <= 12
    return jp / max(1, len(text)) >= 0.35


def add_corpus(
    by_length: dict[int, list[tuple[str, list[dict[str, str]]]]],
    seen: dict[str, list[dict[str, str]]],
    text: str,
    origin: str,
    tier: str,
    *,
    short_only: bool = False,
) -> None:
    text = text.replace("\\n", "").replace("\n", "").strip()
    if not text or len(text) < 2 or len(text) > (16 if short_only else 80):
        return
    if lang.SLOT_RE.search(text) or "�" in text or "\ufffd" in text:
        return
    if not is_clean_label(text):
        return
    item = {"path": origin, "tier": tier}
    if text not in seen:
        seen[text] = [item]
        by_length[len(text)].append((text, seen[text]))
    elif item not in seen[text]:
        seen[text].append(item)


def walk_source_strings(value: Any) -> list[str]:
    out: list[str] = []
    if isinstance(value, dict):
        if "translations" in value and isinstance(value["translations"], dict):
            out.extend(str(k) for k in value["translations"].keys())
        for key, child in value.items():
            if key == "translations":
                continue
            if key in {"jp", "source_text", "source_text_seed", "joined"} and isinstance(child, str):
                out.append(child)
            else:
                out.extend(walk_source_strings(child))
    elif isinstance(value, list):
        for child in value:
            out.extend(walk_source_strings(child))
    elif isinstance(value, str):
        out.append(value)
    return out


def visible_len(template: str) -> int:
    literals, slots = multi.marker_parts(template)
    return sum(len(part) for part in literals) + len(slots)


def longest_unknown_run(template: str) -> int:
    literals, slots = multi.marker_parts(template)
    if not slots:
        return 0
    best = run = 1
    for index in range(1, len(slots)):
        if literals[index] == "":
            run += 1
            best = max(best, run)
        else:
            run = 1
    return best


def trailing_unknown_run(template: str) -> int:
    literals, slots = multi.marker_parts(template)
    if not slots:
        return 0
    run = 0
    for index in range(len(slots) - 1, -1, -1):
        right = literals[index + 1]
        if right != "":
            break
        run += 1
        if literals[index] != "" and index > 0:
            break
    return run


def is_suffix_only(template: str) -> bool:
    """Unknowns are a contiguous prefix; the only known material is a suffix."""
    literals, slots = multi.marker_parts(template)
    if not slots:
        return False
    return all(part == "" for part in literals[:-1]) and literals[-1] != ""


def is_short_exact_shape(template: str, unresolved: set[int]) -> bool:
    stats = multi.anchor_stats(template)
    if stats["visible_len"] > SHORT_EXACT_MAX_LEN:
        return False
    if stats["known_chars"] < 1:
        return False
    if len(unresolved) > SHORT_EXACT_MAX_UNRESOLVED:
        return False
    if is_suffix_only(template):
        return False
    if trailing_unknown_run(template) > SHORT_EXACT_MAX_TRAILING_UNKNOWN:
        return False
    return True


def is_long_exact_shape(template: str) -> bool:
    stats = multi.anchor_stats(template)
    if is_suffix_only(template):
        return False
    if stats["known_chars"] < 3:
        return False
    if stats["known_ratio"] < 0.5:
        return False
    if longest_unknown_run(template) > 2:
        return False
    return True


def unique_mapping(matches: list[dict[str, Any]]) -> dict[int, str] | None:
    if not matches:
        return None
    mappings = {
        tuple(sorted((int(slot), str(char)) for slot, char in match["mapping"].items()))
        for match in matches
    }
    if len(mappings) != 1:
        return None
    return dict(next(iter(mappings)))


def visible_units(template: str) -> list[str]:
    units: list[str] = []
    cursor = 0
    for match in MARKER_TOKEN_RE.finditer(template):
        units.extend(template[cursor : match.start()])
        units.append(match.group(0))
        cursor = match.end()
    units.extend(template[cursor:])
    return units


def span_has_cjk_anchor(template: str) -> bool:
    literals, _slots = multi.marker_parts(template)
    return any(CJK_RE.search(part) for part in literals)


def iter_spans(template: str, target: set[int]) -> list[str]:
    units = visible_units(template)
    out: list[str] = []
    seen: set[str] = set()
    n = len(units)
    for start in range(n):
        for end in range(start + 2, min(n, start + SHORT_EXACT_MAX_LEN) + 1):
            piece = "".join(units[start:end])
            if piece in seen or "¤" not in piece:
                continue
            slots = {int(item, 16) for item in SLOT_MARK_RE.findall(piece)}
            if not (slots & target):
                continue
            if is_suffix_only(piece) or not span_has_cjk_anchor(piece):
                continue
            if trailing_unknown_run(piece) > SHORT_EXACT_MAX_TRAILING_UNKNOWN:
                continue
            if longest_unknown_run(piece) > 2:
                continue
            seen.add(piece)
            out.append(piece)
    return out


def collect_votes(
    template: str,
    unresolved: set[int],
    target: set[int],
    label_by_length: dict[int, list[tuple[str, list[dict[str, str]]]]],
) -> list[dict[str, Any]]:
    """Whole-template exact only. Random interior spans vs dialogue are not exact."""
    del target
    hits: list[dict[str, Any]] = []
    if not is_short_exact_shape(template, unresolved):
        return hits
    matches = [m for m in multi.match_template(template, label_by_length) if m.get("best_tier") == "A"]
    mapping = unique_mapping(matches)
    if mapping is None or set(mapping) != unresolved:
        return hits
    filled = next(match["text"] for match in matches if match["mapping"] == mapping)
    if not is_clean_label(filled) or re.search(r"[！？。…]", filled):
        return hits
    hits.append({
        "mapping": mapping,
        "filled": filled,
        "short_exact": True,
        "span": template,
        "matches": matches,
    })
    return hits


def family_key(text: str) -> str:
    stripped = re.sub(r"[0-9０-９]+$", "", text).strip()
    if "公国" in stripped:
        return "zeon"
    if "連邦" in stripped:
        return "federation"
    if "ザフト" in stripped:
        return "zaft"
    if stripped.startswith("∀") or "ターンエー" in stripped:
        return "turn_a"
    if "ガンダム" in stripped:
        return "gundam_family"
    return stripped[:4] if stripped else text


def build_corpus() -> tuple[dict[int, list[tuple[str, list[dict[str, str]]]]], dict[int, list[tuple[str, list[dict[str, str]]]]], int]:
    by_length: dict[int, list[tuple[str, list[dict[str, str]]]]] = defaultdict(list)
    label_by_length: dict[int, list[tuple[str, list[dict[str, str]]]]] = defaultdict(list)
    seen: dict[str, list[dict[str, str]]] = {}
    seen_label: dict[str, list[dict[str, str]]] = {}

    mapscript = load_json(MAPSCRIPT_DEFAULT)
    for raw in walk_source_strings(mapscript):
        add_corpus(by_length, seen, raw, "legacy/analysis/ggen_advance_map_script_translation_source_20260828.json", "A")
        cleaned = raw.replace("\\n", "").replace("\n", "").strip()
        if 2 <= len(cleaned) <= 16 and not re.search(r"[！？。…]", cleaned):
            add_corpus(
                label_by_length, seen_label, cleaned,
                "legacy/analysis/ggen_advance_map_script_translation_source_20260828.json",
                "A",
                short_only=True,
            )

    if PROD_KO_DEFAULT.exists():
        prod_ko = load_json(PROD_KO_DEFAULT)
        for raw in walk_source_strings(prod_ko):
            add_corpus(by_length, seen, raw, "analysis/_tmp_ko_production.json", "A")
            add_corpus(label_by_length, seen_label, raw, "analysis/_tmp_ko_production.json", "A", short_only=True)

    for text in rebuild.PART_PLAINTEXT.values():
        add_corpus(by_length, seen, text, "tools/rebuild_ggen_advance_japanese_charmap.py#PART_PLAINTEXT", "A")
        add_corpus(label_by_length, seen_label, text, "tools/rebuild_ggen_advance_japanese_charmap.py#PART_PLAINTEXT", "A")
    for text in rebuild.ENTITY_PLAINTEXT.values():
        add_corpus(by_length, seen, text, "tools/rebuild_ggen_advance_japanese_charmap.py#ENTITY_PLAINTEXT", "A")
        add_corpus(label_by_length, seen_label, text, "tools/rebuild_ggen_advance_japanese_charmap.py#ENTITY_PLAINTEXT", "A")
    for text in rebuild.DIRECT_PLAINTEXT.values():
        add_corpus(by_length, seen, text, "tools/rebuild_ggen_advance_japanese_charmap.py#DIRECT_PLAINTEXT", "A")
        add_corpus(label_by_length, seen_label, text, "tools/rebuild_ggen_advance_japanese_charmap.py#DIRECT_PLAINTEXT", "A")

    return dict(by_length), dict(label_by_length), len(seen_label)


def decode_row(source: str, map8: dict[int, str]) -> tuple[str, set[int]]:
    source = CTRL_RE.sub("", source)
    template, unresolved = lang.decode_template(source, map8)
    unresolved = {slot for slot in unresolved if slot not in lang.RESERVED}
    return template.replace("\n", ""), unresolved


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--slices", type=Path, default=SLICES_DEFAULT)
    ap.add_argument("--catalog", type=Path, default=CATALOG_DEFAULT)
    ap.add_argument("--map8", type=Path, default=MAP8_DEFAULT)
    ap.add_argument("--map12", type=Path, default=MAP12_DEFAULT)
    ap.add_argument("--merged", type=Path, default=MERGED_DEFAULT)
    ap.add_argument("--out", type=Path, default=OUT_DEFAULT)
    args = ap.parse_args(argv)
    for path in (args.slices, args.catalog, args.map8, args.map12, args.merged, args.out):
        refuse_outside(path)

    slices = load_json(args.slices)
    target_hex: list[str] = list(slices["agents"][AGENT]["slots"])
    if len(target_hex) != 110:
        raise SystemExit(f"expected 110 short_label_a slots, got {len(target_hex)}")
    target = {int(item, 16) for item in target_hex}
    if target & QUARANTINE:
        raise SystemExit(f"quarantine slot leaked into short_label_a: {target & QUARANTINE}")

    catalog_rows = {item["slot"]: item for item in load_json(args.catalog)["slots"]}
    map8 = lang.load_map(args.map8)
    map12 = load_map12_chars(args.map12)
    viterbi_by_slot: dict[str, str] = {}
    if VITERBI_DEFAULT.exists():
        for item in load_json(VITERBI_DEFAULT).get("candidates", []):
            viterbi_by_slot[str(item.get("slot"))] = str(item.get("char", ""))

    by_length, label_by_length, corpus_count = build_corpus()
    by_length = defaultdict(list, by_length)
    label_by_length = defaultdict(list, label_by_length)
    merged = load_json(args.merged)

    votes: dict[int, Counter[str]] = defaultdict(Counter)
    evidence: dict[int, list[dict[str, Any]]] = defaultdict(list)
    matched_texts: dict[int, set[str]] = defaultdict(set)
    matched_cats: dict[int, set[str]] = defaultdict(set)
    matched_families: dict[int, set[str]] = defaultdict(set)
    short_exact_hits: dict[int, int] = defaultdict(int)
    long_exact_hits: dict[int, int] = defaultdict(int)
    structural_hits: dict[int, int] = defaultdict(int)
    best_anchor: dict[int, dict[str, Any]] = {}
    row_count: dict[int, int] = defaultdict(int)
    conflict_notes: dict[int, list[str]] = defaultdict(list)
    factions_for_space: dict[int, set[str]] = defaultdict(set)

    space_body = re.compile(r"ま¤([0-9A-Fa-f]{4})¤宙¤([0-9A-Fa-f]{4})¤MS")
    space_known = re.compile(r"ま宇宙¤([0-9A-Fa-f]{4})¤(?:MS|¤)")

    def record_vote(
        slot: int,
        char: str,
        *,
        filled: str,
        category: str,
        scope: str,
        row: dict[str, Any],
        template: str,
        stats: dict[str, Any],
        short_exact: bool,
        sources: list[dict[str, str]],
        structural: bool = False,
    ) -> None:
        votes[slot][char] += 1
        matched_texts[slot].add(filled)
        matched_cats[slot].add(category)
        matched_families[slot].add(family_key(filled))
        if structural:
            structural_hits[slot] += 1
        elif short_exact:
            short_exact_hits[slot] += 1
        else:
            long_exact_hits[slot] += 1
        if len(evidence[slot]) < 8:
            evidence[slot].append({
                "record_id": row.get("record_id"),
                "semantic_category": category,
                "scope": scope,
                "template": template,
                "matched_text": filled,
                "char": char,
                "short_exact": short_exact,
                "structural": structural,
                "known_chars": stats["known_chars"],
                "known_ratio": round(stats["known_ratio"], 3),
                "longest_unknown_run": longest_unknown_run(template),
                "sources": sources[:4],
            })

    for row in merged.get("records", []):
        if row.get("translation_status") != "pending" or row.get("translation_policy") != "translate":
            continue
        if str(row.get("semantic_category", "")) in NON_8X16:
            continue
        scope = str(row.get("source_scope", ""))
        if scope not in {"production", "non_scenario_ui"}:
            continue
        source = str(row.get("source_text", ""))
        if not source:
            continue
        template, unresolved = decode_row(source, map8)
        hit = unresolved & target
        if not hit:
            continue
        stats = multi.anchor_stats(template)
        category = str(row.get("semantic_category", ""))
        for slot in hit:
            row_count[slot] += 1
            current = best_anchor.get(slot)
            snapshot = {
                "known_chars": stats["known_chars"],
                "known_ratio": stats["known_ratio"],
                "visible_len": stats["visible_len"],
                "longest_unknown_run": longest_unknown_run(template),
                "unresolved_count": len(unresolved),
                "suffix_only": is_suffix_only(template),
                "template": template,
                "record_id": row.get("record_id"),
                "semantic_category": category,
            }
            if current is None or (
                snapshot["known_chars"],
                -snapshot["longest_unknown_run"],
                snapshot["known_ratio"],
            ) > (
                current["known_chars"],
                -current["longest_unknown_run"],
                current["known_ratio"],
            ):
                best_anchor[slot] = snapshot

        for match in space_body.finditer(template):
            slot_u = int(match.group(1), 16)
            slot_y = int(match.group(2), 16)
            prefix = template[: match.start()]
            faction = prefix[-6:] if len(prefix) >= 6 else prefix
            for slot, char in ((slot_u, "宇"), (slot_y, "用")):
                if slot not in hit:
                    continue
                factions_for_space[slot].add(faction)
                record_vote(
                    slot, char,
                    filled="宇宙用",
                    category=category,
                    scope=scope,
                    row=row,
                    template=template,
                    stats=stats,
                    short_exact=False,
                    sources=[{
                        "path": "legacy/analysis/ggen_advance_map_script_translation_source_20260828.json",
                        "tier": "A",
                        "note": "宇宙用に仕様変更を",
                    }],
                    structural=True,
                )
        for match in space_known.finditer(template):
            slot_y = int(match.group(1), 16)
            if slot_y not in hit:
                continue
            record_vote(
                slot_y, "用",
                filled="宇宙用",
                category=category,
                scope=scope,
                row=row,
                template=template,
                stats=stats,
                short_exact=False,
                sources=[{
                    "path": "legacy/analysis/ggen_advance_map_script_translation_source_20260828.json",
                    "tier": "A",
                    "note": "宇宙用に仕様変更を",
                }],
                structural=True,
            )

        for hit_row in collect_votes(template, unresolved, hit, label_by_length):
            mapping = hit_row["mapping"]
            filled = hit_row["filled"]
            sources = []
            for match in hit_row["matches"]:
                if match["mapping"] == mapping:
                    sources.extend(match["sources"][:3])
            for slot, char in mapping.items():
                if slot not in hit:
                    continue
                record_vote(
                    slot, char,
                    filled=filled,
                    category=category,
                    scope=scope,
                    row=row,
                    template=hit_row["span"],
                    stats=stats,
                    short_exact=bool(hit_row["short_exact"]),
                    sources=[{"path": item["path"], "tier": item["tier"]} for item in sources[:4]],
                    structural=False,
                )
        type_match = re.search(r"ま(?P<body>.+?)(?:MS|MA)", template)
        if type_match:
            body = type_match.group("body")
            body_unresolved = {int(item, 16) for item in SLOT_MARK_RE.findall(body)}
            if body_unresolved & hit:
                for hit_row in collect_votes(body, body_unresolved, hit, label_by_length):
                    mapping = hit_row["mapping"]
                    filled = hit_row["filled"]
                    sources = []
                    for match in hit_row["matches"]:
                        if match["mapping"] == mapping:
                            sources.extend(match["sources"][:3])
                    for slot, char in mapping.items():
                        if slot not in hit:
                            continue
                        record_vote(
                            slot, char,
                            filled=filled,
                            category=category,
                            scope=scope,
                            row=row,
                            template=hit_row["span"],
                            stats=stats,
                            short_exact=bool(hit_row["short_exact"]),
                            sources=[{"path": item["path"], "tier": item["tier"]} for item in sources[:4]],
                            structural=False,
                        )

    slots_out: list[dict[str, Any]] = []
    grade_counts: Counter[str] = Counter()
    for slot_hex in target_hex:
        slot = int(slot_hex, 16)
        cat = catalog_rows[slot_hex]
        counter = votes.get(slot, Counter())
        proposed = ""
        alternates: list[str] = []
        conflicts: list[str] = []
        if len(counter) == 1:
            proposed = next(iter(counter))
        elif len(counter) > 1:
            proposed, _count = counter.most_common(1)[0]
            alternates = [char for char, _n in counter.most_common() if char != proposed]
            conflicts = [f"{char}:{counter[char]}" for char in sorted(counter)]

        texts = matched_texts.get(slot, set())
        cats = matched_cats.get(slot, set())
        families = matched_families.get(slot, set())
        n_texts = len(texts)
        n_cats = len(cats)
        n_families = len(families)
        n_short = short_exact_hits.get(slot, 0)
        n_long = long_exact_hits.get(slot, 0)
        n_struct = structural_hits.get(slot, 0)
        anchor = best_anchor.get(slot, {})
        viterbi = viterbi_by_slot.get(slot_hex, "")
        map12_char = map12.get(slot, "")
        notes: list[str] = []

        if viterbi:
            notes.append(f"Viterbi 참고 {viterbi} (단독 승격 금지)")
            if proposed and viterbi != proposed:
                notes.append("Viterbi와 exact 불일치 → exact 우선")
            if (not proposed) and viterbi:
                notes.append("Viterbi만 있음 → A/B 승격 안 함")
        if map12_char:
            notes.append(f"12x12 동일번호는 {map12_char} (번호 복사 금지, 증거 아님)")
            if proposed and proposed == map12_char:
                notes.append("제안 문자가 12x12 동일번호와 같음 → 우연/복사 위험 표기")
        if proposed:
            dup = [f"0x{other:04X}" for other, char in map8.items() if char == proposed and other != slot]
            if dup:
                notes.append(f"기존 8x16 중복 슬롯 {dup[:3]} (중복 가능, 충돌 아님)")
        if conflict_notes.get(slot):
            conflicts.extend(conflict_notes[slot][:4])

        same_char_closed = bool(proposed) and len(counter) == 1 and not any(
            item.startswith("exact 후보 충돌") for item in conflict_notes.get(slot, [])
        )
        independent = n_texts >= 2 or n_cats >= 2
        one_family = n_families <= 1
        char_conflict = len(counter) > 1

        if char_conflict:
            grade = "C"
            notes.append("서로 다른 문자로 exact 후보가 갈림")
        elif same_char_closed and n_struct > 0 and n_short == 0:
            grade = "B"
            notes.append("생산 지형 접미사 宇宙用 구조 후보 (한 계열, exact 단문 아님)")
            extra_factions = sorted(factions_for_space.get(slot, []))
            if extra_factions:
                notes.append(f"세력 접두 {extra_factions[:6]}")
        elif same_char_closed and n_short > 0 and not independent:
            grade = "A"
            notes.append(f"trusted short-label exact ({n_short}행) 문자 {proposed} 닫힘")
            notes.append(f"문맥 계열 {sorted(families)[:4]}")
        elif same_char_closed and independent:
            grade = "A"
            notes.append(f"독립 문맥 {n_texts}문자열/{n_cats}범주가 {proposed}로 일치")
        elif same_char_closed and n_long > 0 and one_family:
            grade = "B"
            notes.append("강한 라벨 후보지만 한 계열에만 존재")
        elif same_char_closed:
            grade = "B"
            notes.append("유일 후보이지만 문맥 독립성 부족")
        else:
            run = int(anchor.get("longest_unknown_run") or 0)
            known = int(anchor.get("known_chars") or 0)
            if known <= 0 or run >= 3 or anchor.get("suffix_only"):
                grade = "D"
                notes.append("앵커 부족 또는 미지 연속이 길어 exact 불가")
            else:
                grade = "C"
                notes.append("앵커는 있으나 unique exact short-label 없음")

        if slot in QUARANTINE:
            grade = "D"
            notes.append("quarantine 승격 금지")
        if grade == "A" and n_short == 0 and not independent:
            grade = "B"
            notes.append("A 조건 미달로 B 강등")

        promote_ready = grade == "A" and len(counter) == 1 and not char_conflict
        if promote_ready and proposed and proposed == map12_char and n_texts < 2:
            promote_ready = False
            notes.append("12x12 동일번호와 같아 promote_ready 보류")

        grade_counts[grade] += 1
        slots_out.append({
            "slot": slot_hex,
            "grade": grade,
            "proposed_char": proposed,
            "alternate_chars": alternates,
            "pending_records": cat.get("pending_records", row_count.get(slot, 0)),
            "hold_reason": cat.get("hold_reason", ""),
            "evidence": evidence.get(slot, []),
            "conflicts": conflicts,
            "promote_ready": promote_ready,
            "notes": " / ".join(notes),
            "semantic_categories": cat.get("semantic_categories", {}),
            "short_label_hits": cat.get("short_label_hits", 0),
            "bucket": cat.get("bucket", ""),
            "exact_matched_texts": sorted(texts)[:8],
            "independent_text_count": n_texts,
            "independent_category_count": n_cats,
            "short_exact_rows": n_short,
            "long_exact_rows": n_long,
            "best_anchor": {
                key: anchor[key]
                for key in (
                    "known_chars",
                    "known_ratio",
                    "visible_len",
                    "longest_unknown_run",
                    "unresolved_count",
                    "suffix_only",
                    "template",
                    "record_id",
                    "semantic_category",
                )
                if key in anchor
            },
            "scanned_rows": row_count.get(slot, 0),
        })

    payload = {
        "schema_version": 1,
        "agent": AGENT,
        "slot_count": 110,
        "analyzed_count": len(slots_out),
        "grades": {
            "A": grade_counts["A"],
            "B": grade_counts["B"],
            "C": grade_counts["C"],
            "D": grade_counts["D"],
        },
        "promote_ready_count": sum(1 for item in slots_out if item["promote_ready"]),
        "trusted_corpus_unique_strings": corpus_count,
        "method": "trusted same-ROM exact short-label alignment with known 8x16 anchors",
        "notes": [
            "Analysis only; charmap/source/ROM were not modified.",
            "configuration_option_text excluded (12x12).",
            "suffix-only unique candidates are not exact.",
            "Viterbi is note-only and never promotes to A.",
            "12x12 same slot numbers are never copied.",
            "quarantine 5 slots are not in this slice.",
            "Grade A requires 2+ independent contexts or trusted exact short-label closing one character.",
            "promote_ready is true only for grade A with zero character conflicts.",
        ],
        "slots": slots_out,
    }
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {
        "out": str(args.out.relative_to(ROOT)),
        "analyzed_count": payload["analyzed_count"],
        "grades": payload["grades"],
        "promote_ready_count": payload["promote_ready_count"],
        "A": [
            {"slot": item["slot"], "char": item["proposed_char"], "texts": item["exact_matched_texts"][:4]}
            for item in slots_out if item["grade"] == "A"
        ],
        "B": [
            {"slot": item["slot"], "char": item["proposed_char"], "texts": item["exact_matched_texts"][:3]}
            for item in slots_out if item["grade"] == "B"
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
