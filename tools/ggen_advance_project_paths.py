"""Canonical paths for the advance-local translation workflow.

All project inputs and outputs resolve from ``advance`` itself.  This module
deliberately does not walk above the advance project root, so active builders
do not depend on the parent Mono-Eye project layout.
"""
from __future__ import annotations

from pathlib import Path


ADVANCE_ROOT = Path(__file__).resolve().parents[1]

ORIGINAL_ROM = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Japan).gba"
MAIN_TIP_ROM = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).gba"
ORIGINAL_ROM_SIZE = 16 * 1024 * 1024
MAIN_TIP_ROM_SIZE = 32 * 1024 * 1024
ORIGINAL_ROM_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"
DIST_ROOT = ADVANCE_ROOT / "outputs" / "dist"
VERSION_FILE = ADVANCE_ROOT / "VERSION"

INTEGRATED_ROOT = ADVANCE_ROOT / "integrated"
MAIN_TIP_ROOT = INTEGRATED_ROOT / "main_tip"
MAIN_TIP_MANIFEST = MAIN_TIP_ROOT / "ggen_advance_main_tip_manifest.json"
MAIN_TIP_BACKUP_ROOT = MAIN_TIP_ROOT / "backups"

TRANSLATION_ROOT = INTEGRATED_ROOT / "translation"
TRANSLATION_MERGED_JSON = TRANSLATION_ROOT / "ggen_advance_translation_merged.json"
TRANSLATION_WORKBOOK = TRANSLATION_ROOT / "ggen_advance_translation_master.xlsx"
TRANSLATION_MANIFEST = TRANSLATION_ROOT / "ggen_advance_translation_manifest.json"
TRANSLATION_PREVIEW_ROOT = TRANSLATION_ROOT / "previews"

LATEST_POC_ROM = (
    ADVANCE_ROOT
    / "legacy"
    / "poc"
    / "outputs"
    / "20260913_blue_destiny"
    / "ggen_blue_destiny_20260913.gba"
)
LATEST_POC_MANIFEST = (
    ADVANCE_ROOT
    / "legacy"
    / "poc"
    / "outputs"
    / "20260913_blue_destiny"
    / "manifest.json"
)
LATEST_MERGED_ANALYSIS = TRANSLATION_MERGED_JSON

UNIFIED_SOURCE = (
    ADVANCE_ROOT / "legacy" / "analysis" / "ggen_advance_unified_source_20260827.json"
)
FONT_ZIP = ADVANCE_ROOT / "assets" / "fonts" / "Galmuri.zip"


def release_version() -> str:
    """Return the public release version from ``VERSION``, defaulting to 1.0.0."""

    if VERSION_FILE.is_file():
        text = VERSION_FILE.read_text(encoding="utf-8").strip()
        if text:
            return text.splitlines()[0].strip()
    return "1.0.0"


def dist_release_name() -> str:
    return f"ggen_advance_ko_v{release_version()}"


def advance_relative(path: Path) -> str:
    """Return a stable path for manifests and advance-local documents."""

    return path.resolve().relative_to(ADVANCE_ROOT.resolve()).as_posix()
