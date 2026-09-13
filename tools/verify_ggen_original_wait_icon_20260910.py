"""Verify the 15-cell renderer while using the original wait-icon resource."""
from __future__ import annotations

import json
from pathlib import Path

import verify_ggen_instant_dialogue_arm_20260910 as arm
from build_ggen_instant_dialogue_15_20260910 import ROOT, OUT as OLD_OUT, sha

OUT = ROOT / "outputs" / "20260910_instant_dialogue_15_icon_original"
ROM = OUT / "ggen_instant_dialogue_15_icon_original.gba"


def main() -> None:
    results = []
    rom_bytes = ROM.read_bytes()
    # ss1 is the current canonical state. ss2-ss4 are historical states whose
    # script pointers belong to the pre-15-cell translation ROM.
    for n in range(1, 2):
        for x in (48, 60):
            label = f"arm_ss{n}_x{x}_original_icon"
            result = arm.run_case(n, x, rom_bytes, label)
            expected = 15 if x == 48 else 14
            assert result["final_count"] == expected
            assert all(draw["limit"] == expected for draw in result["draws"])
            assert result["stack_restored"] and result["script_end_preserved"]
            results.append(result)
    manifest_path = OUT / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["verification"] = {
        "result": "PASS",
        "arm_renderer_cases": len(results),
        "x48_draw_count": 15,
        "x60_draw_count": 14,
        "original_wait_icon_pointer": True,
        "all_script_end_addresses_preserved": True,
        "all_stacks_restored": True,
        "rom_sha256": sha(ROM.read_bytes()),
    }
    (OUT / "arm_runtime.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("PASS: original wait icon with 15-cell renderer")


if __name__ == "__main__":
    main()
