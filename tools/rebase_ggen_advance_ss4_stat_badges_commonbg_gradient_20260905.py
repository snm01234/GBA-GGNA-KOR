#!/usr/bin/env python3
"""Rebase the user-approved ss4 common-background/gradient badge tiles onto current main TIP.

The approved visual candidate was built from an older parent.  This script copies
only the five approved 4x2 badge resources' atlas tiles into the current main TIP,
so unrelated changes already promoted after that older parent remain byte-exact.
"""
from __future__ import annotations

import hashlib
import json
import struct
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_fixed_word_semantics_20260830 as sem
import build_ggen_advance_status_ui_tile_overlay_poc as status
from ggen_advance_project_paths import ADVANCE_ROOT, MAIN_TIP_MANIFEST, MAIN_TIP_ROM, advance_relative

TABLE = 0x000E0518
TARGET_RESOURCES = (24, 27, 21, 23, 25)
OUT = ADVANCE_ROOT / "outputs" / "20260905_ggen_advance_ss4_stat_badges"
APPROVED = OUT / "ggen_advance_ss4_stat_badges_ko_commonbg_gradient_candidate_20260905.gba"
APPROVED_MANIFEST = OUT / "manifest_commonbg_gradient.json"
RESULT = OUT / "ggen_advance_ss4_stat_badges_ko_commonbg_gradient_mainrebase_candidate_20260905.gba"
MANIFEST = OUT / "manifest_commonbg_gradient_mainrebase.json"
VERIFY_LOG = OUT / "verification_commonbg_gradient_mainrebase.log"


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def parse_map(data: bytes, index: int) -> dict:
    obj = sem.parse_map(data, u32(data, TABLE + index * 4))
    assert obj is not None and (obj["width"], obj["height"]) == (4, 2), index
    return obj


def atlas_info(data: bytes) -> tuple[int, int, bytes, bytes]:
    ptr = u32(data, TABLE)
    off = ptr - 0x08000000
    header = u32(data, off)
    assert header & 0x80000000
    body_len = header & 0xFFFF
    blob = data[off:off + 4 + body_len]
    decoded = status.lzss_decompress(blob[4:])
    assert len(decoded) == status.ATLAS_EXPECTED_DECODED
    return ptr, off, blob, decoded


def main() -> int:
    main_data = MAIN_TIP_ROM.read_bytes()
    main_manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    assert main_manifest.get("status") == "approved_main_tip"
    assert sha256(main_data) == main_manifest.get("sha256")

    approved = APPROVED.read_bytes()
    approved_manifest = json.loads(APPROVED_MANIFEST.read_text(encoding="utf-8"))
    assert approved_manifest.get("verification", {}).get("result") == "PASS"
    assert approved_manifest.get("output", {}).get("sha256") == sha256(approved)
    assert approved_manifest.get("output", {}).get("size") == len(approved) == 32 * 1024 * 1024

    main_ptr, main_off, main_blob, main_atlas = atlas_info(main_data)
    approved_ptr, _approved_off, _approved_blob, approved_atlas = atlas_info(approved)
    assert main_ptr == approved_ptr, (hex(main_ptr), hex(approved_ptr))

    target_ids: set[int] = set()
    resource_tiles: dict[str, list[int]] = {}
    for idx in TARGET_RESOURCES:
        main_obj = parse_map(main_data, idx)
        approved_obj = parse_map(approved, idx)
        main_ids = [c & 0x3FF for c in main_obj["cells"]]
        approved_ids = [c & 0x3FF for c in approved_obj["cells"]]
        assert main_ids == approved_ids, idx
        resource_tiles[str(idx)] = main_ids
        target_ids.update(main_ids)

    patched_atlas = bytearray(main_atlas)
    for tid in sorted(target_ids):
        patched_atlas[tid * 32:(tid + 1) * 32] = approved_atlas[tid * 32:(tid + 1) * 32]

    # The user-approved tile payloads must be byte-identical after the rebase.
    assert all(
        patched_atlas[tid * 32:(tid + 1) * 32] == approved_atlas[tid * 32:(tid + 1) * 32]
        for tid in target_ids
    )
    # Every non-target atlas tile remains current-main byte-exact.
    non_target_changed = [
        tid for tid in range(len(main_atlas) // 32)
        if tid not in target_ids
        and patched_atlas[tid * 32:(tid + 1) * 32] != main_atlas[tid * 32:(tid + 1) * 32]
    ]
    assert not non_target_changed, non_target_changed

    new_blob = status.literal_only_compress(bytes(patched_atlas))
    assert len(new_blob) == len(main_blob), (len(new_blob), len(main_blob))
    assert status.lzss_decompress(new_blob[4:]) == bytes(patched_atlas)

    result = bytearray(main_data)
    result[main_off:main_off + len(main_blob)] = new_blob
    assert result[:main_off] == main_data[:main_off]
    assert result[main_off + len(main_blob):] == main_data[main_off + len(main_blob):]

    OUT.mkdir(parents=True, exist_ok=True)
    RESULT.write_bytes(result)
    result_sha = sha256(result)

    verification = {
        "result": "PASS",
        "approved_visual_candidate_sha256": sha256(approved),
        "current_main_parent_sha256": sha256(main_data),
        "target_resources": list(TARGET_RESOURCES),
        "target_tile_count": len(target_ids),
        "approved_target_tiles_byte_identical": True,
        "non_target_atlas_tiles_current_main_byte_exact": True,
        "outside_e0518_stream_current_main_byte_exact": True,
        "compression_roundtrip": True,
        "current_main_manifest_status": main_manifest.get("status"),
    }
    manifest = {
        "kind": "ggen_advance_ss4_stat_badges_commonbg_gradient_mainrebase_candidate_20260905",
        "parent_main_tip": {
            "path": advance_relative(MAIN_TIP_ROM),
            "manifest_path": advance_relative(MAIN_TIP_MANIFEST),
            "sha256": sha256(main_data),
            "promotion_reason": main_manifest.get("promotion_reason"),
        },
        "approved_source": {
            "path": advance_relative(APPROVED),
            "manifest_path": advance_relative(APPROVED_MANIFEST),
            "sha256": sha256(approved),
        },
        "output": {
            "path": advance_relative(RESULT),
            "sha256": result_sha,
            "size": len(result),
        },
        "atlas": {
            "table": f"0x{TABLE:08X}",
            "pointer": f"0x{main_ptr:08X}",
            "file_offset": f"0x{main_off:08X}",
            "target_resources": resource_tiles,
            "target_tile_count": len(target_ids),
            "target_tiles": sorted(target_ids),
        },
        "verification": verification,
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    VERIFY_LOG.write_text(
        "\n".join([
            "PASS ss4 common-background/gradient main-TIP rebase candidate",
            f"current_main={sha256(main_data)} reason={main_manifest.get('promotion_reason')}",
            f"approved_source={sha256(approved)}",
            f"target_resources={list(TARGET_RESOURCES)} target_tiles={len(target_ids)}",
            "approved_target_tiles_byte_identical=true",
            "non_target_atlas_tiles_current_main_byte_exact=true",
            "outside_e0518_stream_current_main_byte_exact=true",
            "compression_roundtrip=true",
            f"output={advance_relative(RESULT)} sha256={result_sha}",
        ]) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
