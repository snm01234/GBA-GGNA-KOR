#!/usr/bin/env python3
"""Apply the unified translation sheet onto a 32 MiB G Generation Advance PoC ROM.

Ready Korean rows from the merged overlay are relocated into the appended text
region, Hangul glyphs are painted from the canonical native BDF pair (Galmuri11
12x12, Galmuri11-Condensed 8x16) onto slots that remaining Japanese text does
not still consume.  Bold TTF and Galmuri7 row-stretch are not used.

The 20260825 Korean charmap plan and the immutable unified source are read-only.
This builder writes a derived apply-charmap, a 32 MiB ROM, and a manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from zipfile import ZipFile

THIS_DIR = Path(__file__).resolve().parent
ADVANCE_DIR = THIS_DIR.parent
for path in (THIS_DIR,):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import build_ggen_advance_ko_poc as fontops  # noqa: E402
import build_ggen_advance_translation_font_poc as fontpoc  # noqa: E402
import build_ggen_advance_translation_master as translation  # noqa: E402
import build_stage2_translation_master as stage2  # noqa: E402
import ggen_advance_32m_layout as layout  # noqa: E402
import test_ggen_advance_font_pair as fontpair  # noqa: E402
from ggen_advance_text_codec import (  # noqa: E402
    DICT_12X12_BASE,
    DICT_12X12_END,
    DICT_8X16_BASE,
    DICT_8X16_END,
    expand_to_slots,
    load_dictionary,
)
from patch_ggen_advance_map_script_inline_poc import (  # noqa: E402
    CHAR_ALIASES,
    apply_map_script_inline_hooks,
    hook_allowed_offsets,
)
from ggen_advance_project_paths import (  # noqa: E402
    FONT_ZIP,
    TRANSLATION_MERGED_JSON,
)


ROM_BASE = 0x08000000
EXPANDED_SIZE = 32 * 1024 * 1024
TEXT_START = translation.TEXT_START
TEXT_END = translation.TEXT_END
EXPECTED_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"
STRONG_TAIL = fontpoc.STRONG_TAIL
FONT8_LITERAL_FILE = fontpoc.FONT8_LITERAL_FILE
FONT12_LITERAL_FILE = fontpoc.FONT12_LITERAL_FILE
ORIGINAL_FONT8_ADDRESS = fontpoc.ORIGINAL_FONT8_ADDRESS
ORIGINAL_FONT12_ADDRESS = fontpoc.ORIGINAL_FONT12_ADDRESS

READY = {"translated"}
RESERVED_GLYPH_SLOTS = {0x07F8, 0x07FB, 0x07FC, 0x07FD, 0x07FE, 0x0813}
SLOT_MIN, SLOT_MAX = 0x00E0, 0x07C7
# The renderer accepts literal tokens through E733 (slot 0x0813).  The
# narrower SLOT_MAX above is only the shared Hangul allocation domain; reviewed
# compatibility/special glyphs may legitimately use the remaining slots.
MAX_LITERAL_SLOT = 0x0813
# Original game glyphs reused by the Korean sheet.  Hangul must not occupy them.
SPECIAL_CHAR_TOKENS: dict[str, int] = {
    "＠": 0xE641,  # slot 0x0721, bark padding
    "∀": 0xE6FC,  # slot 0x07DC
    "γ": 0xE6FB,  # slot 0x07DB
    "ν": 0xE063,  # slot 0x0143, 12x12 Nu Gundam; Hangul must not occupy it
    "↑": 0xE711,  # slot 0x07F1
    "↓": 0xE710,  # slot 0x07F0
}
SPECIAL_SLOTS = {
    token - 0xDF20
    for token in SPECIAL_CHAR_TOKENS.values()
    if token >= 0xE000
}
# Korean 12x12 font: native dash slot 0x00E5 is occupied by 값 in the
# promoted font. Keep a separate copy; do not overwrite the Hangul glyph.
KOREAN12_GLYPH_COPIES = {0x07B9: 0x00E5}
SPECIAL_SLOTS.update(KOREAN12_GLYPH_COPIES)
SKIP_EXTRA_OWNER_SCHEMAS = {
    "length_prefixed_pair_fallback",
    "length_prefixed_pair_override",
    "double_nul_list",
    "relative_block_base_literal",
    "relative_pair_block",
}
PLAN_PATH = ADVANCE_DIR / "font_tables" / "ggen_advance_korean_charmap_plan_20260825.json"
MERGED_PATH = TRANSLATION_MERGED_JSON
CHARMAP_8X16_PATH = ADVANCE_DIR / "analysis" / "ggen_advance_8x16_charmap_supplement_20260828.json"
CHARMAP_12X12_PATH = ADVANCE_DIR / "analysis" / "ggen_advance_12x12_identified_charmap_20260828.json"
ID_BARK_OVERLAY_PATH = ADVANCE_DIR / "integrated" / "translation" / "ggen_advance_id_command_battle_barks.json"
ID_BARK_EXTRACT_PATH = ADVANCE_DIR / "legacy" / "analysis" / "ggen_advance_id_command_battle_barks_20260830.json"
ID_BARK_PAYLOAD_START = 0x002231B4
ID_BARK_TABLE_START = 0x00226984
ID_BARK_TABLE_END = ID_BARK_TABLE_START + 768 * 8
CANONICAL_FONT12_MEMBER = "Galmuri11.bdf"
CANONICAL_FONT8_MEMBER = "Galmuri11-Condensed.bdf"

SCENARIO_12X12_SCOPES = {
    "scenario_main",
    "scenario_dynamic",
    "scenario_map_script",
    "id_command_battle_bark",
    "battle_event_dialogue",
}
# Renderer-proven: fixed16/fixed40 option matrices dispatch bit0=1 → 12x12.
# table_1C92E8 cinematic lines also enter 0x08000CA0 with 12x12 tokens.
# ID-command body text and some direct-PC dialogs enter 0x08000CA0 as 12x12.
# Names/effect summaries on the same screen stay 8x16.
UI_12X12_CATEGORIES = {
    "configuration_option_text",
    "scripted_multiline_text",
    "id_command_description",
    "two_choice_confirmation_dialog_text",
    # Intermission help and development/refit dialogue are drawn through the
    # same 12x12 renderer despite their older static-analysis category names.
    "map_system_function_help",
    "stage_battle_condition_target_label",
    # Yellow-window parallel condition bodies (FCE1A0) are 12x12; 8x16 decode
    # left them pending with Japanese still on-screen.
    "stage_battle_condition_text",
}
UI_12X12_RECORD_IDS = {
    "GGA-TEXT-001BE7B4",  # ID説明なし (8x16 decode is noise)
}


def uses_12x12(row: dict[str, Any]) -> bool:
    if str(row.get("source_scope") or "") in SCENARIO_12X12_SCOPES:
        return True
    if str(row.get("record_id") or "") in UI_12X12_RECORD_IDS:
        return True
    return str(row.get("semantic_category") or "") in UI_12X12_CATEGORIES

# ASCII spellings used by the translation sheets must be resolved through the
# target font's reviewed Unicode→slot map.  In particular, the 12×12 map has
# punctuation in slots 0x02/0x04/0x05/0x07; treating ASCII codepoints as slots
# produces the visible kana leak reported in the battle dialogue.
ENCODER_CHAR_ALIASES = dict(CHAR_ALIASES)
ENCODER_CHAR_ALIASES["—"] = "－"
ENCODER_CHAR_ALIASES["─"] = "－"
ENCODER_CHAR_ALIASES["·"] = "・"
ENCODER_CHAR_ALIASES["＋"] = "+"
PUNCTUATION_CHARS = frozenset(
    "!?,.;:-_~…、。・·ー—－～！？「」『』（）％／"
)

def sha256(value: bytes | bytearray) -> str:
    return hashlib.sha256(value).hexdigest()


def gate(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"gate failed: {message}")


def parse_hex(value: str) -> int:
    return int(value, 16)


def u32(data: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def load_verified_charmap(path: Path) -> dict[str, int]:
    """Load a reviewed font-mode Unicode→slot map.

    The JSON files are stored slot→Unicode because that is also the useful
    representation for glyph audits.  Encoding needs the reverse direction;
    when a Unicode character has aliases/duplicate slots, the lowest reviewed
    slot is deterministic and matches the map-script encoder policy.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    result: dict[str, int] = {}
    for slot_text, char in payload.get("verified_charmap", {}).items():
        if not isinstance(char, str) or not char:
            continue
        slot = int(str(slot_text), 16)
        previous = result.get(char)
        if previous is None or slot < previous:
            result[char] = slot
    if path.resolve() == CHARMAP_12X12_PATH.resolve():
        result["―"] = 0x07B9
    return result


