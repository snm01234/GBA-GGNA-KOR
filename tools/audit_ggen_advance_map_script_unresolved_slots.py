#!/usr/bin/env python3
"""Audit the 326 unresolved map-script rows without mutating the charmap.

The exact 12x12 matcher is deliberately treated as a probe, not as an
automatic promotion source.  A bitmap can be an exact match for a different
character (especially when the same glyph is already used elsewhere), so this
report joins three independent pieces of evidence:

* all scenario/map-script records that are still partial;
* the system-font exact-match probe; and
* a small, explicitly labelled set of phrase-context candidates reviewed from
  the full map-script corpus.

The output is an audit/queue for the next review pass.  It never writes the
identified charmap or a ROM.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MERGED = ROOT / "analysis" / "ggen_advance_translation_merged_20260828.json"
DEFAULT_SOURCE = ROOT / "analysis" / "ggen_advance_map_script_translation_source_20260828.json"
DEFAULT_CHARMAP = ROOT / "analysis" / "ggen_advance_12x12_identified_charmap_20260828.json"
DEFAULT_PROBE = ROOT / "analysis" / "ggen_advance_map_script_unresolved_exact_probe_20260828.json"
DEFAULT_OUTPUT = ROOT / "analysis" / "ggen_advance_map_script_unresolved_slot_audit_20260828.json"


# These are phrase-context readings, not promotions.  They are restricted to
# strings whose surrounding words make the reading stable across the corpus.
# Keeping them in the audit makes the human judgement visible and reproducible
# while still requiring a later explicit charmap-promotion step.
CONTEXT_CANDIDATES: dict[str, tuple[str, str]] = {
    "0x00E5": ("―", "high"),
    "0x00FD": ("6", "high"),
    "0x0109": ("周", "high"),
    "0x012D": ("ぴ", "high"),
    "0x0135": ("ょ", "high"),
    "0x0154": ("偉", "high"),
    "0x015A": ("様", "high"),
    "0x0161": ("勤", "high"),
    "0x0178": ("用", "high"),
    "0x018A": ("縁", "high"),
    "0x0193": ("宇", "high"),
    "0x01AE": ("現", "high"),
    "0x01AF": ("荷", "high"),
    "0x01CB": ("口", "high"),
    "0x01CD": ("骸", "high"),
    "0x01D4": ("入", "high"),
    "0x01E3": ("刈", "high"),
    "0x01E6": ("夢", "high"),
    "0x01E8": ("勧", "high"),
    "0x01F1": ("念", "high"),
    "0x01F4": ("歓", "high"),
    "0x01FB": ("緩", "high"),
    "0x0214": ("忌", "high"),
    "0x021C": ("知", "high"),
    "0x025A": ("挟", "high"),
    "0x026E": ("禁", "high"),
    "0x026F": ("筋", "high"),
    "0x0270": ("緊", "high"),
    "0x0289": ("方", "high"),
    "0x028F": ("恵", "high"),
    "0x0291": ("敬", "high"),
    "0x02B1": ("抑", "high"),
    "0x02BF": ("幻", "high"),
    "0x02CD": ("股", "high"),
    "0x02D2": ("2", "high"),
    "0x02D4": ("艦", "high"),
    "0x020F": ("大", "high"),
    "0x02E6": ("喉", "high"),
    "0x02EF": ("拘", "high"),
    "0x02F1": ("違", "high"),
    "0x0306": ("克", "high"),
    "0x0309": ("酷", "high"),
    "0x0315": ("害", "high"),
    "0x0319": ("僅", "high"),
    "0x031D": ("査", "high"),
    "0x0337": ("動", "high"),
    "0x033A": ("削", "high"),
    "0x033F": ("拶", "high"),
    "0x0340": ("擦", "high"),
    "0x034A": ("賛", "high"),
    "0x034B": ("唾", "high"),
    "0x0357": ("屍", "high"),
    "0x0362": ("紙", "high"),
    "0x0364": ("至", "high"),
    "0x036A": ("飼", "high"),
    "0x036F": ("慈", "high"),
    "0x0373": ("磁", "high"),
    "0x037B": ("七", "high"),
    "0x037E": ("室", "high"),
    "0x0388": ("当", "high"),
    "0x038D": ("説", "high"),
    "0x039C": ("宙", "high"),
    "0x03AB": ("充", "high"),
    "0x03B9": ("准", "high"),
    "0x03BE": ("順", "high"),
    "0x03C3": ("署", "high"),
    "0x03C8": ("牲", "high"),
    "0x03CD": ("召", "high"),
    "0x03D8": ("把", "high"),
    "0x03DC": ("期", "high"),
    "0x03E7": ("衝", "high"),
    "0x03F9": ("植", "high"),
    "0x0401": ("伸", "high"),
    "0x0410": ("親", "high"),
    "0x0415": ("震", "high"),
    "0x042C": ("澄", "high"),
    "0x042D": ("寸", "high"),
    "0x044A": ("撃", "high"),
    "0x0451": ("力", "high"),
    "0x0457": ("折", "high"),
    "0x0458": ("設", "high"),
    "0x046E": ("探", "high"),
    "0x0471": ("善", "high"),
    "0x0473": ("措", "high"),
    "0x047B": ("僧", "high"),
    "0x048B": ("聡", "high"),
    "0x0491": ("騒", "high"),
    "0x04A2": ("賊", "high"),
    "0x04A7": ("孫", "high"),
    "0x04C5": ("托", "high"),
    "0x04D1": ("嘆", "high"),
    "0x04DC": ("壇", "high"),
    "0x04DE": ("暖", "high"),
    "0x04F8": ("貯", "high"),
    "0x04FA": ("兆", "high"),
    "0x04FD": ("殴", "high"),
    "0x0502": ("め", "high"),
    "0x0505": ("聴", "high"),
    "0x050B": ("御", "high"),
    "0x0520": ("姿", "high"),
    "0x0526": ("隊", "high"),
    "0x0528": ("長", "high"),
    "0x052B": ("優", "high"),
    "0x0539": ("殿", "high"),
    "0x04ED": ("犠", "high"),
    "0x0550": ("盗", "high"),
    "0x055C": ("働", "high"),
    "0x0572": ("縄", "medium"),
    "0x0581": ("人", "medium"),
    "0x058A": ("波", "medium"),
    "0x058F": ("拝", "high"),
    "0x0599": ("剥", "high"),
    "0x059B": ("拍", "high"),
    "0x0596": ("倍", "high"),
    "0x05A2": ("縛", "high"),
    "0x05B4": ("煩", "high"),
    "0x05CC": ("連", "high"),
    "0x05C3": ("疲", "high"),
    "0x05E1": ("婦", "high"),
    "0x05F8": ("服", "high"),
    "0x0608": ("柄", "high"),
    "0x060A": ("閉", "high"),
    "0x0621": ("避", "high"),
    "0x0625": ("抱", "high"),
    "0x062C": ("訪", "high"),
    "0x0634": ("忙", "high"),
    "0x0642": ("摩", "high"),
    "0x0649": ("毎", "high"),
    "0x064B": ("間", "medium"),
    "0x0655": ("脈", "high"),
    "0x0657": ("民", "high"),
    "0x0664": ("妄", "high"),
    "0x0667": ("網", "high"),
    "0x0670": ("幕", "high"),
    "0x0676": ("薬", "high"),
    "0x067D": ("唯", "high"),
    "0x0683": ("幽", "high"),
    "0x0687": ("裕", "high"),
    "0x0691": ("和", "high"),
    "0x0692": ("揺", "high"),
    "0x069C": ("翼", "high"),
    "0x06A2": ("波", "medium"),
    "0x06BA": ("瞭", "high"),
    # The phrase is 特定のキャラクター同士が<06C0>接した時, so the
    # unresolved slot is 隣 (the following literal 接 is already present).
    "0x06C0": ("隣", "high"),
    "0x06C9": ("き", "high"),
    "0x06CE": ("裂", "high"),
    "0x06D0": ("誰", "medium"),
    "0x06D1": ("憐", "high"),
    "0x06D6": ("露", "high"),
    "0x06E2": ("汲", "high"),
    "0x06EA": ("嗅", "high"),
    "0x06F7": ("舐", "high"),
    "0x06FA": ("贖", "high"),
    "0x06FB": ("踪", "high"),
    "0x0703": ("擁", "high"),
    "0x0704": ("融", "high"),
    "0x0705": ("征", "high"),
    "0x0709": ("八", "high"),
    "0x070A": ("湧", "high"),
    "0x0710": ("憎", "high"),
    "0x0711": ("轍", "high"),
    "0x0714": ("牌", "high"),
    "0x0715": ("い", "high"),
    "0x0716": ("購", "high"),
    "0x07A2": ("ぽ", "high"),
    "0x07AF": ("廷", "high"),
    "0x0789": ("録", "high"),
    "0x079C": ("灯", "high"),
    "0x07A4": ("怯", "high"),
    "0x07A5": ("勤", "high"),
    "0x07A8": ("侍", "high"),
    "0x07AA": ("倉", "high"),
    "0x07AC": ("卑", "high"),
}


# These slots have an internally competing phrase reading or a known
# neighbouring-slot collision.  They stay in the hold queue even when the
# bitmap probe returns a candidate.
HOLD_NOTES: dict[str, str] = {
    "0x020F": "paired context strongly suggests 大 (大嫌な/大きな), but the first source phrase omits い and needs a source check",
    "0x0225": "phrase is emotionally clear but the exact kanji is not (…子だわ)",
    "0x0360": "dialogue contains a proper-name/kinship phrase requiring source check",
    "0x03B7": "青<slot>してて is not a stable lexical reading",
    "0x0373": "電<slot><058A>/<06A2> may be electromagnetic terms; pair must be checked",
    "0x058A": "must be paired with 0x0373 and 0x06A2 before promotion",
    "0x0585": "納得/収める readings compete across two phrases",
    "0x065C": "proper-name and 小<slot> contexts compete",
    "0x06A2": "must be paired with 0x0373 and 0x058A before promotion",
    "0x06C9": "paired context strongly suggests き (大きな声) with 0x020F=大; verify the unusual neighbouring source phrase",
}


# A pre-existing mapping error can make an otherwise good unresolved-slot
# reading look nonsensical.  This is kept separate from the 177-slot queue so
# it cannot be mistaken for a new promotion.  0x03C7's atlas bitmap is 女;
# the current charmap's 壁 came from an earlier scenario promotion, while the
# map-script corpus repeatedly requires 女王/彼女/女性/少女/侍女.  0x060D is
# the separate 壁 slot.
KNOWN_CHARMAP_CONTEXT_FLAGS: dict[str, dict[str, str]] = {
    "0x0046": {
        "current_charmap": "ふ",
        "context_reading": "べ",
        "basis": "low-kana corpus repeatedly forms 比べて/すべく/選べる/選べない/調べて/しかるべき; 0x012E is the separate ふ slot",
        "action": "repair_charmap_before_final_map_script_translation",
    },
    "0x0200": {
        "current_charmap": "堕",
        "context_reading": "還",
        "basis": "full map-script corpus repeatedly forms 奪還/生還/帰還; current 堕 makes all three compounds malformed",
        "action": "repair_charmap_before_final_map_script_translation",
    },
    "0x0186": {
        "current_charmap": "遺",
        "context_reading": "怨",
        "basis": "the four uses form 怨恨/怨み/私怨; 遺伝子 is carried by the separate 0x0160 遺 slot",
        "action": "repair_charmap_before_final_map_script_translation",
    },
    "0x0237": {
        "current_charmap": "益",
        "context_reading": "久",
        "basis": "all eight uses form 久々/久しぶり/永久; current 益 makes those phrases malformed",
        "action": "repair_charmap_before_final_map_script_translation",
    },
    "0x023C": {
        "current_charmap": "棺",
        "context_reading": "宮",
        "basis": "the three uses form 宮殿/子宮; the separate 0x01F3 slot carries 棺",
        "action": "repair_charmap_before_final_map_script_translation",
    },
    "0x027A": {
        "current_charmap": "弱",
        "context_reading": "馬",
        "basis": "eleven uses read as 馬鹿者/馬鹿な, while the separate 0x038F slot carries 弱 in 弱者/軟弱者; atlas/source composite behavior should be checked before repair",
        "action": "hold_for_source_or_glyph_verification",
    },
    "0x0492": {
        "current_charmap": "党",
        "context_reading": "像",
        "basis": "the two uses form 想像もつかない/想像以上; 残党 and 悪党 use the separate 0x0548 党 slot",
        "action": "repair_charmap_before_final_map_script_translation",
    },
    "0x03C7": {
        "current_charmap": "壁",
        "context_reading": "女",
        "basis": "full map-script corpus uses this slot in 女王/彼女/女性/少女/侍女 contexts; atlas strip distinguishes it from 0x060D 壁",
        "action": "repair_charmap_before_final_map_script_translation",
    },
    "0x03B0": {
        "current_charmap": "全",
        "context_reading": "銃",
        "basis": "three map-script lines form 銃を向ける/銃を撃って; current 全 is a clear context mismatch",
        "action": "repair_charmap_before_final_map_script_translation",
    },
    "0x04E7": {
        "current_charmap": "捨",
        "context_reading": "置",
        "basis": "full map-script corpus repeatedly forms 放置/配置/位置/処置/装置/自爆装置/置いて; atlas strip separates this glyph from the true 捨 slot 0x0383",
        "action": "repair_charmap_before_final_map_script_translation",
    },
    "0x03AB": {
        "current_charmap": "十",
        "context_reading": "充",
        "basis": "all ten map-script uses form 補充/充実/補充兵 compounds; the denser glyph differs from the known 給 slot 0x0244",
        "action": "repair_charmap_before_final_map_script_translation",
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--merged", type=Path, default=DEFAULT_MERGED)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--charmap", type=Path, default=DEFAULT_CHARMAP)
    parser.add_argument("--probe", type=Path, default=DEFAULT_PROBE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def slot_int(slot: str) -> int:
    return int(str(slot), 16)


def slot_label(slot: int) -> str:
    return f"0x{slot:04X}"


def normalize_slot(raw: Any) -> str:
    return slot_label(slot_int(str(raw)))


def main() -> None:
    args = parse_args()
    merged = load_json(args.merged)
    source = load_json(args.source)
    charmap_payload = load_json(args.charmap)
    probe = load_json(args.probe)
    charmap: dict[str, str] = charmap_payload.get("verified_charmap", {})
    char_to_slots: dict[str, list[str]] = defaultdict(list)
    for raw_slot, char in charmap.items():
        char_to_slots[str(char)].append(normalize_slot(raw_slot))

    exact_by_slot: dict[str, dict[str, Any]] = {}
    for item in probe.get("inferred", []):
        exact_by_slot[normalize_slot(item["slot"])] = {
            "char": str(item["char"]),
            "evidence": list(item.get("evidence") or []),
        }

    source_by_id = {
        str(row.get("record_id")): row
        for row in source.get("records", [])
        if row.get("record_id")
    }

    records: list[dict[str, Any]] = []
    by_slot: dict[str, list[dict[str, Any]]] = defaultdict(list)
    slot_occurrences: Counter[str] = Counter()
    control_signature_counts: Counter[str] = Counter()
    speaker_ids: set[str] = set()
    line_break_count_total = 0
    dynamic_control_count_total = 0
    known_flag_usage: dict[str, dict[str, Any]] = {
        slot: {
            "record_ids": set(),
            "occurrences": 0,
            "partial_record_ids": set(),
            "partial_occurrences": 0,
            "source_texts": [],
        }
        for slot in KNOWN_CHARMAP_CONTEXT_FLAGS
    }
    for row in merged.get("records", []):
        if row.get("source_scope") != "scenario_map_script":
            continue
        source_row = source_by_id.get(str(row.get("record_id")), {})
        source_segments = source_row.get("segments") or row.get("segments") or []
        row_slots_all = [
            normalize_slot(raw_slot)
            for segment in source_segments
            for raw_slot in segment.get("slots") or []
        ]
        for flagged_slot in KNOWN_CHARMAP_CONTEXT_FLAGS:
            count = row_slots_all.count(flagged_slot)
            if count:
                usage = known_flag_usage[flagged_slot]
                usage["record_ids"].add(str(row.get("record_id", "")))
                usage["occurrences"] += count
                if len(usage["source_texts"]) < 12:
                    usage["source_texts"].append(str(row.get("source_text", "")))
        if row.get("source_decode_status") != "partial":
            continue
        if not row.get("source_unresolved_slots"):
            continue
        records.append(row)
        for flagged_slot in KNOWN_CHARMAP_CONTEXT_FLAGS:
            count = row_slots_all.count(flagged_slot)
            if count:
                usage = known_flag_usage[flagged_slot]
                usage["partial_record_ids"].add(str(row.get("record_id", "")))
                usage["partial_occurrences"] += count
        signature = ",".join(str(item.get("code", "")) for item in row.get("control_signature") or [])
        control_signature_counts[signature] += 1
        speaker_ids.add(str(row.get("speaker_id", "")))
        line_break_count_total += int(row.get("line_break_count") or 0)
        dynamic_control_count_total += int(row.get("dynamic_control_count") or 0)
        unresolved = {normalize_slot(raw) for raw in row.get("source_unresolved_slots", [])}
        seen_in_row: set[str] = set()
        source_row = source_by_id.get(str(row.get("record_id")), {})
        source_segments = source_row.get("segments") or row.get("segments") or []
        for segment in source_segments:
            for raw_slot in segment.get("slots") or []:
                normalized = normalize_slot(raw_slot)
                if normalized in unresolved:
                    slot_occurrences[normalized] += 1
                    seen_in_row.add(normalized)
        # A malformed/legacy row may not carry segment slots.  Keep the row
        # visible and count one occurrence rather than silently dropping it.
        for normalized in unresolved - seen_in_row:
            slot_occurrences[normalized] += 1
        for normalized in unresolved:
            by_slot[normalized].append(row)

    slot_audit: list[dict[str, Any]] = []
    classification_counts: Counter[str] = Counter()
    classification_occurrences: Counter[str] = Counter()
    for raw_slot in sorted(by_slot, key=slot_int):
        exact = exact_by_slot.get(raw_slot)
        context = CONTEXT_CANDIDATES.get(raw_slot)
        hold_note = HOLD_NOTES.get(raw_slot)
        exact_char = exact.get("char") if exact else None
        context_char = context[0] if context else None
        if hold_note:
            classification = "hold_context_or_slot_collision"
            action = "manual_review_required"
        elif exact_char and context_char and exact_char == context_char:
            classification = "context_and_glyph_agree"
            action = "eligible_for_curated_promotion_review"
        elif exact_char and context_char:
            classification = "context_vs_glyph_conflict"
            action = "do_not_promote_until_resolved"
        elif context_char:
            classification = "context_only_candidate"
            action = "manual_glyph_check_then_curated_review"
        elif exact_char:
            classification = "glyph_exact_needs_context_review"
            action = "manual_context_review_required"
        else:
            classification = "no_candidate"
            action = "new_context_or_bitmap_analysis_required"
        classification_counts[classification] += 1
        classification_occurrences[classification] += slot_occurrences[raw_slot]

        char_slots = []
        if exact_char:
            char_slots = sorted(set(char_to_slots.get(exact_char, [])), key=slot_int)
        row_items = sorted(by_slot[raw_slot], key=lambda item: int(str(item.get("target_file_offset", "0")), 16))
        slot_audit.append(
            {
                "slot": raw_slot,
                "occurrences": int(slot_occurrences[raw_slot]),
                "record_count": len(row_items),
                "record_ids": [str(item["record_id"]) for item in row_items],
                "source_texts": [str(item.get("source_text", "")) for item in row_items],
                "glyph_exact_candidate": exact,
                "glyph_exact_candidate_existing_slots": char_slots,
                "context_candidate": (
                    {"char": context_char, "confidence": context[1], "basis": "curated phrase context"}
                    if context
                    else None
                ),
                "hold_note": hold_note,
                "known_charmap_context_flag": KNOWN_CHARMAP_CONTEXT_FLAGS.get(raw_slot),
                "classification": classification,
                "recommended_action": action,
                "current_charmap_contains_slot": raw_slot in charmap,
            }
        )

    recommended = [
        item["slot"]
        for item in slot_audit
        if item["classification"] == "context_and_glyph_agree"
    ]
    context_only = [
        item["slot"]
        for item in slot_audit
        if item["classification"] == "context_only_candidate"
    ]
    conflicts = [
        item["slot"]
        for item in slot_audit
        if item["classification"] in {"context_vs_glyph_conflict", "hold_context_or_slot_collision"}
    ]
    exact_with_existing_char = sum(
        1
        for item in slot_audit
        if item["glyph_exact_candidate"] and item["glyph_exact_candidate_existing_slots"]
    )
    class_by_slot = {item["slot"]: item["classification"] for item in slot_audit}
    rows_all_agree = 0
    rows_all_context = 0
    rows_with_hold_or_conflict = 0
    rows_without_any_candidate = 0
    for row in records:
        row_slots = {normalize_slot(raw) for raw in row.get("source_unresolved_slots", [])}
        row_classes = {class_by_slot.get(slot, "no_candidate") for slot in row_slots}
        if row_classes and row_classes <= {"context_and_glyph_agree"}:
            rows_all_agree += 1
        if row_classes and row_classes <= {
            "context_and_glyph_agree",
            "context_only_candidate",
        }:
            rows_all_context += 1
        if row_classes & {"context_vs_glyph_conflict", "hold_context_or_slot_collision"}:
            rows_with_hold_or_conflict += 1
        if not row_classes or row_classes == {"no_candidate"}:
            rows_without_any_candidate += 1

    row_review_queue: list[dict[str, Any]] = []
    for row in sorted(records, key=lambda item: int(str(item.get("target_file_offset", "0")), 16)):
        row_slots = sorted(
            {normalize_slot(raw) for raw in row.get("source_unresolved_slots", [])},
            key=slot_int,
        )
        row_classes = [class_by_slot.get(slot, "no_candidate") for slot in row_slots]
        if any(value in {"context_vs_glyph_conflict", "hold_context_or_slot_collision"} for value in row_classes):
            row_action = "hold_for_slot_or_phrase_conflict"
        elif all(value == "context_and_glyph_agree" for value in row_classes):
            row_action = "ready_for_curated_translation_batch_review"
        else:
            row_action = "needs_context_candidate_review_before_translation"
        row_review_queue.append(
            {
                "record_id": str(row["record_id"]),
                "target_file_offset": str(row.get("target_file_offset", "")),
                "source_text": str(row.get("source_text", "")),
                "unresolved_slots": row_slots,
                "slot_classifications": dict(zip(row_slots, row_classes)),
                "action": row_action,
            }
        )

    output = {
        "schema_version": "ggen_advance.map_script_unresolved_slot_audit.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "method": {
            "scope": "scenario_map_script",
            "partial_record_filter": "source_decode_status == partial",
            "glyph_probe": str(args.probe),
            "context_candidates_are_promotions": False,
            "note": "Exact bitmap matches are probes only; no charmap or ROM is modified.",
        },
        "inputs": {
            "merged": str(args.merged),
            "charmap": str(args.charmap),
            "source": str(args.source),
            "probe": str(args.probe),
        },
        "summary": {
            "partial_records": len(records),
            "unique_unresolved_slots": len(slot_audit),
            "unresolved_occurrences": int(sum(slot_occurrences.values())),
            "probe_inferred_slots": len(exact_by_slot),
            "probe_rejected_ambiguous_or_used": int((probe.get("rejected") or {}).get("ambiguous_or_used", 0)),
            "probe_no_exact_match": int((probe.get("rejected") or {}).get("no_exact_match", 0)),
            "probe_exact_candidates_already_in_charmap": exact_with_existing_char,
            "probe_exact_candidates_not_in_charmap": len(exact_by_slot) - exact_with_existing_char,
            "context_candidate_slots": sum(1 for item in slot_audit if item["context_candidate"]),
            "known_charmap_context_flags": len(KNOWN_CHARMAP_CONTEXT_FLAGS),
            "rows_fully_covered_by_context_and_glyph_agree": rows_all_agree,
            "rows_fully_covered_by_non_hold_context_candidates": rows_all_context,
            "rows_containing_conflict_or_hold_slot": rows_with_hold_or_conflict,
            "rows_without_any_candidate": rows_without_any_candidate,
            "control_signature_counts": dict(control_signature_counts),
            "line_break_count_total": line_break_count_total,
            "dynamic_control_count_total": dynamic_control_count_total,
            "speaker_id_count_including_empty": len(speaker_ids),
            "classification_counts": dict(classification_counts),
            "classification_occurrence_counts": dict(classification_occurrences),
            "recommended_context_and_glyph_agree_slots": len(recommended),
            "context_only_slots": len(context_only),
            "conflict_or_hold_slots": len(conflicts),
        },
        "next_review_queue": {
            "first": recommended,
            "context_only_after_glyph_check": context_only,
            "hold_or_conflict": conflicts,
            "no_candidate": [item["slot"] for item in slot_audit if item["classification"] == "no_candidate"],
        },
        "known_charmap_context_flags": {
            slot: {
                **flag,
                "usage": {
                    "record_count": len(known_flag_usage[slot]["record_ids"]),
                    "occurrences": known_flag_usage[slot]["occurrences"],
                    "partial_record_count": len(known_flag_usage[slot]["partial_record_ids"]),
                    "partial_occurrences": known_flag_usage[slot]["partial_occurrences"],
                    "source_texts": known_flag_usage[slot]["source_texts"],
                },
            }
            for slot, flag in KNOWN_CHARMAP_CONTEXT_FLAGS.items()
        },
        "row_review_queue": row_review_queue,
        "slot_audit": slot_audit,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output["summary"], ensure_ascii=False, indent=2))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
