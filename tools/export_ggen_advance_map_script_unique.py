#!/usr/bin/env python3
"""Export slot-complete map-script unique JP for Korean overlay drafting.

Does not translate.  Partial leftover rows are excluded.  Compact/overlay
JSON is not written into analysis/ggen_advance_translation_overlays/.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
ADDENDUM = ROOT / "analysis" / "ggen_advance_map_script_unified_records_20260828.json"
WORK = ROOT / "analysis" / "map_script_ko_work"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--addendum", type=Path, default=ADDENDUM)
    parser.add_argument("--work", type=Path, default=WORK)
    parser.add_argument("--chunk-size", type=int, default=400)
    args = parser.parse_args()

    payload = json.loads(args.addendum.read_text(encoding="utf-8"))
    unique: dict[tuple[str, ...], dict[str, Any]] = {}
    order: list[tuple[str, ...]] = []
    complete = 0
    partial = 0
    for row in payload["records"]:
        if row.get("source_decode_status") != "complete":
            partial += 1
            continue
        complete += 1
        parts = tuple(str(segment.get("source_text") or "") for segment in row.get("segments") or [])
        if parts not in unique:
            unique[parts] = {
                "id": len(order),
                "parts_jp": list(parts),
                "record_ids": [],
                "parts_ko": None,
            }
            order.append(parts)
        unique[parts]["record_ids"].append(row["record_id"])

    records = [unique[key] for key in order]
    args.work.mkdir(parents=True, exist_ok=True)
    unique_path = args.work / "unique_complete_jp.json"
    unique_path.write_text(json.dumps({"records": records}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    chunk_dir = args.work / "chunks"
    chunk_dir.mkdir(parents=True, exist_ok=True)
    for old in chunk_dir.glob("chunk_*.json"):
        old.unlink()
    chunk_paths: list[str] = []
    size = max(1, args.chunk_size)
    for start in range(0, len(records), size):
        chunk = records[start : start + size]
        index = start // size
        path = chunk_dir / f"chunk_{index:02d}.json"
        path.write_text(
            json.dumps(
                {
                    "chunk_index": index,
                    "start_id": chunk[0]["id"],
                    "end_id": chunk[-1]["id"],
                    "records": [
                        {"id": item["id"], "parts_jp": item["parts_jp"]}
                        for item in chunk
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        chunk_paths.append(path.name)

    print(
        json.dumps(
            {
                "result": "PASS",
                "complete_rows": complete,
                "partial_rows_excluded": partial,
                "unique": len(records),
                "chunk_size": size,
                "chunks": len(chunk_paths),
                "unique_path": str(unique_path),
                "chunk_dir": str(chunk_dir),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