def slot_to_token_bytes(slot: int) -> bytes:
    """Encode one already-reviewed font slot as a GGA text token."""
    gate(1 <= slot <= MAX_LITERAL_SLOT, f"font slot outside text-token range: 0x{slot:04X}")
    if slot <= 0xDF:
        return bytes((slot,))
    token = 0xDF20 + slot
    gate(0xE000 <= token <= 0xEFFF, f"font slot cannot form literal token: 0x{slot:04X}")
    return bytes((token >> 8, token & 0xFF))


def candidate_char_spellings(char: str) -> list[str]:
    """Return explicit ASCII/full-width spellings for one sheet character."""
    candidates: list[str] = []
    pending = [char]
    while pending:
        current = pending.pop(0)
        if current in candidates:
            continue
        candidates.append(current)
        alias = ENCODER_CHAR_ALIASES.get(current)
        if alias is not None and alias not in candidates:
            pending.append(alias)
        code = ord(current)
        if 0x21 <= code <= 0x7E:
            fullwidth_char = chr(code + 0xFEE0)
            if fullwidth_char not in candidates:
                pending.append(fullwidth_char)
        if 0xFF01 <= code <= 0xFF5E:
            ascii_char = chr(code - 0xFEE0)
            if ascii_char not in candidates:
                pending.append(ascii_char)
        if current in {"—", "－"} and "-" not in candidates:
            pending.append("-")
    return candidates


def verified_slot_for(char: str, verified_charmap: dict[str, int] | None) -> int | None:
    if verified_charmap is None:
        return None
    for spelling in candidate_char_spellings(char):
        slot = verified_charmap.get(spelling)
        if slot is not None:
            return slot
    return None


def tokens_from_bytes(data: bytes) -> list[int]:
    tokens: list[int] = []
    index = 0
    while index < len(data):
        lead = data[index]
        index += 1
        if lead == 0:
            break
        if lead <= 0xDF:
            tokens.append(lead)
            continue
        if index >= len(data):
            break
        tokens.append((lead << 8) | data[index])
        index += 1
    return tokens


def raw_hex_bytes(value: str) -> bytes:
    return bytes.fromhex(value.replace(" ", ""))


def ready_text(row: dict[str, Any]) -> str:
    segments = row.get("translation_segments")
    if isinstance(segments, list) and segments:
        return "".join(str(item) for item in segments)
    return str(row.get("translation_ko") or "")


