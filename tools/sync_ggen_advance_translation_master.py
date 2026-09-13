#!/usr/bin/env python3
"""Publish the latest advance translation merge into one canonical location.

Date-stamped files under ``analysis`` remain historical evidence.  The active
translation source used by later builds is always the single JSON file under
``integrated/translation``.  The copy is byte-preserving and verified by
SHA-256 so a path refactor cannot silently alter the merge.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections import Counter
from pathlib import Path

from ggen_advance_project_paths import (
    LATEST_MERGED_ANALYSIS,
    TRANSLATION_MANIFEST,
    TRANSLATION_MERGED_JSON,
    advance_relative,
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_copy(source: Path, destination: Path, payload: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, destination)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=LATEST_MERGED_ANALYSIS)
    parser.add_argument("--out", type=Path, default=TRANSLATION_MERGED_JSON)
    parser.add_argument("--manifest", type=Path, default=TRANSLATION_MANIFEST)
    args = parser.parse_args()

    source = args.source.resolve()
    output = args.out.resolve()
    manifest_path = args.manifest.resolve()
    if not source.is_file():
        raise SystemExit(f"gate failed: merge source does not exist: {source}")
    if not source.is_relative_to(TRANSLATION_MERGED_JSON.parents[2].resolve()):
        raise SystemExit("gate failed: source must remain inside the advance project")

    payload_bytes = source.read_bytes()
    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"gate failed: merge source is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
        raise SystemExit("gate failed: merge source has no records list")
    if payload.get("merge", {}).get("rom_write_performed") is not False:
        raise SystemExit("gate failed: merge source must remain a no-ROM-write translation merge")

    source_sha = sha256(payload_bytes)
    atomic_copy(source, output, payload_bytes)
    output_sha = sha256(output.read_bytes())
    if output_sha != source_sha:
        raise SystemExit("gate failed: canonical merge copy changed bytes")

    summary = payload.get("summary", {})
    record_status_counts = dict(
        sorted(Counter(str(record.get("translation_status", "")) for record in payload["records"]).items())
    )
    manifest = {
        "schema_version": 1,
        "kind": "ggen_advance_canonical_translation_source",
        "canonical_path": advance_relative(output),
        "source_snapshot": advance_relative(source),
        "sha256": output_sha,
        "source_sha256": source_sha,
        "record_count": len(payload["records"]),
        "record_identity_sha256": payload.get("identity", {}).get("record_identity_sha256"),
        "translation_overlay_identity_sha256": payload.get("identity", {}).get(
            "translation_overlay_identity_sha256"
        ),
        "record_translation_status_counts": record_status_counts,
        "source_summary_translation_status_counts": summary.get("merged_translation_status_counts", {}),
        "policy": {
            "active_source_is_single_path": True,
            "dated_analysis_snapshots_are_historical": True,
            "outputs_directory_is_not_translation_source_of_truth": True,
            "parent_project_references_forbidden": True,
        },
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
