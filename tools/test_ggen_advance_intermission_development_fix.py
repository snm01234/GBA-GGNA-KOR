#!/usr/bin/env python3
"""Regression tests for the measured intermission/development fixes."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import apply_ggen_advance_intermission_development_fix_20260829 as fix  # noqa: E402
import apply_ggen_advance_development_dialogue_fit_20260829 as fit  # noqa: E402
import build_ggen_advance_unified_rom_poc as builder  # noqa: E402


class IntermissionDevelopmentFixTests(unittest.TestCase):
    def test_all_measured_records_are_covered(self) -> None:
        self.assertEqual(len(fix.TRANSLATIONS), 26)
        self.assertEqual(
            fix.TRANSLATIONS["GGA-TEXT-001BE8AE"],
            ("データをセーブします", "데이터를 세이브합니다"),
        )
        self.assertEqual(
            fix.TRANSLATIONS["GGA-TEXT-001BE972"],
            ("では、改造を行います", "그럼 개조를 시작합니다"),
        )

    def test_runtime_categories_use_12x12(self) -> None:
        for category in (
            "map_system_function_help",
            "stage_battle_condition_target_label",
        ):
            self.assertTrue(builder.uses_12x12({"semantic_category": category}))

    def test_percent_glyph_slot_is_protected(self) -> None:
        slot_to_char = builder.load_identified_slot_to_char(builder.CHARMAP_12X12_PATH)
        self.assertEqual(slot_to_char[0x00F3], "％")
        self.assertIn(0x00F3, builder.compatibility_12x12_slots(slot_to_char))

    def test_split_completion_dialogue_stays_within_measured_width(self) -> None:
        self.assertEqual(fit.TRANSLATIONS["GGA-TEXT-001BE97E"], "완성됐습니다 기체는")
        self.assertEqual(fit.TRANSLATIONS["GGA-TEXT-001BE98E"], "스톡으로 보냅니다")
        for record_id in ("GGA-TEXT-001BE98E", "GGA-TEXT-001BE9B2"):
            self.assertLessEqual(len(fit.TRANSLATIONS[record_id]), 10)


if __name__ == "__main__":
    unittest.main(verbosity=2)