def load_identified_slot_to_char(path: Path) -> dict[int, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    result: dict[int, str] = {}
    for slot_text, char in payload.get("verified_charmap", {}).items():
        if isinstance(char, str) and char:
            result[int(str(slot_text), 16)] = char
    return result


def compatibility_slots(slot_to_char: dict[int, str]) -> set[int]:
    """Return compatibility slots that Korean text or mixed JP may still use.

    Punctuation must be protected too: the 12x12 percent sign is slot 0x00F3.
    Repainting that slot as Hangul made ``80%`` render as ``80깥`` even though
    the translated payload itself was correct.
    """
    protected: set[int] = set()
    for slot, char in slot_to_char.items():
        if not (SLOT_MIN <= slot <= SLOT_MAX) or len(char) != 1:
            continue
        code = ord(char)
        if (
            0x30 <= code <= 0x39
            or 0x41 <= code <= 0x5A
            or 0x61 <= code <= 0x7A
            or 0xFF10 <= code <= 0xFF19
            or 0xFF21 <= code <= 0xFF3A
            or 0xFF41 <= code <= 0xFF5A
            or 0x3040 <= code <= 0x30FF
            or 0x31F0 <= code <= 0x31FF
            or char in PUNCTUATION_CHARS
            or any(spelling in PUNCTUATION_CHARS for spelling in candidate_char_spellings(char))
        ):
            protected.add(slot)
    return protected


def compatibility_8x16_slots(slot_to_char: dict[int, str]) -> set[int]:
    """8x16 slots used by untracked ASCII labels must remain intact."""
    return compatibility_slots(slot_to_char)


def compatibility_12x12_slots(slot_to_char: dict[int, str]) -> set[int]:
    """12x12 slots Korean encoding and leftover JP kana still need intact."""
    return compatibility_slots(slot_to_char)


def row_jp_glyphs_still_drawn(row: dict[str, Any]) -> bool:
    """True when the original Japanese tokens can still reach the renderer."""
    if row.get("scope_status") != "included":
        return False
    relocated = (
        row.get("translation_status") in READY
        and row.get("translation_policy") == "translate"
    )
    # Map banks keep the original JP bytes, but hooked prints draw Hangul instead.
    # scenario_main / production / UI pointers are rewritten when translated.
    if relocated and str(row.get("source_scope") or "") in {
        "scenario_map_script",
        "scenario_main",
        "production",
        "non_scenario_ui",
        "id_command_battle_bark",
    }:
        return False
    return True


def collect_live_slots(
    rom: bytes,
    records: list[dict[str, Any]],
) -> tuple[set[int], set[int]]:
    dict8 = load_dictionary(rom, DICT_8X16_BASE, DICT_8X16_END)
    dict12 = load_dictionary(rom, DICT_12X12_BASE, DICT_12X12_END)
    live8: set[int] = set()
    live12: set[int] = set()
    for row in records:
        if not row_jp_glyphs_still_drawn(row):
            continue
        dictionary = dict12 if uses_12x12(row) else dict8
        chunks: list[str] = []
        segments = row.get("segments") or []
        if segments:
            for segment in segments:
                hex_text = str(segment.get("raw_hex") or "")
                if hex_text.replace(" ", "") not in {"", "00"}:
                    chunks.append(hex_text)
        else:
            chunks.append(str(row.get("raw_hex") or ""))
        used: set[int] = set()
        for hex_text in chunks:
            try:
                used.update(expand_to_slots(tokens_from_bytes(raw_hex_bytes(hex_text)), dictionary))
            except Exception:
                continue
        if uses_12x12(row):
            live12.update(used)
        else:
            live8.update(used)
    live8.update(compatibility_8x16_slots(load_identified_slot_to_char(CHARMAP_8X16_PATH)))
    live12.update(compatibility_12x12_slots(load_identified_slot_to_char(CHARMAP_12X12_PATH)))
    return live8, live12


def build_apply_charmap(
    rom: bytes,
    records: list[dict[str, Any]],
    plan: dict[str, Any],
) -> dict[str, Any]:
    assigned = {str(row["char"]): int(row["slot"], 16) for row in plan["assignments"]}
    compat = {int(slot, 16) for slot in plan["slot_domain"]["compatibility_only_slots"]}
    live8, live12 = collect_live_slots(rom, records)
    domain = set(range(SLOT_MIN, SLOT_MAX + 1)) - RESERVED_GLYPH_SLOTS - compat - SPECIAL_SLOTS
    free8 = domain - live8
    free12 = domain - live12
    free_both = domain - live8 - live12
    prod_chars: set[str] = set()
    scenario_chars: set[str] = set()
    for row in records:
        if row.get("scope_status") != "included" or row.get("translation_status") not in READY:
            continue
        chars = {char for char in ready_text(row) if "가" <= char <= "힣"}
        if uses_12x12(row):
            scenario_chars |= chars
        else:
            prod_chars |= chars
    both = prod_chars & scenario_chars
    only_prod = prod_chars - scenario_chars
    only_scenario = scenario_chars - prod_chars
    pools = {
        "both": sorted(free_both),
        "8x16": sorted(free8),
        "12x12": sorted(free12),
    }
    cursors = {"both": 0, "8x16": 0, "12x12": 0}
    used_slots: set[int] = set()
    mapping: dict[str, int] = {}
    paint_modes: dict[str, str] = {}
    kept = reassigned = newly = split = 0
    assignments: list[dict[str, Any]] = []

    def take_slot(pool_name: str, *, required: bool = True) -> int | None:
        pool = pools[pool_name]
        index = cursors[pool_name]
        while index < len(pool):
            slot = pool[index]
            index += 1
            if slot not in used_slots:
                cursors[pool_name] = index
                return slot
        if required:
            raise SystemExit(f"gate failed: Hangul slots exhausted in pool {pool_name}")
        cursors[pool_name] = index
        return None

    def assign_group(
        chars: set[str],
        mode: str,
        pool_name: str,
        allowed: set[int],
        *,
        allow_miss: bool = False,
    ) -> set[str]:
        nonlocal kept, reassigned, newly
        missed: set[str] = set()
        for char in sorted(chars):
            current = assigned.get(char)
            if (
                current is not None
                and current in allowed
                and current not in used_slots
            ):
                slot = current
                origin = "kept"
                kept += 1
            else:
                slot = take_slot(pool_name, required=not allow_miss)
                if slot is None:
                    missed.add(char)
                    continue
                origin = "new" if current is None else "reassigned"
                if origin == "new":
                    newly += 1
                else:
                    reassigned += 1
            used_slots.add(slot)
            mapping[char] = slot
            paint_modes[char] = mode
            assignments.append(
                {
                    "char": char,
                    "slot": f"0x{slot:04X}",
                    "token": f"0x{0xDF20 + slot:04X}",
                    "source": origin,
                    "paint": mode,
                    "plan_slot": f"0x{current:04X}" if current is not None else "",
                }
            )
        return missed

    remaining_both = assign_group(both, "both", "both", free_both, allow_miss=True)
    assign_group(only_prod, "8x16", "8x16", free8)
    assign_group(only_scenario, "12x12", "12x12", free12)
    mapping8 = {char: slot for char, slot in mapping.items() if char in prod_chars}
    mapping12 = {char: slot for char, slot in mapping.items() if char in scenario_chars}
    for char in sorted(remaining_both):
        slot8 = take_slot("8x16")
        used_slots.add(slot8)
        slot12 = take_slot("12x12")
        used_slots.add(slot12)
        mapping8[char] = slot8
        mapping12[char] = slot12
        paint_modes[char] = "split"
        split += 1
        current = assigned.get(char)
        assignments.append(
            {
                "char": char,
                "slot": f"0x{slot12:04X}",
                "token": f"0x{0xDF20 + slot12:04X}",
                "slot_8x16": f"0x{slot8:04X}",
                "token_8x16": f"0x{0xDF20 + slot8:04X}",
                "source": "split" if current is None else "reassigned_split",
                "paint": "split",
                "plan_slot": f"0x{current:04X}" if current is not None else "",
            }
        )
    gate(set(mapping8) == prod_chars, "8x16 apply charmap lost production Hangul")
    identified12 = load_verified_charmap(CHARMAP_12X12_PATH)
    extra12: set[str] = set()
    for row in records:
        if row.get("scope_status") != "included" or row.get("translation_status") not in READY:
            continue
        if not uses_12x12(row):
            continue
        text = ready_text(row).replace("\\n", "\n")
        for char in text:
            if char in {" ", "\n"} or "가" <= char <= "힣":
                continue
            mapped = ENCODER_CHAR_ALIASES.get(char, char)
            if mapped in identified12 or mapped in mapping12:
                continue
            extra12.add(mapped)
    if extra12:
        assign_group(extra12, "12x12", "12x12", free12)
        mapping12.update({char: mapping[char] for char in extra12})
    gate(scenario_chars <= set(mapping12), "12x12 apply charmap lost scenario Hangul")
    gate(set(mapping12) == scenario_chars | extra12, "12x12 apply charmap extra ASCII drift")
    assignments.sort(key=lambda item: item["char"])
    return {
        "schema_version": 1,
        "description": "Hangul slots painted per font mode against remaining Japanese consumers",
        "source_plan": str(PLAN_PATH.relative_to(ADVANCE_DIR)).replace("\\", "/"),
        "source_plan_assignment_sha256": plan["allocation"]["assignment_sha256"],
        "policy": {
            "both_scopes_prefer_free_both": True,
            "split_slots_when_free_both_exhausted": True,
            "single_scope_paints_one_font": True,
            "reclaim_live_japanese_forbidden": True,
            "scripted_multiline_uses_12x12": True,
            "protect_8x16_latin_digit_slots": True,
            "protect_8x16_kana_slots": True,
            "protect_12x12_latin_digit_slots": True,
            "protect_12x12_kana_slots": True,
            "special_slots_excluded": sorted(f"0x{slot:04X}" for slot in SPECIAL_SLOTS if SLOT_MIN <= slot <= SLOT_MAX),
        },
        "live_remaining_japanese": {
            "font_8x16": len(live8),
            "font_12x12": len(live12),
            "union": len(live8 | live12),
        },
        "summary": {
            "needed_hangul": len(prod_chars | scenario_chars),
            "both_scopes": len(both),
            "production_only": len(only_prod),
            "scenario_only": len(only_scenario),
            "kept": kept,
            "reassigned": reassigned,
            "new": newly,
            "split": split,
            "free_both": len(free_both),
            "free_8x16": len(free8),
            "free_12x12": len(free12),
        },
        "assignments": assignments,
        "_mapping8": mapping8,
        "_mapping12": mapping12,
        "_paint_modes": paint_modes,
    }


def encode_korean_text(
    value: str,
    charmap: dict[str, int],
    *,
    verified_charmap: dict[str, int] | None = None,
    strict_punctuation: bool = False,
) -> tuple[bytes | None, list[str]]:
    """Encode Korean text using the target font's reviewed slot map.

    ``charmap`` contains the newly allocated Hangul slots.  All compatibility
    glyphs (punctuation, Latin, digits, and spacing) are resolved separately
    through ``verified_charmap`` because their numeric slot is font-mode
    specific.  The legacy low-byte fallback is retained only for non-punctuation
    characters in the 8×16 production path; scenario text enables the strict
    punctuation gate so an unreviewed glyph can never silently become kana.
    """
    out = bytearray()
    missing: list[str] = []
    for char in value:
        code = ord(char)
        if char == " ":
            out.append(0x01)
            continue
        if char in charmap:
            token = 0xDF20 + charmap[char]
            gate(0xE000 <= token <= 0xEFFF, f"Korean token outside literal range for {char}")
            out.extend((token >> 8, token & 0xFF))
            continue
        # Font-mode split: 12x12 has a reviewed literal ν at slot 0x0143,
        # while the original 8x16 Nu glyph lives at slot 0x06FC (the same
        # numeric slot used by ∀ in the 12x12 font).  Prefer the verified
        # per-font mapping and only use the preserved 8x16 token as fallback.
        if char == "ν":
            nu_slot = verified_slot_for(char, verified_charmap)
            if nu_slot is not None:
                out.extend(slot_to_token_bytes(nu_slot))
            else:
                out.extend((0xE6, 0xFC))
            continue
        if char in SPECIAL_CHAR_TOKENS:
            token = SPECIAL_CHAR_TOKENS[char]
            out.extend(slot_to_token_bytes(token - 0xDF20) if token >= 0xE000 else bytes((token,)))
            continue

        # Resolve punctuation and compatibility characters through the
        # selected font mode.  This is the critical distinction from the old
        # implementation, which emitted ord(char) and therefore turned `!`,
        # `,`, `…`, and `?` into Japanese kana slots in 12×12 battle text.
        slot = verified_slot_for(char, verified_charmap)
        if slot is not None:
            out.extend(slot_to_token_bytes(slot))
            continue
        if char == "\n":
            out.append(0x0A)
            continue
        if strict_punctuation and (
            char in PUNCTUATION_CHARS
            or any(spelling in PUNCTUATION_CHARS for spelling in candidate_char_spellings(char))
        ):
            missing.append(char)
            continue
        if 1 <= code <= 0xDF:
            out.append(code)
            continue
        missing.append(char)
    if missing:
        return None, sorted(set(missing))
    out.append(0)
    return bytes(out), []


def leading_reserved_prefix(raw: bytes) -> bytes:
    index = 0
    while index + 1 < len(raw):
        lead = raw[index]
        if lead <= 0xDF:
            break
        token = (lead << 8) | raw[index + 1]
        if not 0xE000 <= token <= 0xEFFF:
            break
        slot = token - 0xDF20
        if slot not in RESERVED_GLYPH_SLOTS:
            break
        index += 2
    return raw[:index]


def encode_production_payload(
    unified: dict[str, Any],
    original: bytes,
    charmap: dict[str, int],
    verified_charmap: dict[str, int],
    *,
    strict_punctuation: bool = False,
) -> tuple[bytes, str, list[str]]:
    status = str(unified.get("translation_status") or "")
    policy = str(unified.get("translation_policy") or "")
    if status not in READY or policy != "translate":
        return original, "original", []
    text = str(unified.get("translation_ko") or "")
    if not text.strip():
        return original, "original", []
    encoded, missing = encode_korean_text(
        text,
        charmap,
        verified_charmap=verified_charmap,
        strict_punctuation=strict_punctuation,
    )
    if encoded is None:
        return original, "encode_failed", missing
    prefix = leading_reserved_prefix(original)
    if unified.get("source_reserved_slots") or prefix:
        return prefix + encoded, "translated_reserved_prefix", []
    return encoded, "translated", []


def rebuild_scenario_payload(
    row: dict[str, Any],
    charmap: dict[str, int],
    verified_charmap: dict[str, int],
    *,
    translate: bool,
) -> tuple[bytes | None, list[str]]:
    segments = row.get("segments") or []
    controls = row.get("control_signature") or []
    translations = row.get("translation_segments") or []
    gate(len(segments) == len(controls), f"scenario segment/control drift: {row['record_id']}")
    if translate:
        gate(len(translations) == len(segments), f"scenario translation_segments drift: {row['record_id']}")
    out = bytearray()
    missing: list[str] = []
    for index, (segment, control) in enumerate(zip(segments, controls)):
        original = raw_hex_bytes(str(segment.get("raw_hex") or ""))
        text = str(translations[index]) if translate and index < len(translations) else ""
        if translate and text:
            encoded, failed = encode_korean_text(
                text,
                charmap,
                verified_charmap=verified_charmap,
                strict_punctuation=True,
            )
            if encoded is None:
                missing.extend(failed)
                encoded = original
            out.extend(encoded)
        else:
            out.extend(original)
        code = int(control["code"], 16)
        out.append(code)
        if code in (0x05, 0x06):
            out.append(int(control["argument"]))
    if missing:
        return None, sorted(set(missing))
    return bytes(out), []


def canonical_record(record_by_id: dict[str, dict[str, Any]], record_id: str) -> dict[str, Any] | None:
    row = record_by_id.get(record_id)
    if row is None:
        return None
    if row.get("scope_status") == "alias" and row.get("alias_of"):
        return record_by_id.get(str(row["alias_of"]))
    return row


def allocate_blob(
    candidate: bytearray,
    cursor: int,
    payload: bytes,
    name: str,
) -> tuple[int, int]:
    aligned = (cursor + 3) & ~3
    start = aligned
    end = start + len(payload)
    gate(end <= TEXT_END, f"text region overflow while allocating {name}")
    candidate[start:end] = payload
    return start, end


def build_candidate(
    rom: bytes,
    merged: dict[str, Any],
    font_zip: Path,
    id_bark_overlay: dict[str, Any] | None = None,
    id_bark_extract: dict[str, Any] | None = None,
) -> tuple[bytearray, dict[str, Any], dict[str, Any]]:
    gate(len(rom) == 16 * 1024 * 1024, "clean ROM must be exactly 16 MiB")
    gate(sha256(rom) == EXPECTED_SHA256, "clean ROM SHA-256 drift")
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    records: list[dict[str, Any]] = list(merged["records"])
    owners: list[dict[str, Any]] = list(merged["owners"])
    id_bark_records: list[dict[str, Any]] = []
    if id_bark_overlay is not None:
        id_bark_records = [dict(row) for row in id_bark_overlay.get("records", [])]
        gate(len(id_bark_records) == 1023, f"ID-bark overlay record count drift: {len(id_bark_records)}")
        gate(
            all(row.get("source_scope") == "id_command_battle_bark" for row in id_bark_records),
            "ID-bark overlay contains wrong source_scope",
        )
        existing_ids = {str(row.get("record_id") or "") for row in records}
        gate(not (existing_ids & {str(row.get("record_id") or "") for row in id_bark_records}), "ID-bark record_id collision")
        records.extend(id_bark_records)
    verified_charmap8 = load_verified_charmap(CHARMAP_8X16_PATH)
    verified_charmap12 = load_verified_charmap(CHARMAP_12X12_PATH)
    # Fail before touching any output if the punctuation anchors drift.  These
    # are the exact slots that distinguish the fixed 12×12 battle path from
    # the old ASCII-codepoint implementation.
    punctuation_anchors12 = {",": 0x0002, "…": 0x0007, "!": 0x0005, "?": 0x0004}
    for char, expected_slot in punctuation_anchors12.items():
        actual_slot = verified_slot_for(char, verified_charmap12)
        gate(actual_slot == expected_slot, f"12x12 punctuation map drift for {char!r}: {actual_slot!r}")
    record_by_id = {str(row["record_id"]): row for row in records}
    apply_map = build_apply_charmap(rom, records, plan)
    charmap8: dict[str, int] = apply_map.pop("_mapping8")
    charmap12: dict[str, int] = apply_map.pop("_mapping12")
    paint_modes: dict[str, str] = apply_map.pop("_paint_modes")

    production_unified = {
        row["record_id"]: row
        for row in records
        if row.get("source_scope") == "production" and row.get("scope_status") == "included"
    }
    stage = stage2.build_master(rom)
    stage_rows: list[dict[str, Any]] = []
    raw_by_target: dict[int, bytes] = {}
    production_encode: Counter[str] = Counter()
    production_missing: Counter[str] = Counter()
    for source in stage["records"]:
        row = dict(source)
        unified = production_unified.get(row["record_id"])
        gate(unified is not None, f"production record missing from unified sheet: {row['record_id']}")
        original = raw_hex_bytes(str(row["raw_hex"]))
        if uses_12x12(unified):
            payload, kind, missing = encode_production_payload(
                unified,
                original,
                charmap12,
                verified_charmap12,
                strict_punctuation=True,
            )
        else:
            payload, kind, missing = encode_production_payload(
                unified,
                original,
                charmap8,
                verified_charmap8,
            )
        production_encode[kind] += 1
        production_missing.update(missing)
        row["translation_ko"] = str(unified.get("translation_ko") or "")
        row["translation_status"] = "translated" if kind.startswith("translated") else str(unified.get("translation_status") or "pending")
        row["byte_delta"] = len(payload) - len(original)
        stage_rows.append(row)
        raw_by_target[int(row["target_file_offset"], 16)] = payload
    gate(len(stage_rows) == 4069, f"production row count drift: {len(stage_rows)}")
    gate(set(production_unified) == {row["record_id"] for row in stage_rows}, "production record_id set drift")

    pointer_plan, planned = translation.build_pointer_plan(stage_rows, raw_by_target, rom)
    candidate = bytearray(planned)
    gate(len(candidate) == EXPANDED_SIZE, "translation candidate must be 32 MiB")
    new_target = {
        parse_hex(old_file): parse_hex(new_address)
        for old_file, new_address in pointer_plan["new_targets"].items()
    }
    gate(len(new_target) == 4069, f"production new_target drift: {len(new_target)}")
    for row in stage_rows:
        old_offset = int(row["target_file_offset"], 16)
        payload = raw_by_target[old_offset]
        dest = new_target[old_offset]
        file_off = dest - ROM_BASE
        gate(candidate[file_off:file_off + len(payload)] == payload, f"production payload mismatch: {row['record_id']}")

    cursor = parse_hex(pointer_plan["text_region"]["high_water"])
    extra_payloads: dict[int, bytes] = dict(raw_by_target)
    ui_counts: Counter[str] = Counter()
    scenario_counts: Counter[str] = Counter()
    battle_event_counts: Counter[str] = Counter()
    ui_missing: Counter[str] = Counter()
    scenario_missing: Counter[str] = Counter()

    ui_blob = bytearray()
    ui_rel: dict[int, int] = {}
    for row in sorted(
        (
            item
            for item in records
            if item.get("source_scope") in {"non_scenario_ui", "scenario_dynamic"}
            and item.get("scope_status") == "included"
        ),
        key=lambda item: int(item["target_file_offset"], 16),
    ):
        old_offset = int(row["target_file_offset"], 16)
        original = raw_hex_bytes(str(row["raw_hex"]))
        if old_offset in new_target:
            ui_counts["already_production"] += 1
            continue
        if row.get("translation_status") in READY and row.get("translation_policy") == "translate":
            text = str(row.get("translation_ko") or "")
            if uses_12x12(row):
                encoded, missing = (
                    encode_korean_text(
                        text,
                        charmap12,
                        verified_charmap=verified_charmap12,
                        strict_punctuation=True,
                    )
                    if text.strip()
                    else (None, ["empty"])
                )
            else:
                encoded, missing = (
                    encode_korean_text(text, charmap8, verified_charmap=verified_charmap8)
                    if text.strip()
                    else (None, ["empty"])
                )
            if encoded is None:
                ui_counts["encode_failed"] += 1
                ui_missing.update(missing)
                continue
            # Extended entity-name rows carry the same leading reserved
            # renderer marker as the canonical production name rows.  Keep
            # that prefix when the UI-owner path relocates the translated
            # payload; otherwise the catalogue loses its measured 07FC slot.
            prefix = leading_reserved_prefix(original)
            payload = prefix + encoded if row.get("source_reserved_slots") or prefix else encoded
            ui_counts["translated"] += 1
        else:
            ui_counts["kept_original_pointer"] += 1
            continue
        ui_rel[old_offset] = len(ui_blob)
        ui_blob.extend(payload)
        extra_payloads[old_offset] = payload
    if ui_blob:
        ui_start, cursor = allocate_blob(candidate, cursor, bytes(ui_blob), "unified_ui_streams")
        cursor = (cursor + 3) & ~3
        for old_offset, rel in ui_rel.items():
            new_target[old_offset] = ROM_BASE + ui_start + rel

    scenario_blob = bytearray()
    scenario_rel: dict[int, int] = {}
    for row in sorted(
        (
            item
            for item in records
            if item.get("source_scope") in {"scenario_main", "battle_event_dialogue"}
            and item.get("scope_status") == "included"
        ),
        key=lambda item: int(item["target_file_offset"], 16),
    ):
        old_offset = int(row["target_file_offset"], 16)
        original, rebuild_missing = rebuild_scenario_payload(
            row,
            charmap12,
            verified_charmap12,
            translate=False,
        )
        gate(original is not None and not rebuild_missing, f"scenario original rebuild failed: {row['record_id']}")
        gate(original == raw_hex_bytes(str(row["raw_hex"])), f"scenario roundtrip drift: {row['record_id']}")
        scope_counts = battle_event_counts if row.get("source_scope") == "battle_event_dialogue" else scenario_counts
        if row.get("translation_status") not in READY or row.get("translation_policy") != "translate":
            scope_counts["kept_original_pointer"] += 1
            continue
        payload, missing = rebuild_scenario_payload(
            row,
            charmap12,
            verified_charmap12,
            translate=True,
        )
        if payload is None:
            scope_counts["encode_failed"] += 1
            scenario_missing.update(missing)
            continue
        scenario_rel[old_offset] = len(scenario_blob)
        scenario_blob.extend(payload)
        extra_payloads[old_offset] = payload
        scope_counts["translated"] += 1
    if scenario_blob:
        scenario_start, cursor = allocate_blob(candidate, cursor, bytes(scenario_blob), "unified_scenario_streams")
        cursor = (cursor + 3) & ~3
        for old_offset, rel in scenario_rel.items():
            new_target[old_offset] = ROM_BASE + scenario_start + rel

    # ID-command battle barks bypass the generic 0x08000CA8/map-script draw
    # wrapper.  0x08018058 receives the container pointer directly from the
    # 256x3 table and calls 0x08000648, so parser-pointer redirects do not see
    # this path.  Rebuild each touched multi-stream container in the expansion
    # area, preserving every original continuation/terminal marker and pending
    # Japanese stream byte-for-byte, then patch only the table's +0 pointer.
    # The +4 activation/condition metadata remains untouched.
    id_bark_counts: Counter[str] = Counter()
    id_bark_missing: Counter[str] = Counter()
    id_bark_table_patches: list[dict[str, Any]] = []
    id_bark_blob = bytearray()
    id_bark_container_rel: list[tuple[dict[str, Any], int, bytes]] = []
    id_bark_by_target = {
        parse_hex(str(row["target_file_offset"])): row
        for row in id_bark_records
    }
    if id_bark_records:
        gate(id_bark_extract is not None, "ID-bark extract is required when overlay is enabled")
        extract_entries = list(id_bark_extract.get("entries", [])) if id_bark_extract else []
        gate(len(extract_entries) == 765, f"ID-bark extract entry count drift: {len(extract_entries)}")
        seen_overlay_targets: set[int] = set()
        for entry in extract_entries:
            table_source = parse_hex(str(entry["table_entry_file_offset"]))
            original_container_start = parse_hex(str(entry["container_start_file_offset"]))
            boundary = parse_hex(str(entry["container_boundary_file_offset"]))
            gate(
                u32(rom, table_source) == ROM_BASE + original_container_start,
                f"ID-bark table pointer drift at 0x{table_source:08X}",
            )
            original_container = rom[original_container_start:boundary]
            rebuilt = bytearray()
            translated_in_container = 0
            nonempty_in_container = 0
            streams = list(entry.get("streams", []))
            separators = list(entry.get("separators", []))
            gate(len(streams) == len(separators), f"ID-bark stream/separator mismatch at 0x{original_container_start:08X}")
            for stream, separator in zip(streams, separators):
                stream_start = parse_hex(str(stream["start_file_offset"]))
                original_stream = raw_hex_bytes(str(stream.get("raw_hex") or ""))
                gate(original_stream.endswith(b"\x00"), f"ID-bark stream missing NUL at 0x{stream_start:08X}")
                gate(
                    rom[stream_start : stream_start + len(original_stream)] == original_stream,
                    f"ID-bark source bytes drift at 0x{stream_start:08X}",
                )
                source_text = str(stream.get("source_text") or "")
                payload = original_stream
                if source_text:
                    nonempty_in_container += 1
                    row = id_bark_by_target.get(stream_start)
                    gate(row is not None, f"ID-bark overlay missing stream at 0x{stream_start:08X}")
                    seen_overlay_targets.add(stream_start)
                    if row.get("translation_status") in READY and row.get("translation_policy") == "translate":
                        text = str(row.get("translation_ko") or "")
                        encoded, missing = (
                            encode_korean_text(
                                text,
                                charmap12,
                                verified_charmap=verified_charmap12,
                                strict_punctuation=True,
                            )
                            if text.strip()
                            else (None, ["empty"])
                        )
                        if encoded is None:
                            id_bark_counts["encode_failed"] += 1
                            id_bark_missing.update(missing)
                        else:
                            payload = encoded
                            translated_in_container += 1
                            id_bark_counts["translated"] += 1
                    else:
                        id_bark_counts["pending"] += 1
                rebuilt.extend(payload)
                marker = int(str(separator["marker"]), 16)
                gate(0 <= marker <= 0xFF, f"ID-bark marker outside byte range at 0x{stream_start:08X}")
                rebuilt.append(marker)
            tail = raw_hex_bytes(str(entry.get("tail_padding_hex") or "")) if str(entry.get("tail_padding_hex") or "").strip() else b""
            rebuilt.extend(tail)

            # Round-trip the original container before considering a patch.
            original_roundtrip = bytearray()
            for stream, separator in zip(streams, separators):
                original_roundtrip.extend(raw_hex_bytes(str(stream.get("raw_hex") or "")))
                original_roundtrip.append(int(str(separator["marker"]), 16))
            original_roundtrip.extend(tail)
            gate(bytes(original_roundtrip) == original_container, f"ID-bark container roundtrip drift at 0x{original_container_start:08X}")

            if translated_in_container == 0:
                id_bark_counts["containers_unchanged"] += 1
                continue
            rel = len(id_bark_blob)
            id_bark_blob.extend(rebuilt)
            id_bark_container_rel.append((entry, rel, bytes(rebuilt)))
            id_bark_counts["containers_patched"] += 1
            if translated_in_container == nonempty_in_container:
                id_bark_counts["containers_fully_translated"] += 1
            else:
                id_bark_counts["containers_mixed"] += 1
        gate(
            seen_overlay_targets == set(id_bark_by_target),
            f"ID-bark overlay/extract target mismatch: seen={len(seen_overlay_targets)} overlay={len(id_bark_by_target)}",
        )
    if id_bark_blob:
        id_bark_start, cursor = allocate_blob(candidate, cursor, bytes(id_bark_blob), "id_command_battle_bark_containers")
        cursor = (cursor + 3) & ~3
        for entry, rel, rebuilt in id_bark_container_rel:
            table_source = parse_hex(str(entry["table_entry_file_offset"]))
            original_container_start = parse_hex(str(entry["container_start_file_offset"]))
            new_address = ROM_BASE + id_bark_start + rel
            struct.pack_into("<I", candidate, table_source, new_address)
            id_bark_table_patches.append(
                {
                    "table_entry_file_offset": f"0x{table_source:08X}",
                    "logical_index": int(entry["logical_index"]),
                    "character_index": int(entry["character_index"]),
                    "command_index": int(entry["command_index"]),
                    "old_container_address": f"0x{ROM_BASE + original_container_start:08X}",
                    "new_container_address": f"0x{new_address:08X}",
                    "new_container_size": len(rebuilt),
                }
            )
    gate(not id_bark_missing, "ID-bark Korean encode failed: " + ", ".join(f"{char} x{count}" for char, count in id_bark_missing.items()))

    extra_owner_patches: list[dict[str, Any]] = []
    owner_seen: dict[int, int] = {}
    for patch in pointer_plan["pointer_recalculation"]["owner_patches"]:
        owner_seen[parse_hex(str(patch["source_file"]))] = parse_hex(str(patch["new_value"]))

    def set_extra_owner(source: int, dest: int, kind: str) -> None:
        prior = owner_seen.get(source)
        if prior is None:
            struct.pack_into("<I", candidate, source, dest)
            owner_seen[source] = dest
            extra_owner_patches.append(
                {
                    "source_file": f"0x{source:08X}",
                    "new_value": f"0x{dest:08X}",
                    "kind": kind,
                }
            )
            return
        gate(prior == dest, f"conflicting extra owner at 0x{source:08X}: 0x{prior:08X} vs 0x{dest:08X}")

    extra_kind_counts: Counter[str] = Counter()
    extra_skipped = 0
    for owner in owners:
        if int(owner["pointer_width"]) != 4:
            continue
        schemas = set(owner.get("relocation_schemas") or [])
        if schemas & SKIP_EXTRA_OWNER_SCHEMAS:
            extra_skipped += 1
            continue
        dests: set[int] = set()
        for record_id in owner.get("target_record_ids") or []:
            target = canonical_record(record_by_id, str(record_id))
            if target is None:
                continue
            old_offset = int(target["target_file_offset"], 16)
            if old_offset in new_target and new_target[old_offset] is not None:
                dests.add(int(new_target[old_offset]))
        if not dests:
            continue
        gate(len(dests) == 1, f"owner maps to multiple relocated destinations: {owner['owner_id']}")
        dest = next(iter(dests))
        kind = ",".join(sorted(schemas)) or "u32"
        set_extra_owner(parse_hex(str(owner["source_file_offset"])), dest, kind)
        extra_kind_counts[kind] += 1

    # Safety-net redirects for translated production strings.  Ordinary owner
    # patching remains the primary relocation mechanism, but a few runtime paths
    # retain/derive the original ROM text address instead of loading one of the
    # enumerated u32 owners (battle/ID-command text is the measured example).
    # Reuse the parser/draw redirect hook already required by map-script text so
    # any such original pointer is resolved to the same relocated Korean stream.
    runtime_redirect_by_orig: dict[int, tuple[int, int, int]] = {}
    runtime_redirect_categories: Counter[str] = Counter()
    for row in records:
        if row.get("source_scope") != "production" or row.get("scope_status") != "included":
            continue
        if row.get("translation_policy") != "translate" or row.get("translation_status") not in READY:
            continue
        old_offset = parse_hex(str(row["target_file_offset"]))
        dest = new_target.get(old_offset)
        if dest is None:
            continue
        original = raw_hex_bytes(str(row.get("raw_hex") or ""))
        gate(original.endswith(b"\x00"), f"runtime redirect source is not NUL-terminated: {row['record_id']}")
        orig = ROM_BASE + old_offset
        entry = (orig, int(dest), orig + len(original) - 1)
        prior = runtime_redirect_by_orig.get(orig)
        if prior is None:
            runtime_redirect_by_orig[orig] = entry
            runtime_redirect_categories[str(row.get("semantic_category") or "unknown")] += 1
        else:
            gate(prior == entry, f"conflicting runtime redirect for {row['record_id']} at 0x{orig:08X}")
    runtime_redirects = [runtime_redirect_by_orig[key] for key in sorted(runtime_redirect_by_orig)]

    cursor, map_script = apply_map_script_inline_hooks(
        rom,
        candidate,
        allocate_blob,
        cursor,
        records,
        charmap12,
        runtime_redirects=runtime_redirects,
    )
    map_script["runtime_redirect_categories"] = dict(sorted(runtime_redirect_categories.items()))

    required_hangul = sorted(set(charmap8) | set(charmap12))
    original12 = rom[fontops.FONT_12X12_BASE : fontops.FONT_12X12_BASE + fontops.FONT_12X12_STRIDE * fontops.FONT_12X12_COUNT]
    original8 = rom[fontops.FONT_8X16_BASE : fontops.FONT_8X16_BASE + fontops.FONT_8X16_STRIDE * fontops.FONT_8X16_COUNT]
    blob12 = bytearray(original12)
    blob8 = bytearray(original8)
    for destination, source in KOREAN12_GLYPH_COPIES.items():
        stride = fontops.FONT_12X12_STRIDE
        blob12[destination * stride : (destination + 1) * stride] = original12[source * stride : (source + 1) * stride]
    with ZipFile(font_zip) as archive:
        font12_face = fontpair.load_bdf(archive, CANONICAL_FONT12_MEMBER)
        font8_face = fontpair.load_bdf(archive, CANONICAL_FONT8_MEMBER)
    glyph_rows: list[dict[str, Any]] = []
    painted8: set[int] = set()
    painted12: set[int] = set()
    blank12 = 0
    blank8 = 0
    shared_limit = min(fontops.FONT_12X12_COUNT, fontops.FONT_8X16_COUNT)
    for char in required_hangul:
        mode = paint_modes[char]
        slot12 = charmap12.get(char)
        slot8 = charmap8.get(char)
        packed12 = packed8 = None
        small_image = None
        if mode in {"both", "12x12", "split"}:
            gate(slot12 is not None, f"12x12 Hangul missing slot for {char}")
            gate(slot12 < shared_limit, f"Hangul slot outside shared font range: 0x{slot12:04X}")
            gate(slot12 not in SPECIAL_SLOTS, f"Hangul painted onto special glyph slot 0x{slot12:04X}")
            gate(slot12 not in painted12, f"duplicate 12x12 Hangul slot 0x{slot12:04X}")
            painted12.add(slot12)
            packed12 = fontops.pack_12x12(fontpair.render_12x12_basic(char, font12_face))
            blank12 += not any(packed12)
            start12 = slot12 * fontops.FONT_12X12_STRIDE
            blob12[start12 : start12 + fontops.FONT_12X12_STRIDE] = packed12
        if mode in {"both", "8x16", "split"}:
            gate(slot8 is not None, f"8x16 Hangul missing slot for {char}")
            gate(slot8 < shared_limit, f"Hangul slot outside shared font range: 0x{slot8:04X}")
            gate(slot8 not in SPECIAL_SLOTS, f"Hangul painted onto special glyph slot 0x{slot8:04X}")
            gate(slot8 not in painted8, f"duplicate 8x16 Hangul slot 0x{slot8:04X}")
            painted8.add(slot8)
            small_image = fontpair.render_condensed_8x16_basic(char, font8_face)
            packed8 = fontops.pack_8x16(small_image)
            blank8 += not any(packed8)
            start8 = slot8 * fontops.FONT_8X16_STRIDE
            blob8[start8 : start8 + fontops.FONT_8X16_STRIDE] = packed8
        glyph_rows.append(
            {
                "char": char,
                "slot": f"0x{(slot12 if slot12 is not None else slot8):04X}",
                "token": f"0x{0xDF20 + (slot12 if slot12 is not None else slot8):04X}",
                "slot_8x16": f"0x{slot8:04X}" if slot8 is not None else "",
                "paint": mode,
                "font8_active_rows": (
                    sum(any(small_image.getpixel((x, y)) for x in range(8)) for y in range(16))
                    if small_image is not None
                    else 0
                ),
            }
        )
    gate(blank12 == 0 and blank8 == 0, "one or more selected Korean glyphs rendered blank")

    allocator = layout.AppendAllocator()
    font12_alloc = allocator.allocate(
        "unified_korean_font_12x12",
        len(blob12),
        region="static",
        category="font",
        alignment=0x20,
        source="clean 12x12 font + apply-charmap Hangul slots",
    )
    font8_alloc = allocator.allocate(
        "unified_korean_font_8x16",
        len(blob8),
        region="static",
        category="font",
        alignment=0x20,
        source="clean 8x16 font + apply-charmap Hangul slots",
    )
    candidate[font12_alloc.file_offset : font12_alloc.end_exclusive] = bytes(blob12)
    candidate[font8_alloc.file_offset : font8_alloc.end_exclusive] = bytes(blob8)
    gate(u32(rom, FONT8_LITERAL_FILE) == ORIGINAL_FONT8_ADDRESS, "8x16 font-base literal drift")
    gate(u32(rom, FONT12_LITERAL_FILE) == ORIGINAL_FONT12_ADDRESS, "12x12 font-base literal drift")
    struct.pack_into("<I", candidate, FONT8_LITERAL_FILE, font8_alloc.address)
    struct.pack_into("<I", candidate, FONT12_LITERAL_FILE, font12_alloc.address)

    allowed: set[int] = set(range(FONT8_LITERAL_FILE, FONT8_LITERAL_FILE + 4))
    allowed.update(range(FONT12_LITERAL_FILE, FONT12_LITERAL_FILE + 4))
    allowed.update(hook_allowed_offsets())
    for source in owner_seen:
        allowed.update(range(source, source + 4))
    for patch in id_bark_table_patches:
        source = parse_hex(str(patch["table_entry_file_offset"]))
        allowed.update(range(source, source + 4))
    changed = [index for index, (before, after) in enumerate(zip(rom, candidate[: len(rom)])) if before != after]
    unexpected = [index for index in changed if index not in allowed]
    gate(not unexpected, f"unexpected original-half changes: {len(unexpected)}")
    gate(candidate[STRONG_TAIL : len(rom)] == rom[STRONG_TAIL:], "strong tail changed")
    gate(candidate[0xA0:0xC0] == rom[0xA0:0xC0], "GBA header changed")
    gate(
        candidate[fontops.FONT_12X12_BASE : fontops.FONT_12X12_BASE + fontops.FONT_12X12_STRIDE * fontops.FONT_12X12_COUNT]
        == original12,
        "original 12x12 font was modified",
    )
    gate(
        candidate[fontops.FONT_8X16_BASE : fontops.FONT_8X16_BASE + fontops.FONT_8X16_STRIDE * fontops.FONT_8X16_COUNT]
        == original8,
        "original 8x16 font was modified",
    )
    gate(
        candidate[ID_BARK_PAYLOAD_START:ID_BARK_TABLE_START] == rom[ID_BARK_PAYLOAD_START:ID_BARK_TABLE_START],
        "original ID-bark container payload changed",
    )
    patched_bark_sources = {
        parse_hex(str(patch["table_entry_file_offset"])): parse_hex(str(patch["new_container_address"]))
        for patch in id_bark_table_patches
    }
    for logical_index in range(768):
        source = ID_BARK_TABLE_START + logical_index * 8
        gate(
            candidate[source + 4 : source + 8] == rom[source + 4 : source + 8],
            f"ID-bark metadata changed at logical index {logical_index}",
        )
        if source in patched_bark_sources:
            gate(
                u32(candidate, source) == patched_bark_sources[source],
                f"ID-bark table pointer patch mismatch at logical index {logical_index}",
            )
        else:
            gate(
                candidate[source : source + 4] == rom[source : source + 4],
                f"unexpected ID-bark pointer change at logical index {logical_index}",
            )

    payload_checked = 0
    for old_offset, dest in new_target.items():
        if dest is None:
            continue
        payload = extra_payloads[old_offset]
        file_off = dest - ROM_BASE
        gate(candidate[file_off : file_off + len(payload)] == payload, f"relocated payload mismatch at 0x{old_offset:08X}")
        payload_checked += 1

    owners_by_target: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for owner in owners:
        if int(owner["pointer_width"]) != 4:
            continue
        for record_id in owner.get("target_record_ids") or []:
            owners_by_target[str(record_id)].append(owner)
    pending_scenario_ok = 0
    for row in records:
        if row.get("source_scope") != "scenario_main" or row.get("scope_status") != "included":
            continue
        old_offset = int(row["target_file_offset"], 16)
        if old_offset in new_target:
            continue
        original = raw_hex_bytes(str(row["raw_hex"]))
        gate(
            candidate[old_offset : old_offset + len(original)] == original,
            f"pending scenario original bytes changed: {row['record_id']}",
        )
        pending_scenario_ok += 1
        for owner in owners_by_target.get(row["record_id"], []):
            source = parse_hex(str(owner["source_file_offset"]))
            gate(
                u32(candidate, source) == ROM_BASE + old_offset,
                f"pending scenario pointer moved: {row['record_id']}",
            )

    apply_map["assignments"] = [
        {
            key: item[key]
            for key in ("char", "slot", "token", "slot_8x16", "token_8x16", "source", "paint", "plan_slot")
            if key in item
        }
        for item in apply_map["assignments"]
    ]
    manifest = {
        "schema_version": 1,
        "description": "32 MiB unified-sheet Korean translation PoC",
        "source": merged.get("source"),
        "overlay_identity_sha256": merged.get("identity", {}).get("translation_overlay_identity_sha256"),
        "map_script_translation_overlay_identity_sha256": merged.get("identity", {}).get(
            "map_script_translation_overlay_identity_sha256"
        ),
        "merged_record_identity_sha256": merged.get("identity", {}).get("record_identity_sha256"),
        "encoding": {
            "scenario_main": {
                "font_mode": "12x12",
                "verified_charmap": str(CHARMAP_12X12_PATH.relative_to(ADVANCE_DIR)).replace("\\", "/"),
                "strict_punctuation": True,
                "punctuation_slots": {
                    char: f"0x{slot:04X}" for char, slot in punctuation_anchors12.items()
                },
            },
            "production_and_ui": {
                "font_mode": "8x16",
                "verified_charmap": str(CHARMAP_8X16_PATH.relative_to(ADVANCE_DIR)).replace("\\", "/"),
                "strict_punctuation": False,
                "legacy_fallback": "non-punctuation only",
                "12x12_semantic_categories": sorted(UI_12X12_CATEGORIES),
            },
        },
        "output": {
            "size": len(candidate),
            "sha256": sha256(candidate),
            "text_high_water": f"0x{cursor:08X}",
            "text_remaining": TEXT_END - cursor,
        },
        "apply_charmap_summary": apply_map["summary"],
        "production": {
            "records": 4069,
            "encode": dict(production_encode),
            "encode_failed_characters": [
                {"char": char, "occurrences": count}
                for char, count in production_missing.most_common(20)
            ],
            "pointer_plan_owners": pointer_plan["pointer_recalculation"]["owner_u32_fields"],
        },
        "non_scenario_ui": dict(ui_counts),
        "scenario_main": dict(scenario_counts),
        "battle_event_dialogue": dict(battle_event_counts),
        "id_command_battle_barks": {
            "overlay_identity_sha256": id_bark_overlay.get("identity_sha256") if id_bark_overlay else None,
            "records": len(id_bark_records),
            "encode": dict(id_bark_counts),
            "table_pointer_patches": len(id_bark_table_patches),
            "apply_contract": "rebuild touched multi-stream containers; patch table +0 pointer only; preserve +4 metadata and original payload",
            "table_pointer_patch_samples": id_bark_table_patches[:12],
        },
        "scenario_map_script": map_script,
        "encode_failed_characters": {
            "ui": [{"char": char, "occurrences": count} for char, count in ui_missing.most_common(20)],
            "scenario": [{"char": char, "occurrences": count} for char, count in scenario_missing.most_common(20)],
            "id_command_battle_barks": [{"char": char, "occurrences": count} for char, count in id_bark_missing.most_common(20)],
        },
        "extra_owners": {
            "patched": len(extra_owner_patches),
            "skipped_container_schemas": extra_skipped,
            "kind_counts": dict(extra_kind_counts),
        },
        "fonts": {
            "glyphs_painted": len(glyph_rows),
            "painted_8x16": len(painted8),
            "painted_12x12": len(painted12),
            "rasterization": {
                "12x12": {
                    "member": CANONICAL_FONT12_MEMBER,
                    "face": "Regular",
                    "cell_placement": "native BDF bitmap centered in 12x12",
                },
                "8x16": {
                    "member": CANONICAL_FONT8_MEMBER,
                    "face": "Regular Condensed",
                    "cell_placement": "native BDF bitmap centered in 8x16",
                    "vertical_active_rows": "font-native (no duplication)",
                },
                "synthetic_bold_or_dilation": False,
            },
            "font_12x12": {
                "file_offset": f"0x{font12_alloc.file_offset:08X}",
                "gba_address": f"0x{font12_alloc.address:08X}",
                "changed_bytes": sum(a != b for a, b in zip(original12, blob12)),
            },
            "font_8x16": {
                "file_offset": f"0x{font8_alloc.file_offset:08X}",
                "gba_address": f"0x{font8_alloc.address:08X}",
                "changed_bytes": sum(a != b for a, b in zip(original8, blob8)),
            },
        },
        "verification": {
            "result": "PASS",
            "relocated_payloads": payload_checked,
            "pending_scenario_unmoved": pending_scenario_ok,
            "changed_bytes_in_original_half": len(changed),
            "unexpected_changed_bytes": len(unexpected),
            "map_script_bank_unchanged": True,
            "strong_tail_unchanged": True,
            "original_fonts_unchanged": True,
            "id_bark_payload_unchanged": True,
            "id_bark_metadata_unchanged": True,
            "id_bark_unpatched_table_pointers_unchanged": True,
            "id_bark_table_pointer_patches": len(id_bark_table_patches),
            "header_unchanged": True,
        },
    }
    return candidate, manifest, apply_map


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rom", type=Path)
    parser.add_argument("--merged", type=Path, default=MERGED_PATH)
    parser.add_argument("--font-zip", type=Path, default=FONT_ZIP)
    parser.add_argument("--id-bark-overlay", type=Path, default=ID_BARK_OVERLAY_PATH)
    parser.add_argument("--id-bark-extract", type=Path, default=ID_BARK_EXTRACT_PATH)
    parser.add_argument(
        "--out-rom",
        type=Path,
        default=ADVANCE_DIR / "outputs" / "20260828_ggen_advance_unified_rom" / "ggen_advance_unified_translation_poc_20260828.gba",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ADVANCE_DIR / "legacy" / "analysis" / "ggen_advance_unified_rom_poc_20260828.json",
    )
    parser.add_argument(
        "--apply-charmap",
        type=Path,
        default=ADVANCE_DIR / "legacy" / "analysis" / "ggen_advance_korean_apply_charmap_20260828.json",
    )
    args = parser.parse_args()
    rom = args.rom.read_bytes()
    merged = json.loads(args.merged.read_text(encoding="utf-8"))
    id_bark_overlay = json.loads(args.id_bark_overlay.read_text(encoding="utf-8")) if args.id_bark_overlay.exists() else None
    id_bark_extract = json.loads(args.id_bark_extract.read_text(encoding="utf-8")) if args.id_bark_extract.exists() else None
    candidate, manifest, apply_map = build_candidate(
        rom,
        merged,
        args.font_zip,
        id_bark_overlay=id_bark_overlay,
        id_bark_extract=id_bark_extract,
    )
    args.out_rom.parent.mkdir(parents=True, exist_ok=True)
    args.out_rom.write_bytes(candidate)
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.apply_charmap.parent.mkdir(parents=True, exist_ok=True)
    args.apply_charmap.write_text(json.dumps(apply_map, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
