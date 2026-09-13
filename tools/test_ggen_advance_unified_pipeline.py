#!/usr/bin/env python3
"""Regression tests for the unified source and overlay merge gates."""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parent
ROOT_DIR = TOOLS_DIR.parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import build_ggen_advance_unified_source as build_source  # noqa: E402
import merge_ggen_advance_translation_overlays as merge_overlays  # noqa: E402


ROM_PATH = ROOT_DIR / "SD Gundam GGeneration Advance (Japan).gba"
PRODUCTION_PATH = ROOT_DIR / "legacy/analysis/stage2_translation_sheet_rows_20260827.json"
SCENARIO_PATH = ROOT_DIR / "legacy/analysis/scenario_event_translation_source_20260827.json"
ALIGNMENT_PATH = ROOT_DIR / "legacy/analysis/scenario_event_12x12_alignment_20260827.json"
UI_PATH = ROOT_DIR / "legacy/analysis/non_scenario_ui_matrix_expansion_20260827.json"
SCAN_PATH = ROOT_DIR / "legacy/analysis/non_scenario_expansion_audit_20260827.json"


def identity_item(source: dict, row: dict, *, batch_id: str, **payload: object) -> dict:
    item = {
        "record_id": row["record_id"],
        "source_rom_sha256": source["source"]["sha256"],
        "manifest_identity_sha256": source["identity"]["manifest_identity_sha256"],
        "original_raw_sha256": row["original_raw_sha256"],
        "owner_digest": row["owner_digest"],
        "source_fingerprint": row["source_fingerprint"],
        "target_file_offset": row["target_file_offset"],
        "translation_unit_id": row["translation_unit_id"],
        "context_bundle_id": row["context_bundle_id"],
        "batch_id": batch_id,
        "translation_source": "llm",
        "source_model": "test-model",
        "prompt_version": "test-prompt-v1",
        "translation_status": "translated",
        "review_status": "draft",
        "translation_ko": "테스트 번역",
    }
    item.update(payload)
    return item


class UnifiedPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = build_source.build_report(
            ROM_PATH,
            PRODUCTION_PATH,
            SCENARIO_PATH,
            ALIGNMENT_PATH,
            UI_PATH,
            SCAN_PATH,
        )
        cls.source_by_id = {row["record_id"]: row for row in cls.source["records"]}

    def write_source(self, directory: Path) -> Path:
        path = directory / "unified_source.json"
        path.write_text(json.dumps(self.source, ensure_ascii=False), encoding="utf-8")
        return path

    def write_overlay(self, directory: Path, name: str, records: list[dict]) -> Path:
        path = directory / name
        payload = {
            "schema_version": 1,
            "kind": "ggen_advance_translation_overlay",
            "batch_id": records[0]["batch_id"],
            "source_rom_sha256": self.source["source"]["sha256"],
            "manifest_identity_sha256": self.source["identity"]["manifest_identity_sha256"],
            "translation_source": "llm",
            "source_model": "test-model",
            "prompt_version": "test-prompt-v1",
            "records": records,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def test_builder_contract_and_counts(self) -> None:
        self.assertEqual(self.source["source"]["sha256"], "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772")
        self.assertEqual(self.source["summary"]["source_scope_counts"], {
            "non_scenario_ui": 1739,
            "production": 4069,
            "scenario_dynamic": 165,
            "scenario_main": 5343,
        })
        self.assertEqual(self.source["summary"]["alias_records"], 375)
        self.assertEqual(self.source["summary"]["exclusion_count"], 12263)
        self.assertEqual(len(self.source["owners"]), self.source["summary"]["owner_count"])
        for row in self.source["records"]:
            if row["scope_status"] == "alias":
                self.assertIn(row["alias_of"], self.source_by_id)
                self.assertEqual(self.source_by_id[row["alias_of"]]["scope_status"], "included")

    def test_draft_merge_and_scenario_control_segments(self) -> None:
        single_units = Counter(
            row["translation_unit_id"]
            for row in self.source["records"]
            if row["scope_status"] == "included" and row["translation_policy"] == "translate"
        )
        ordinary = next(
            row
            for row in self.source["records"]
            if row["scope_status"] == "included"
            and row["translation_policy"] == "translate"
            and single_units[row["translation_unit_id"]] == 1
            and row["record_kind"] == "text_stream"
        )
        scenario = next(
            row
            for row in self.source["records"]
            if row["record_kind"] == "scenario_controlled_text_stream"
        )
        scenario_segments = [
            "" if not segment["is_text_segment"] else f"시나리오 {index}"
            for index, segment in enumerate(scenario["segments"])
        ]
        scenario_display = "\n".join(
            value
            for segment, value in zip(scenario["segments"], scenario_segments)
            if segment["is_text_segment"] and value
        )
        ordinary_item = identity_item(self.source, ordinary, batch_id="test-ordinary")
        scenario_item = identity_item(
            self.source,
            scenario,
            batch_id="test-scenario",
            translation_ko=scenario_display,
            translation_segments=scenario_segments,
            control_signature=copy.deepcopy(scenario["control_signature"]),
            segments_sha256=merge_overlays.digest(scenario["segments"]),
        )
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            source_path = self.write_source(directory)
            ordinary_path = self.write_overlay(directory, "ordinary.json", [ordinary_item])
            scenario_path = self.write_overlay(directory, "scenario.json", [scenario_item])
            output_path = directory / "merged.json"
            result = merge_overlays.run(
                source_path,
                [ordinary_path, scenario_path],
                output_path,
                mode="draft",
                summary_only=False,
            )
            self.assertEqual(result["merge"]["accepted_record_count"], 2)
            self.assertEqual(result["merge"]["batch_count"], 2)
            merged = {row["record_id"]: row for row in result["records"]}
            self.assertEqual(merged[ordinary["record_id"]]["translation_ko"], "테스트 번역")
            self.assertEqual(merged[scenario["record_id"]]["translation_segments"], scenario_segments)
            self.assertEqual(merged[scenario["record_id"]]["translation_ko"], scenario_display)
            self.assertTrue(output_path.exists())

    def test_duplicate_record_and_stale_fingerprint_fail(self) -> None:
        row = next(
            row
            for row in self.source["records"]
            if row["scope_status"] == "included" and row["translation_policy"] == "translate"
        )
        first = identity_item(self.source, row, batch_id="duplicate-a")
        second = identity_item(self.source, row, batch_id="duplicate-b", translation_ko="다른 번역")
        stale = identity_item(self.source, row, batch_id="stale", source_fingerprint="0" * 64)
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            source_path = self.write_source(directory)
            first_path = self.write_overlay(directory, "first.json", [first])
            second_path = self.write_overlay(directory, "second.json", [second])
            stale_path = self.write_overlay(directory, "stale.json", [stale])
            with self.assertRaises(SystemExit):
                merge_overlays.run(source_path, [first_path, second_path], directory / "duplicate.json", mode="draft", summary_only=True)
            with self.assertRaises(SystemExit):
                merge_overlays.run(source_path, [stale_path], directory / "stale-out.json", mode="draft", summary_only=True)

    def test_jsonl_metadata_line_is_supported(self) -> None:
        row = next(
            row
            for row in self.source["records"]
            if row["scope_status"] == "included" and row["translation_policy"] == "translate"
        )
        item = identity_item(self.source, row, batch_id="jsonl-batch")
        for field in (
            "source_rom_sha256",
            "manifest_identity_sha256",
            "batch_id",
            "translation_source",
            "source_model",
            "prompt_version",
        ):
            item.pop(field, None)
        metadata = {
            "schema_version": 1,
            "kind": "ggen_advance_translation_overlay_meta",
            "batch_id": "jsonl-batch",
            "source_rom_sha256": self.source["source"]["sha256"],
            "manifest_identity_sha256": self.source["identity"]["manifest_identity_sha256"],
            "translation_source": "llm",
            "source_model": "test-model",
            "prompt_version": "test-prompt-v1",
        }
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            source_path = self.write_source(directory)
            overlay_path = directory / "batch.jsonl"
            overlay_path.write_text(
                json.dumps(metadata, ensure_ascii=False) + "\n" + json.dumps(item, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            result = merge_overlays.run(source_path, [overlay_path], directory / "merged.json", mode="draft", summary_only=True)
            self.assertEqual(result["merge"]["accepted_record_count"], 1)

    def test_partial_translation_unit_fails(self) -> None:
        members: dict[str, list[dict]] = {}
        for row in self.source["records"]:
            if row["scope_status"] == "included" and row["translation_policy"] == "translate":
                members.setdefault(row["translation_unit_id"], []).append(row)
        unit = next(rows for rows in members.values() if len(rows) > 1)
        item = identity_item(self.source, unit[0], batch_id="partial-unit")
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            source_path = self.write_source(directory)
            overlay_path = self.write_overlay(directory, "partial.json", [item])
            with self.assertRaises(SystemExit):
                merge_overlays.run(source_path, [overlay_path], directory / "partial-out.json", mode="draft", summary_only=True)

    def test_approved_mode_requires_review_metadata(self) -> None:
        row = next(
            row
            for row in self.source["records"]
            if row["scope_status"] == "included" and row["translation_policy"] == "translate"
        )
        item = identity_item(self.source, row, batch_id="draft-not-approved")
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            source_path = self.write_source(directory)
            overlay_path = self.write_overlay(directory, "draft.json", [item])
            with self.assertRaises(SystemExit):
                merge_overlays.run(source_path, [overlay_path], directory / "approved-out.json", mode="approved", summary_only=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
