#!/usr/bin/env python3
"""Build an xdelta3 (VCDIFF) patch: clean 16 MiB Japan ROM → current 32 MiB main TIP.

VCDIFF COPYs unchanged bytes from the original 16 MiB image. The appended 16 MiB
half and in-place Korean edits are the patch payload. The original ROM is not
embedded.

Requires xdelta3 (pinned Windows 3.2.0 is fetched into ``tools/vendor``).
Apply with ``tools/apply_ggen_advance_main_tip_xdelta.py``.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from ggen_advance_project_paths import (  # noqa: E402
    DIST_ROOT,
    MAIN_TIP_MANIFEST,
    MAIN_TIP_ROM,
    MAIN_TIP_ROM_SIZE,
    ORIGINAL_ROM,
    ORIGINAL_ROM_SHA256,
    ORIGINAL_ROM_SIZE,
    advance_relative,
    dist_release_name,
    release_version,
)
from xdelta3_tool import (  # noqa: E402
    DEFAULT_APP_HEADER,
    SOURCE_WINDOW,
    TARGET_WINDOW,
    XdeltaError,
    decode_xdelta,
    encode_xdelta,
    identity,
    print_delta_info,
    resolve_xdelta3,
    sha256_bytes,
    sha256_file,
)

DEFAULT_NAME = dist_release_name()
# Fail closed if the encoder forgot ``-s`` and stuffed most of the 32 MiB TIP in.
MAX_PATCH_BYTES = 12 * 1024 * 1024


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original", type=Path, default=ORIGINAL_ROM)
    parser.add_argument("--tip", type=Path, default=MAIN_TIP_ROM)
    parser.add_argument("--out-dir", type=Path, default=DIST_ROOT)
    parser.add_argument("--name", type=str, default=DEFAULT_NAME)
    parser.add_argument("--release-version", type=str, default=None)
    parser.add_argument("--xdelta3", type=Path, default=None)
    parser.add_argument(
        "--armor",
        action="store_true",
        help="Keep xdelta 3.2 BLAKE3 armor (breaks older Delta Patcher builds)",
    )
    parser.add_argument(
        "--skip-roundtrip",
        action="store_true",
        help="Do not re-apply the patch for SHA verification",
    )
    args = parser.parse_args()

    original_path = args.original
    tip_path = args.tip
    if not original_path.is_file():
        raise SystemExit(f"original ROM missing: {original_path}")
    if not tip_path.is_file():
        raise SystemExit(f"main TIP missing: {tip_path}")

    original = original_path.read_bytes()
    tip = tip_path.read_bytes()
    if len(original) != ORIGINAL_ROM_SIZE:
        raise SystemExit(f"original size must be {ORIGINAL_ROM_SIZE}, got {len(original)}")
    if len(tip) != MAIN_TIP_ROM_SIZE:
        raise SystemExit(f"main TIP size must be {MAIN_TIP_ROM_SIZE}, got {len(tip)}")
    original_sha = sha256_bytes(original)
    if original_sha != ORIGINAL_ROM_SHA256:
        raise SystemExit(
            f"original SHA-256 mismatch: got {original_sha}, expected {ORIGINAL_ROM_SHA256}"
        )

    try:
        xdelta3 = resolve_xdelta3(args.xdelta3)
    except XdeltaError as exc:
        raise SystemExit(str(exc)) from exc

    args.out_dir.mkdir(parents=True, exist_ok=True)
    patch_path = args.out_dir / f"{args.name}.xdelta"
    try:
        encode_xdelta(
            xdelta3,
            original_path,
            tip_path,
            patch_path,
            armor=args.armor,
        )
    except XdeltaError as exc:
        raise SystemExit(str(exc)) from exc

    patch_prefix = patch_path.read_bytes()[:5]
    if len(patch_prefix) < 5 or patch_prefix[:4] != bytes.fromhex("D6C3C400"):
        raise SystemExit(f"invalid VCDIFF header in {patch_path}")
    vcd_header_indicator = patch_prefix[4]
    if vcd_header_indicator & 0x01:
        raise SystemExit(
            "xdelta compatibility regression: VCD_SECONDARY is set; "
            "xdeltaUI/older xdelta3 decoders may reject this patch"
        )
    if vcd_header_indicator & 0x04:
        raise SystemExit(
            "xdelta compatibility regression: VCD_APPHEADER is set; older xdeltaUI "
            "may misread filename metadata as an external-compression ID"
        )

    patch_size = patch_path.stat().st_size
    if patch_size > MAX_PATCH_BYTES:
        raise SystemExit(
            f"xdelta unexpectedly large ({patch_size} bytes); refuse to keep "
            f"{patch_path} (source-copy may have failed)"
        )

    hdr = ""
    try:
        hdr = print_delta_info(xdelta3, patch_path)
    except XdeltaError:
        hdr = ""

    roundtrip_ok = None
    if not args.skip_roundtrip:
        handle = tempfile.NamedTemporaryFile(prefix="ggen_advance_xdelta_rt_", suffix=".gba", delete=False)
        rebuilt_path = Path(handle.name)
        handle.close()
        try:
            decode_xdelta(xdelta3, original_path, patch_path, rebuilt_path)
            rebuilt = rebuilt_path.read_bytes()
            roundtrip_ok = rebuilt == tip
            if not roundtrip_ok:
                if len(rebuilt) != len(tip):
                    raise SystemExit(
                        f"xdelta round-trip size mismatch: got {len(rebuilt)} expected {len(tip)}"
                    )
                for index, (left, right) in enumerate(zip(rebuilt, tip)):
                    if left != right:
                        raise SystemExit(
                            f"xdelta round-trip mismatch at {index:#x}: "
                            f"got {left:02X} expected {right:02X}"
                        )
                raise SystemExit("xdelta round-trip mismatch")
        except XdeltaError as exc:
            raise SystemExit(str(exc)) from exc
        finally:
            try:
                os.unlink(rebuilt_path)
            except OSError:
                pass

    tip_sha = sha256_bytes(tip)
    patch_sha = sha256_file(patch_path)
    promotion_reason = None
    if MAIN_TIP_MANIFEST.is_file():
        manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
        promotion_reason = manifest.get("promotion_reason")
        manifest_sha = str(manifest.get("sha256") or "").lower()
        if manifest_sha and manifest_sha != tip_sha:
            raise SystemExit(
                f"main TIP SHA-256 {tip_sha} does not match manifest {manifest_sha}"
            )

    version = args.release_version or release_version()
    meta: dict[str, Any] = {
        "schema_version": 1,
        "kind": "ggen_advance_main_tip_xdelta",
        "generated_by": "tools/make_ggen_advance_main_tip_xdelta.py",
        "release_version": version,
        "name": args.name,
        "method": "xdelta3_vcdiff_from_16mib_original_to_32mib_tip",
        "xdelta3": {
            "path": (
                advance_relative(xdelta3)
                if xdelta3.resolve().is_relative_to(ROOT.resolve())
                else str(xdelta3)
            ),
            "armor": args.armor,
            "app_header": DEFAULT_APP_HEADER,
            "secondary": "disabled",
            "vcd_header_indicator": f"0x{vcd_header_indicator:02X}",
            "compatibility": (
                "plain VCDIFF: no secondary compression and no application header; "
                "xdeltaUI/older xdelta3 friendly"
            ),
            "level": 9,
            "source_window": SOURCE_WINDOW,
            "target_window": TARGET_WINDOW,
            "legacy_app_header": False,
        },
        "original": identity(original_path, original),
        "main_tip": identity(tip_path, tip),
        "promotion_reason": promotion_reason,
        "xdelta": {
            "path": advance_relative(patch_path) if patch_path.resolve().is_relative_to(ROOT.resolve()) else str(patch_path),
            "size": patch_size,
            "sha256": patch_sha,
        },
        "embeds_original_rom": False,
        "roundtrip_matches_main_tip": roundtrip_ok,
        "printhdrs": hdr.strip() or None,
        "apply": [
            "Use only a legally owned Japanese original 16 MiB GBA ROM, and keep a clean backup.",
            f"Verify original SHA-256 == {original_sha}",
            "Apply with Delta Patcher (xdelta3) or:",
            "python tools/apply_ggen_advance_main_tip_xdelta.py --original <original.gba> "
            f"--xdelta {advance_relative(patch_path) if patch_path.resolve().is_relative_to(ROOT.resolve()) else patch_path} "
            "--out <output.gba>",
            f"Expected output SHA-256 == {tip_sha}",
        ],
    }
    meta_path = args.out_dir / f"{args.name}_xdelta.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    patch_rel = patch_path.name
    readme_path = args.out_dir / f"{args.name}_XDELTA_README.md"
    readme_path.write_text(
        "\n".join(
            [
                f"# {args.name} xdelta",
                "",
                "**합법적으로 소유한 일본판 원본 16 MiB GBA ROM**에 적용하면 **32 MiB** 한국어 메인 TIP이 됩니다.",
                "",
                "원본 16 MiB는 파일 앞쪽에 그대로 두고, 추가 16 MiB(`0x01000000–0x01FFFFFF`)에",
                "한글 글꼴·텍스트를 붙입니다. xdelta3(VCDIFF)는 원본을 소스로 COPY하므로",
                "원본 ROM 바이트는 패치 파일에 들어가지 않습니다.",
                "",
                "## 입력",
                "",
                f"- 원본: `{original_path.name}` · 16 MiB · SHA-256 `{original_sha}`",
                f"- 메인 TIP: `{tip_path.name}` · 32 MiB · SHA-256 `{tip_sha}`",
                "",
                "## 패치",
                "",
                f"- 파일: `{patch_rel}`",
                f"- xdelta SHA-256: `{patch_sha}`",
                f"- 크기: **{patch_size}** bytes",
                f"- 원본 ROM 포함: **아니오** (`embeds_original_rom: false`)",
                f"- 16 MiB→32 MiB 라운드트립: **{roundtrip_ok}**",
                "",
                "## 적용",
                "",
                "### GUI (Delta Patcher 등 xdelta3 프론트엔드)",
                "",
                "1. 합법적으로 소유한 일본판 원본 16 MiB ROM 준비 및 백업",
                f"2. Original file = 원본 `.gba`, XDelta patch = `{patch_rel}`, Output = 새 32 MiB `.gba`",
                f"3. 결과 SHA-256이 `{tip_sha}`인지 확인",
                "",
                "xdelta **3.2 armor(BLAKE3)**, **VCDIFF secondary compression**,",
                "**application header**를 모두 끄고 plain VCDIFF로 인코딩했습니다.",
                "",
                "### CLI",
                "",
                "```bash",
                f"python tools/apply_ggen_advance_main_tip_xdelta.py --original \"{original_path.name}\" "
                f"--xdelta outputs/dist/{patch_rel} --out outputs/dist/ggen_advance_ko_from_xdelta.gba",
                "```",
                "",
                "또는:",
                "",
                "```bash",
                f"xdelta3 -d -f -s \"{original_path.name}\" outputs/dist/{patch_rel} "
                "outputs/dist/ggen_advance_ko_from_xdelta.gba",
                "```",
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    print(f"Wrote {patch_path}")
    print(f"Wrote {meta_path}")
    print(f"Wrote {readme_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
