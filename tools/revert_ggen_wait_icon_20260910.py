"""Remove only the private wait-icon relocation from the approved 15-cell ROM."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT / "SD Gundam GGeneration Advance (Korean).gba"
OUT_DIR = ROOT / "outputs" / "20260910_instant_dialogue_15_icon_original"
OUT_ROM = OUT_DIR / "ggen_instant_dialogue_15_icon_original.gba"
HOOK_CAVE = (0x012B4000, 0x012B4100)
ICON_CLONE = (0x012B4100, 0x012B4710)
ICON_POINTER_OFFSET = 0x00011198
ICON_SOURCE = 0x000CAFF4


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    parent = PARENT.read_bytes()
    candidate = bytearray(parent)
    # Keep the 15-cell renderer hook and its code cave. Remove the relocated
    # animation asset and point the original loader back at the stock asset.
    candidate[ICON_CLONE[0] : ICON_CLONE[1]] = b"\x00" * (ICON_CLONE[1] - ICON_CLONE[0])
    candidate[ICON_POINTER_OFFSET : ICON_POINTER_OFFSET + 4] = (0x08000000 + ICON_SOURCE).to_bytes(4, "little")
    changed = [i for i, (a, b) in enumerate(zip(parent, candidate)) if a != b]
    expected = set(range(ICON_CLONE[0], ICON_CLONE[1])) | set(range(ICON_POINTER_OFFSET, ICON_POINTER_OFFSET + 4))
    assert set(changed) <= expected
    assert any(i in changed for i in range(ICON_CLONE[0], ICON_CLONE[1]))
    assert any(i in changed for i in range(ICON_POINTER_OFFSET, ICON_POINTER_OFFSET + 4))
    assert candidate[0xD7A8:0xD7B0] == parent[0xD7A8:0xD7B0]
    assert candidate[HOOK_CAVE[0] : HOOK_CAVE[1]] == parent[HOOK_CAVE[0] : HOOK_CAVE[1]]
    assert candidate[ICON_POINTER_OFFSET : ICON_POINTER_OFFSET + 4] == (0x08000000 + ICON_SOURCE).to_bytes(4, "little")
    assert candidate[0x00F00000:0x00FC0000] == parent[0x00F00000:0x00FC0000]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_ROM.write_bytes(candidate)
    manifest = {
        "kind": "instant_dialogue_15_original_wait_icon",
        "parent": {"path": str(PARENT.relative_to(ROOT)), "sha256": sha(parent)},
        "output": {"path": str(OUT_ROM.relative_to(ROOT)), "size": len(candidate), "sha256": sha(candidate)},
        "reverted": {
            "icon_pointer_offset": hex(ICON_POINTER_OFFSET),
            "icon_pointer_value": hex(0x08000000 + ICON_SOURCE),
            "private_clone_range": [hex(ICON_CLONE[0]), hex(ICON_CLONE[1])],
            "15_cell_hook_preserved": True,
            "map_script_bank_preserved": True,
        },
        "verification": {"result": "PENDING"},
    }
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
