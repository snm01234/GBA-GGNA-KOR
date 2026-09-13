#!/usr/bin/env python3
"""Apply the approved live-tile 소유수 overlay across the supply entry wait.

The first 0x0806D384 transfer queues/starts the BG update.  The following
0x0806D398 call is inside the wait loop for 0x0300177C == 2.  Hook both calls
so the existing dynamic tile-ID overlay is retried until the transferred
plaque is actually resident in BG2 VRAM.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import build_ggen_advance_owned_count_ab_candidates_20260903 as thumb
import build_ggen_advance_owned_count_live_overlay_candidate_20260904 as overlay
from ggen_advance_project_paths import ADVANCE_ROOT, MAIN_TIP_MANIFEST, MAIN_TIP_ROM, advance_relative

EXPECTED_MAIN_SHA256 = "f4ec36f115ea03af0b8f40f84686a5f6f5b2b5526e5d857b84703a3bcc8c3db4"
MAIN_SAV = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).sav"
OUT_DIR = ADVANCE_ROOT / "outputs" / "20260905_ggen_advance_owned_count_supply_live"
OUT_ROM = OUT_DIR / "ggen_advance_owned_count_supply_live_candidate_20260905.gba"
OUT_SAV = OUT_DIR / "ggen_advance_owned_count_supply_live_candidate_20260905.sav"
MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_owned_count_supply_live_candidate_20260905.json"

ROM_BASE = 0x08000000
COMPOSITOR_CALL = 0x0806D380
COMPOSITOR = 0x0806CFC4
ENTRY_TRANSFER_CALLS = (0x0806D384, 0x0806D398)
ORIGINAL_TRANSFER = 0x08063194
TRANSFER_STATUS = 0x0300177C
TRANSFER_COMPLETE = 2
STEADY_TRANSFER_CALL = 0x0806EB3E
OVERLAY_STUB = overlay.STUB_ADDR


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    parent = MAIN_TIP_ROM.read_bytes()
    main_manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(parent) == EXPECTED_MAIN_SHA256, f"main TIP hash drift: {sha256(parent)}")
    gate(main_manifest.get("sha256") == EXPECTED_MAIN_SHA256, "main manifest hash drift")
    gate(MAIN_SAV.is_file(), "main SAV missing")
    gate(thumb.thumb_bl_target(parent, COMPOSITOR_CALL) == COMPOSITOR, "supply compositor call drift")
    for site in ENTRY_TRANSFER_CALLS:
        gate(thumb.thumb_bl_target(parent, site) == ORIGINAL_TRANSFER, f"supply transfer call drift @0x{site:08X}")
    gate(thumb.thumb_bl_target(parent, STEADY_TRANSFER_CALL) == OVERLAY_STUB, "approved disposal/steady hook missing")

    stub = overlay.build_stub_clean()
    gate(parent[overlay.STUB_FILE:overlay.STUB_FILE + len(stub)] == stub, "approved overlay stub drift")
    payload = parent[overlay.PAYLOAD_FILE:overlay.PAYLOAD_FILE + 10 * 32]
    gate(any(payload), "approved 소유수 payload blank")

    child = bytearray(parent)
    allowed: set[int] = set()
    for site in ENTRY_TRANSFER_CALLS:
        off = site - ROM_BASE
        child[off:off + 4] = thumb.encode_thumb_bl(site, OVERLAY_STUB)
        allowed.update(range(off, off + 4))
        gate(thumb.thumb_bl_target(child, site) == OVERLAY_STUB, f"supply live hook encode drift @0x{site:08X}")

    changed = [i for i, (before, after) in enumerate(zip(parent, child)) if before != after]
    gate(changed and set(changed) <= allowed, "changes escaped two supply transfer BLs")
    gate(child[overlay.STUB_FILE:overlay.STUB_FILE + len(stub)] == stub, "overlay stub changed")
    gate(child[overlay.PAYLOAD_FILE:overlay.PAYLOAD_FILE + len(payload)] == payload, "overlay payload changed")
    gate(thumb.thumb_bl_target(child, STEADY_TRANSFER_CALL) == OVERLAY_STUB, "steady hook changed")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_ROM.write_bytes(child)
    shutil.copyfile(MAIN_SAV, OUT_SAV)
    gate(OUT_SAV.read_bytes() == MAIN_SAV.read_bytes(), "SAV copy drift")
    compiled = subprocess.run(
        [sys.executable, "-m", "py_compile", str(Path(__file__).resolve())],
        cwd=ADVANCE_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    gate(compiled.returncode == 0, f"py_compile failed: {compiled.stderr}")

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_owned_count_supply_live_candidate_20260905",
        "result": "PASS",
        "status": "test_candidate_main_tip_not_promoted",
        "translation": {"所有数": "소유수"},
        "source": {
            "path": advance_relative(MAIN_TIP_ROM),
            "sha256": sha256(parent),
            "promotion_reason": main_manifest.get("promotion_reason"),
        },
        "patch": {
            "compositor": f"0x{COMPOSITOR_CALL:08X} -> 0x{COMPOSITOR:08X}",
            "entry_transfer_hooks": [f"0x{site:08X} -> 0x{OVERLAY_STUB:08X}" for site in ENTRY_TRANSFER_CALLS],
            "steady_disposal_hook_preserved": f"0x{STEADY_TRANSFER_CALL:08X} -> 0x{OVERLAY_STUB:08X}",
            "transfer_wait_condition": f"[0x{TRANSFER_STATUS:08X}] == {TRANSFER_COMPLETE}",
            "why_previous_candidate_had_no_effect": (
                "0x0806D384 can return while the new screenblock is still queued; the overlay gate then sees stale VRAM. "
                "0x0806D398 is retried inside the transfer-completion wait and can observe the live plaque tile IDs."
            ),
            "changed_bytes": len(changed),
            "changed_offsets": [f"0x{value:08X}" for value in changed],
        },
        "flash_condition": {
            "candidate_condition": (
                "BG2CNT=0x5D0A and palette-B plaque corners are present after a 0x08063194 iteration, "
                "while transfer status 0x0300177C has not yet advanced past the entry wait."
            ),
            "expected_effect": (
                "The live-tile rewrite runs in the same wait iteration that first exposes the plaque; "
                "this is the earliest existing dynamic-tile boundary available without patching the hidden text source."
            ),
            "runtime_verdict": "pending first-frame observation",
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
            "both_supply_transfer_calls_verified": True,
            "approved_overlay_byte_exact": True,
            "steady_disposal_hook_preserved": True,
            "only_two_supply_BLs_mutated": True,
            "py_compile": "PASS",
            "main_tip_not_modified": True,
            "runtime_measurement": "pending supply-screen and entry-flash measurement",
        },
        "measurement_checkpoints": [
            "후보 ROM과 동봉 SAV로 부팅하고 보급 화면에 진입한다.",
            "보급 화면의 所有数가 최종적으로 소유수로 바뀌는지 확인한다.",
            "보급 진입 첫 순간에 所有数 플래시가 남는지 관찰한다.",
            "처분 화면과 커서 이동 뒤에도 소유수가 유지되는지 확인한다.",
            "숫자 1, 보급포인트, 총유닛수 및 다른 BG 요소가 정상이어야 한다.",
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
        "hooks": [f"0x{site:08X} -> 0x{OVERLAY_STUB:08X}" for site in ENTRY_TRANSFER_CALLS],
        "flash_condition": report["flash_condition"]["candidate_condition"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
