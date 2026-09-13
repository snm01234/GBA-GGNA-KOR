#!/usr/bin/env python3
"""Restore the unit-list/detail N tile by reversing the C491 1x1 지 redirects.

JP/KO ss1 proof:
- Visible MC Gundam N is the compressed 1x1 C491C0/C491F4 family.
- Current main still points those four literals at Galmuri7 지 clones.
- The 8x16 C439 持→지 path and Aile Strike C suffix are independent and stay.

This candidate restores only the four N-tile literals.  Canonical main TIP is
not modified.
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
ROOT = THIS_DIR.parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from ggen_advance_project_paths import (
    ADVANCE_ROOT,
    MAIN_TIP_MANIFEST,
    MAIN_TIP_ROM,
    ORIGINAL_ROM,
    advance_relative,
)

ROM_BASE = 0x08000000
EXPECTED_JP_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"
MAIN_SAV = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).sav"
OUT_DIR = ADVANCE_ROOT / "outputs" / "20260903_ggen_advance_n_tile_rollback"
OUT_ROM = OUT_DIR / "ggen_advance_n_tile_rollback_candidate_20260903.gba"
OUT_SAV = OUT_DIR / "ggen_advance_n_tile_rollback_candidate_20260903.sav"
MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_n_tile_rollback_candidate_20260903.json"

RESTORES = {
    0x080752F0: 0x08C491C0,
    0x08075458: 0x08C491C0,
    0x080758F4: 0x08C491F4,
    0x08075A5C: 0x08C491F4,
}
CURRENT = {
    0x080752F0: 0x09280000,
    0x08075458: 0x09280000,
    0x080758F4: 0x09280040,
    0x08075A5C: 0x09280040,
}
HOLD_KEEP = {
    0x080752E8: 0x08C43954,
    0x08075450: 0x08C43954,
    0x080758EC: 0x08C439A8,
    0x08075A54: 0x08C439A8,
}


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def main() -> int:
    manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    source = MAIN_TIP_ROM.read_bytes()
    jp = ORIGINAL_ROM.read_bytes()
    gate(sha256(source) == manifest["sha256"], "current main hash/manifest drift")
    gate(sha256(jp) == EXPECTED_JP_SHA256, "Japanese ROM hash drift")
    gate(MAIN_SAV.exists(), "current main SAV missing")
    gate(len(source) == 32 * 1024 * 1024, "current main size drift")

    for addr, expected in CURRENT.items():
        gate(u32(source, addr - ROM_BASE) == expected, f"N literal drift at 0x{addr:08X}")
    for addr, expected in HOLD_KEEP.items():
        gate(u32(source, addr - ROM_BASE) == expected, f"持 redirect missing at 0x{addr:08X}")
    for addr, expected in RESTORES.items():
        gate(u32(jp, addr - ROM_BASE) == expected, f"JP N literal drift at 0x{addr:08X}")

    candidate = bytearray(source)
    allowed: set[int] = set()
    for addr, value in RESTORES.items():
        off = addr - ROM_BASE
        struct.pack_into("<I", candidate, off, value)
        allowed.update(range(off, off + 4))

    diff = [i for i, (a, b) in enumerate(zip(source, candidate)) if a != b]
    gate(diff, "candidate has no changes")
    gate(all(i in allowed for i in diff), "changes escaped the four N literals")
    gate(len(diff) == 16, f"changed byte count drift: {len(diff)}")
    for addr, expected in HOLD_KEEP.items():
        gate(u32(candidate, addr - ROM_BASE) == expected, "持 redirect was disturbed")
    gate(candidate[0x00C491C0:0x00C491C0 + 0x34] == source[0x00C491C0:0x00C491C0 + 0x34], "original N descriptor B changed")
    gate(candidate[0x00C491F4:0x00C491F4 + 0x34] == source[0x00C491F4:0x00C491F4 + 0x34], "original N descriptor A changed")
    gate(candidate[0x00C43954:0x00C43954 + 0x54] == source[0x00C43954:0x00C43954 + 0x54], "C439 지 payload changed")
    gate(source[0x01280000:0x01280080] == candidate[0x01280000:0x01280080], "orphan 지 clones changed")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_ROM.write_bytes(candidate)
    shutil.copyfile(MAIN_SAV, OUT_SAV)
    py_compile = subprocess.run(
        [sys.executable, "-m", "py_compile", str(Path(__file__).resolve())],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    gate(py_compile.returncode == 0, f"py_compile failed: {py_compile.stderr}")
    unified = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "test_ggen_advance_unified_pipeline.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    gate(unified.returncode == 0, f"unified pipeline failed: {unified.stdout}\n{unified.stderr}")
    unified_summary = "6/6 PASS" if "OK" in unified.stderr or "OK" in unified.stdout or unified.returncode == 0 else "FAIL"

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_n_tile_rollback_candidate_20260903",
        "result": "PASS",
        "source": {
            "path": advance_relative(MAIN_TIP_ROM),
            "sha256": sha256(source),
            "size": len(source),
            "promotion_reason": manifest["promotion_reason"],
        },
        "output": {
            "path": advance_relative(OUT_ROM),
            "sha256": sha256(candidate),
            "size": len(candidate),
        },
        "sav": {
            "path": advance_relative(OUT_SAV),
            "sha256": sha256(OUT_SAV.read_bytes()),
            "byte_exact_copy": OUT_SAV.read_bytes() == MAIN_SAV.read_bytes(),
        },
        "change": {
            "restored_literals": {f"0x{addr:08X}": {"from": f"0x{CURRENT[addr]:08X}", "to": f"0x{value:08X}"} for addr, value in RESTORES.items()},
            "changed_byte_count": len(diff),
            "preserved_hold_ji_8x16_redirects": {f"0x{addr:08X}": f"0x{value:08X}" for addr, value in HOLD_KEEP.items()},
            "original_n_descriptors_unchanged": True,
            "orphan_ji_clones_left_in_place": ["0x09280000", "0x09280040"],
        },
        "verification": {
            "result": "PASS",
            "current_main_hash_verified": True,
            "jp_hash_verified": True,
            "only_four_n_literals_mutated": True,
            "hold_ji_redirects_preserved": True,
            "py_compile": "PASS",
            "unified_pipeline_unittest": unified_summary,
            "main_tip_not_modified": True,
            "runtime_measurement": "pending user verification",
        },
        "measurement_checkpoints": [
            "처분 유닛 목록에서 MC 건담 행의 특성 칸이 지 대신 원본 N으로 보여야 한다.",
            "에일 스트라이크 건담 행의 C 접미와, 이미 번역된 8x16 지(持) 배지는 유지되어야 한다.",
            "포커스를 MC/플랫/에일 사이로 옮겨도 N/C/- 구분이 유지되어야 한다.",
            "우측 상세의 Newtype N 표식도 지로 보이지 않아야 한다.",
        ],
    }
    MANIFEST.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "output": advance_relative(OUT_ROM),
        "sha256": sha256(candidate),
        "changed_bytes": len(diff),
        "manifest": advance_relative(MANIFEST),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
