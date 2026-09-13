#!/usr/bin/env python3
"""Rebase the approved 소유수 overlay onto the initial BG2 transfer.

The approved main already routes the steady-state/cursor-redraw transfer at
0x0806EB3E through the verified live-tile overlay at 0x080C5700.  The entry
builder 0x0806D350 calls the actual BG2 compositor at 0x0806D380 and performs
its first transfer at 0x0806D384.  Routing that first transfer through the
same overlay makes the Japanese glyphs and their Korean replacement occur in
one synchronous call, before control returns to the entry builder.

Only the four-byte BL at 0x0806D384 is changed.  The canonical main TIP and
its SAV are never modified.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import struct
import subprocess
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import build_ggen_advance_owned_count_ab_candidates_20260903 as thumb
import build_ggen_advance_owned_count_live_overlay_candidate_20260904 as overlay
from ggen_advance_project_paths import (
    ADVANCE_ROOT,
    MAIN_TIP_MANIFEST,
    MAIN_TIP_ROM,
    advance_relative,
)

EXPECTED_MAIN_SHA256 = "f4ec36f115ea03af0b8f40f84686a5f6f5b2b5526e5d857b84703a3bcc8c3db4"
MAIN_SAV = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).sav"
OUT_DIR = ADVANCE_ROOT / "outputs" / "20260905_ggen_advance_owned_count_entry_no_flash"
OUT_ROM = OUT_DIR / "ggen_advance_owned_count_entry_no_flash_candidate_20260905.gba"
OUT_SAV = OUT_DIR / "ggen_advance_owned_count_entry_no_flash_candidate_20260905.sav"
MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_owned_count_entry_no_flash_candidate_20260905.json"

ROM_BASE = 0x08000000
COMPOSITOR_CALL = 0x0806D380
COMPOSITOR = 0x0806CFC4
ENTRY_TRANSFER_CALL = 0x0806D384
ORIGINAL_TRANSFER = 0x08063194
STEADY_TRANSFER_CALL = 0x0806EB3E
OVERLAY_STUB = overlay.STUB_ADDR
OVERLAY_STUB_FILE = overlay.STUB_FILE
OVERLAY_PAYLOAD_FILE = overlay.PAYLOAD_FILE
OVERLAY_PAYLOAD_BYTES = 10 * 32


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def changed_ranges(offsets: list[int]) -> list[list[str]]:
    if not offsets:
        return []
    rows: list[list[str]] = []
    start = previous = offsets[0]
    for value in offsets[1:]:
        if value != previous + 1:
            rows.append([f"0x{start:08X}", f"0x{previous + 1:08X}"])
            start = value
        previous = value
    rows.append([f"0x{start:08X}", f"0x{previous + 1:08X}"])
    return rows


def main() -> int:
    parent = MAIN_TIP_ROM.read_bytes()
    main_manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(parent) == EXPECTED_MAIN_SHA256, f"main TIP hash drift: {sha256(parent)}")
    gate(main_manifest.get("sha256") == EXPECTED_MAIN_SHA256, "main manifest hash drift")
    gate(MAIN_SAV.is_file(), "main SAV missing")

    # Prove the entry boundary and the already-approved steady-state overlay.
    gate(thumb.thumb_bl_target(parent, COMPOSITOR_CALL) == COMPOSITOR, "entry compositor call drift")
    gate(thumb.thumb_bl_target(parent, ENTRY_TRANSFER_CALL) == ORIGINAL_TRANSFER, "entry transfer call drift")
    gate(thumb.thumb_bl_target(parent, STEADY_TRANSFER_CALL) == OVERLAY_STUB, "approved steady overlay hook missing")
    stub = overlay.build_stub_clean()
    gate(parent[OVERLAY_STUB_FILE:OVERLAY_STUB_FILE + len(stub)] == stub, "approved overlay stub drift")
    payload = parent[OVERLAY_PAYLOAD_FILE:OVERLAY_PAYLOAD_FILE + OVERLAY_PAYLOAD_BYTES]
    gate(any(payload), "approved 소유수 payload is blank")

    child = bytearray(parent)
    entry_file = ENTRY_TRANSFER_CALL - ROM_BASE
    child[entry_file:entry_file + 4] = thumb.encode_thumb_bl(ENTRY_TRANSFER_CALL, OVERLAY_STUB)
    gate(thumb.thumb_bl_target(child, ENTRY_TRANSFER_CALL) == OVERLAY_STUB, "entry overlay hook encode drift")

    changed = [i for i, (before, after) in enumerate(zip(parent, child)) if before != after]
    gate(changed and set(changed) <= set(range(entry_file, entry_file + 4)), "changes escaped entry BL")
    gate(child[OVERLAY_STUB_FILE:OVERLAY_STUB_FILE + len(stub)] == stub, "overlay stub changed")
    gate(child[OVERLAY_PAYLOAD_FILE:OVERLAY_PAYLOAD_FILE + OVERLAY_PAYLOAD_BYTES] == payload, "overlay payload changed")
    gate(thumb.thumb_bl_target(child, STEADY_TRANSFER_CALL) == OVERLAY_STUB, "steady overlay hook changed")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_ROM.write_bytes(child)
    shutil.copyfile(MAIN_SAV, OUT_SAV)
    gate(OUT_SAV.read_bytes() == MAIN_SAV.read_bytes(), "SAV copy drift")

    compile_result = subprocess.run(
        [sys.executable, "-m", "py_compile", str(Path(__file__).resolve())],
        cwd=ADVANCE_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    gate(compile_result.returncode == 0, f"py_compile failed: {compile_result.stderr}")

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_owned_count_entry_no_flash_candidate_20260905",
        "result": "PASS",
        "status": "test_candidate_main_tip_not_promoted",
        "translation": {"所有数": "소유수"},
        "source": {
            "path": advance_relative(MAIN_TIP_ROM),
            "sha256": sha256(parent),
            "promotion_reason": main_manifest.get("promotion_reason"),
        },
        "ownership": {
            "fixed_graphics_scan": "legacy/analysis/ggen_advance_owned_count_graphics_scan_20260904.json",
            "loaded_candidate_intersection": "legacy/analysis/ggen_advance_owned_count_loaded_candidates_20260905.json",
            "plaque_source_match": "legacy/analysis/ggen_advance_owned_count_plaque_source_match_20260905.json",
            "text_tile_owner": "legacy/analysis/ggen_advance_owned_count_text_tile_owner_20260905.json",
            "conclusion": (
                "0x08C4654C animation 8 supplies plaque chrome but zero glyph-bearing cells; "
                "the 所有数 glyph tiles are produced by the 0x0806CFC4 compositor family called at 0x0806D380."
            ),
        },
        "patch": {
            "entry_builder": "0x0806D350",
            "compositor_call": f"0x{COMPOSITOR_CALL:08X} -> 0x{COMPOSITOR:08X}",
            "entry_transfer_before": f"0x{ENTRY_TRANSFER_CALL:08X} -> 0x{ORIGINAL_TRANSFER:08X}",
            "entry_transfer_after": f"0x{ENTRY_TRANSFER_CALL:08X} -> 0x{OVERLAY_STUB:08X}",
            "steady_transfer_preserved": f"0x{STEADY_TRANSFER_CALL:08X} -> 0x{OVERLAY_STUB:08X}",
            "overlay_stub": f"0x{OVERLAY_STUB:08X}",
            "overlay_payload": f"0x{ROM_BASE + OVERLAY_PAYLOAD_FILE:08X}",
            "changed_bytes": len(changed),
            "changed_ranges": changed_ranges(changed),
            "flash_removal_rationale": (
                "The compositor, first BG2 transfer, and live-tile Korean rewrite now complete synchronously "
                "before 0x0806D384 returns, so there is no frame boundary at which the Japanese plaque is the completed entry result."
            ),
        },
        "output": {
            "path": advance_relative(OUT_ROM),
            "sha256": sha256(child),
            "size": len(child),
            "sav": advance_relative(OUT_SAV),
            "sav_sha256": sha256(OUT_SAV.read_bytes()),
        },
        "verification": {
            "result": "PASS",
            "main_tip_hash_verified": True,
            "entry_compositor_call_verified": True,
            "entry_original_transfer_verified": True,
            "approved_overlay_stub_byte_exact": True,
            "approved_overlay_payload_byte_exact": True,
            "steady_state_hook_preserved": True,
            "only_entry_bl_mutated": True,
            "py_compile": "PASS",
            "main_tip_not_modified": True,
            "original_sav_not_modified": True,
            "runtime_measurement": "pending user measurement of disposal-entry first frames",
        },
        "measurement_checkpoints": [
            "후보 ROM과 동봉 SAV로 부팅한다.",
            "개발 메뉴에서 처분을 선택하고 목록 진입 직후를 관찰한다.",
            "첫 프레임부터 플래크가 소유수이면 PASS; 所有数가 한 번이라도 보이면 FAIL.",
            "커서 이동 뒤에도 소유수가 유지되고 숫자 1 및 하단 보급포인트/총유닛수가 정상이어야 한다.",
        ],
    }
    MANIFEST.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "rom": advance_relative(OUT_ROM),
        "sha256": sha256(child),
        "sav": advance_relative(OUT_SAV),
        "changed_bytes": len(changed),
        "entry_hook": f"0x{ENTRY_TRANSFER_CALL:08X} -> 0x{OVERLAY_STUB:08X}",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
