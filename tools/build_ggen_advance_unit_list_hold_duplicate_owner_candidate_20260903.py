#!/usr/bin/env python3
"""Build an isolated current-main candidate fixing the remaining unit-list 持.

Runtime execution tracing on 2026-09-03 proved that the moving normal/focus row
uses callback index 8.  Those callbacks do not consume the already-translated
C439 descriptors directly: they point at compressed duplicate descriptors
C490B8/C4910C whose decoded Japanese graphics are byte-identical to the old
C439 B/A 持 graphics.

The safest fix is therefore pointer-only: redirect the four verified literals
for C490B8/C4910C to the already-approved Korean C439 B/A descriptors.  The two
descriptor pairs have identical geometry/map metadata; only the compression
flag differs.  No graphics, code, transfer hook, or main TIP is modified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import struct
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_action_graphics_scan_20260830 as lz  # noqa: E402

INPUT_ROM = ROOT / "SD Gundam GGeneration Advance (Korean).gba"
JP_ROM = ROOT / "SD Gundam GGeneration Advance (Japan).gba"
INPUT_SAV = ROOT / "SD Gundam GGeneration Advance (Korean).sav"
OUT_DIR = ROOT / "outputs" / "20260903_ggen_advance_unit_list_hold_duplicate_owner"
DEFAULT_OUT = OUT_DIR / "ggen_advance_unit_list_hold_duplicate_owner_candidate_20260903.gba"
DEFAULT_SAV = OUT_DIR / "ggen_advance_unit_list_hold_duplicate_owner_candidate_20260903.sav"
DEFAULT_MANIFEST = ROOT / "analysis" / "ggen_advance_unit_list_hold_duplicate_owner_candidate_20260903.json"

EXPECTED_INPUT_SHA256 = "84bffce9627ccf99a1fa98dfe11db5a945276ab688d225c844b99881606c875d"
EXPECTED_JP_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"
ROM_BASE = 0x08000000

TARGETS = {
    "normal_B": {
        "duplicate": 0x00C490B8,
        "approved_korean": 0x00C43954,
        "literal_refs": [0x080752E8, 0x08075450],
    },
    "focus_A": {
        "duplicate": 0x00C4910C,
        "approved_korean": 0x00C439A8,
        "literal_refs": [0x080758EC, 0x08075A54],
    },
}


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def u16(data: bytes, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def descriptor_info(data: bytes, off: int) -> dict:
    header = data[off : off + 0x14]
    gate(len(header) == 0x14, f"descriptor header truncated at 0x{off:08X}")
    flags = header[0]
    width = header[2]
    height = header[3]
    map_rel = u16(data, off + 4)
    gfx_rel = u16(data, off + 8)
    gfx_len = u16(data, off + 10)
    gate((width, height) == (1, 2), f"unexpected descriptor geometry at 0x{off:08X}: {width}x{height}")
    gate(map_rel == 0x10 and gfx_rel == 0x14, f"descriptor offsets drift at 0x{off:08X}")
    body = data[off + gfx_rel : off + gfx_rel + gfx_len]
    gate(len(body) == gfx_len, f"descriptor body truncated at 0x{off:08X}")
    if flags & 0x10:
        decoded = lz.lzss_decompress(body)
    else:
        decoded = body
    gate(len(decoded) == 64, f"descriptor 0x{off:08X} decoded to {len(decoded)} bytes, expected 64")
    return {
        "flags": flags,
        "width": width,
        "height": height,
        "map_rel": map_rel,
        "gfx_rel": gfx_rel,
        "gfx_len": gfx_len,
        "header": header,
        "map_cell": u16(data, off + map_rel),
        "decoded": decoded,
    }


def aligned_pointer_refs(data: bytes, pointer: int) -> list[int]:
    raw = struct.pack("<I", pointer)
    hits = []
    for off in range(0, len(data) - 3, 4):
        if data[off : off + 4] == raw:
            hits.append(ROM_BASE + off)
    return hits


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", type=Path, default=INPUT_ROM)
    ap.add_argument("--jp", type=Path, default=JP_ROM)
    ap.add_argument("--sav", type=Path, default=INPUT_SAV)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--out-sav", type=Path, default=DEFAULT_SAV)
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = ap.parse_args()

    source = args.input.read_bytes()
    jp = args.jp.read_bytes()
    gate(len(source) == 32 * 1024 * 1024, "current main must be 32 MiB")
    gate(sha256(source) == EXPECTED_INPUT_SHA256, f"current main hash drift: {sha256(source)}")
    gate(sha256(jp) == EXPECTED_JP_SHA256, f"Japanese ROM hash drift: {sha256(jp)}")
    gate(args.sav.exists(), "current main SAV missing")

    candidate = bytearray(source)
    reports = []
    allowed = set()

    for name, spec in TARGETS.items():
        dup = int(spec["duplicate"])
        ko = int(spec["approved_korean"])
        dup_addr = ROM_BASE + dup
        ko_addr = ROM_BASE + ko
        refs = [int(x) for x in spec["literal_refs"]]

        current_dup = descriptor_info(source, dup)
        current_ko = descriptor_info(source, ko)
        jp_dup = descriptor_info(jp, dup)
        jp_ko = descriptor_info(jp, ko)

        # The duplicate is still Japanese and is exactly the old C439 art.
        gate(current_dup["decoded"] == jp_dup["decoded"], f"{name} duplicate already changed")
        gate(jp_dup["decoded"] == jp_ko["decoded"], f"{name} duplicate is not byte-identical to Japanese C439")
        # The approved C439 target must already differ from Japanese and retain
        # identical descriptor geometry/map metadata except compression flag.
        gate(current_ko["decoded"] != jp_ko["decoded"], f"{name} approved C439 target is not Korean")
        gate(current_dup["header"][1:] == current_ko["header"][1:], f"{name} descriptor metadata differs beyond flags")
        gate((current_dup["flags"] ^ current_ko["flags"]) == 0x10, f"{name} expected only compression-flag difference")
        gate(current_dup["map_cell"] == current_ko["map_cell"], f"{name} descriptor map cell differs")

        actual_refs = aligned_pointer_refs(source, dup_addr)
        gate(actual_refs == refs, f"{name} duplicate refs drift: {[hex(x) for x in actual_refs]}")
        for addr in refs:
            off = addr - ROM_BASE
            gate(u32(source, off) == dup_addr, f"{name} pointer drift at 0x{addr:08X}")
            struct.pack_into("<I", candidate, off, ko_addr)
            allowed.update(range(off, off + 4))

        reports.append({
            "variant": name,
            "duplicate_descriptor": f"0x{dup_addr:08X}",
            "approved_korean_descriptor": f"0x{ko_addr:08X}",
            "literal_refs_redirected": [f"0x{x:08X}" for x in refs],
            "duplicate_decoded_sha256": sha256(current_dup["decoded"]),
            "approved_korean_decoded_sha256": sha256(current_ko["decoded"]),
            "japanese_c439_decoded_sha256": sha256(jp_ko["decoded"]),
            "metadata_byte_exact_except_compression_flag": True,
            "map_cell": f"0x{current_dup['map_cell']:04X}",
        })

    diff = [i for i, (a, b) in enumerate(zip(source, candidate)) if a != b]
    gate(diff, "candidate has no changes")
    gate(all(i in allowed for i in diff), f"changes escaped four pointer literals: {[hex(i) for i in diff if i not in allowed][:16]}")
    # Prove the target resources themselves were not altered.
    for spec in TARGETS.values():
        for key in ("duplicate", "approved_korean"):
            off = int(spec[key])
            gate(candidate[off : off + 0x54] == source[off : off + 0x54], f"resource bytes changed at 0x{off:08X}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(candidate)
    shutil.copyfile(args.sav, args.out_sav)

    manifest = {
        "schema_version": 1,
        "kind": "ggen_advance_unit_list_hold_duplicate_owner_candidate_20260903",
        "result": "PASS",
        "source": {"path": str(args.input.relative_to(ROOT)), "sha256": sha256(source), "size": len(source)},
        "output": {"path": str(args.out.relative_to(ROOT)), "sha256": sha256(candidate), "size": len(candidate)},
        "sav": {"path": str(args.out_sav.relative_to(ROOT)), "sha256": sha256(args.out_sav.read_bytes()), "byte_exact_copy": args.out_sav.read_bytes() == args.sav.read_bytes()},
        "runtime_evidence": {
            "trace_states": [
                "outputs/20260903_ggen_advance_unit_list_execution_trace/ggen_advance_unit_list_execution_trace_candidate_20260903.ss1",
                "outputs/20260903_ggen_advance_unit_list_execution_trace/ggen_advance_unit_list_execution_trace_candidate_20260903.ss2",
                "outputs/20260903_ggen_advance_unit_list_execution_trace/ggen_advance_unit_list_execution_trace_candidate_20260903.ss3"
            ],
            "active_callback_index": 8,
            "normal_callback_owner": "0x08075258 family -> literal 0x080752E8/0x08075450 -> 0x08C490B8",
            "focus_callback_owner": "0x0807585C family -> literal 0x080758EC/0x08075A54 -> 0x08C4910C",
            "finding": "Decoded C490B8/C4910C graphics are byte-exact Japanese C439 B/A duplicates; redirect them to the already-approved Korean C439 B/A descriptors."
        },
        "variants": reports,
        "verification": {
            "result": "PASS",
            "current_main_hash_verified": True,
            "jp_hash_verified": True,
            "exact_duplicate_pointer_ref_sets_verified": True,
            "duplicate_resources_unchanged": True,
            "approved_korean_resources_unchanged": True,
            "only_four_pointer_literals_mutated": True,
            "changed_byte_count": len(diff),
            "main_tip_not_modified": True,
            "runtime_measurement": "pending user verification"
        },
        "measurement_checkpoints": [
            "On the unit list, Aile Strike selected/focused row should show 지 instead of 持.",
            "Move focus to MC Gundam and back; both normal and focused variants should remain 지.",
            "The adjacent c/suffix and previously translated detail/status graphics must remain unchanged."
        ]
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "result": "PASS",
        "output": str(args.out),
        "sha256": sha256(candidate),
        "sav": str(args.out_sav),
        "manifest": str(args.manifest),
        "changed_bytes": len(diff),
        "changed_ranges": [f"0x{min(allowed):08X}..0x{max(allowed)+1:08X}"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
