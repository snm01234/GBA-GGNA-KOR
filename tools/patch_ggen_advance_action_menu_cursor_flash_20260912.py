#!/usr/bin/env python3
"""Stop the 1-frame see-through action-menu wells on D-pad cursor moves.

Do not promote this candidate.  Current main TIP stays byte-exact.

On cursor redraw (0x08015484) the original code DMA-fills BG0 at 0x0600D800
with tile 0, then 0x0801550C blits the 6-wide frame whose interior is atlas
tile 7 (all palette index 0) before restamping command labels.  Scanout can
display those empty wells, so 이동 and the other badges vanish for a frame
while the green chrome is already back.

This candidate:

* does not start that DMA fill (NOP the DMA3 enable at 0x080154A4);
* when the 5th argument to 0x0801550C is 0 (cursor refresh), skips the
  6-wide frame blit and jumps to the label loop so old button pixels stay
  until the matching 4x2 label overwrites them.

Menu open/slide still passes a non-zero 5th argument, so those paths keep
the original frame blit.  Command-0 empty-slot skipping is unchanged
because live 이동 is encoded as 0x10, not 0x00.
"""
from __future__ import annotations

import json
import shutil
import struct
import sys
from pathlib import Path

from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs

THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from ggen_advance_project_paths import MAIN_TIP_MANIFEST, MAIN_TIP_ROM, advance_relative
from patch_ggen_advance_intermission_text_consumers_20260904 import gate, sha256

OUT = ROOT / "outputs" / "20260912_ggen_advance_action_menu_cursor_flash"
WORK = OUT / "ggen_advance_action_menu_cursor_flash_candidate_20260912.gba"
MAIN_SAV = ROOT / "SD Gundam GGeneration Advance (Korean).sav"
ROM_BASE = 0x08000000
THUMB_NOP = bytes((0xC0, 0x46))

# cmp r0,#0 / beq +0 (to 0x08015536) inside 0x0801550C
BEQ_FRAME = 0x00015532
BEQ_OLD = bytes((0x00, 0xD0))
BEQ_NEW = bytes((0x13, 0xD0))  # beq 0x0801555C: skip frame blit, keep label loop

# str r1, [r2, #8] starts DMA3 fill of BG0
DMA_ENABLE = 0x000154A4
DMA_OLD = bytes((0x91, 0x60))


def u16(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def disasm(rom: bytes, addr: int, size: int) -> list[dict[str, str]]:
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    rows = []
    for ins in md.disasm(rom[addr - ROM_BASE : addr - ROM_BASE + size], addr):
        rows.append({"address": f"0x{ins.address:08X}", "op": f"{ins.mnemonic} {ins.op_str}"})
    return rows


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parent = MAIN_TIP_ROM.read_bytes()
    manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(parent) == str(manifest.get("sha256") or ""), "main TIP sha mismatch")
    gate(parent[BEQ_FRAME : BEQ_FRAME + 2] == BEQ_OLD, "0x08015532 beq encoding drift")
    gate(parent[DMA_ENABLE : DMA_ENABLE + 2] == DMA_OLD, "0x080154A4 DMA enable drift")
    gate(u16(parent, 0x00015530) == 0x2800, "cmp r0,#0 before frame-blit branch drift")
    gate(MAIN_SAV.exists(), "current main SAV missing")

    candidate = bytearray(parent)
    candidate[BEQ_FRAME : BEQ_FRAME + 2] = BEQ_NEW
    candidate[DMA_ENABLE : DMA_ENABLE + 2] = THUMB_NOP
    changed = [i for i, (a, b) in enumerate(zip(parent, candidate)) if a != b]
    # 0x08015532 second byte stays 0xD0 (beq); only the signed offset changes.
    allowed = {BEQ_FRAME, DMA_ENABLE, DMA_ENABLE + 1}
    gate(set(changed) == allowed, f"unexpected writes {sorted(set(changed) - allowed)}")
    gate(sha256(MAIN_TIP_ROM.read_bytes()) == sha256(parent), "main TIP mutated during patch")

    OUT.mkdir(parents=True, exist_ok=True)
    WORK.write_bytes(bytes(candidate))
    shutil.copy2(MAIN_SAV, WORK.with_suffix(".sav"))

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_action_menu_cursor_flash_candidate_20260912",
        "status": "candidate_not_promoted",
        "promotion": "not applied; current main TIP unchanged",
        "parent": {"path": advance_relative(MAIN_TIP_ROM), "sha256": sha256(parent)},
        "output": {"path": advance_relative(WORK), "sha256": sha256(bytes(candidate)), "size": len(candidate)},
        "sav": {"path": advance_relative(WORK.with_suffix(".sav")), "copied_from": advance_relative(MAIN_SAV)},
        "patches": [
            {
                "address": "0x08015532",
                "before": BEQ_OLD.hex(),
                "after": BEQ_NEW.hex(),
                "effect": "5th arg == 0 skips 6-wide frame blit (tile-7 wells) and goes to 0x0801555C label setup",
            },
            {
                "address": "0x080154A4",
                "before": DMA_OLD.hex(),
                "after": THUMB_NOP.hex(),
                "effect": "cursor refresh no longer DMA-fills BG0 0x0600D800 with tile 0",
            },
        ],
        "disasm_after": {
            "frame_branch": disasm(bytes(candidate), 0x0801552E, 0x38),
            "cursor_dma": disasm(bytes(candidate), 0x08015496, 0x20),
        },
        "verification": {
            "result": "PASS",
            "changed_bytes": len(changed),
            "only_two_thumb_instructions": True,
            "main_tip_unmodified": True,
            "runtime_emulator": "not run; static Thumb identity and allowlist only",
        },
        "test_plan": [
            "Load the candidate ROM and copied SAV, not main TIP.",
            "Open a unit action menu and move the D-pad up/down several times.",
            "Confirm 이동 and the other badges no longer vanish for a frame.",
            "Open/close the menu on both map sides and confirm chrome still appears.",
        ],
    }
    (OUT / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "result": "PASS",
                "output": report["output"],
                "sav": report["sav"],
                "verification": report["verification"],
                "promotion": report["promotion"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
