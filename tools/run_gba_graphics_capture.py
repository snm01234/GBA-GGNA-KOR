#!/usr/bin/env python3
"""Run the G Generation Advance graphics-only BizHawk/mGBA capture.

The capture records runtime graphics memory, not scenario/dialogue data:
VRAM, palette RAM, OAM, periodic work-RAM snapshots, graphics-target DMA
sources, optional graphics-bus write summaries, and deterministic framebuffer
screenshots.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROM = ROOT / "SD Gundam GGeneration Advance (Japan).gba"
DEFAULT_LUA = Path(__file__).with_name("gba_graphics_capture.lua")
DEFAULT_PROFILE = ROOT.parent / "out" / "bizhawk_profile"
DEFAULT_EMU = DEFAULT_PROFILE / "EmuHawk.exe"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_log(log_path: Path) -> dict[str, object]:
    domains: list[dict[str, object]] = []
    dumps: list[dict[str, object]] = []
    dma: list[dict[str, object]] = []
    dma_sources: list[dict[str, object]] = []
    bus_writes: list[dict[str, object]] = []
    screenshots: list[dict[str, object]] = []
    summary: dict[str, str] = {}
    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    for line in lines:
        fields = line.split("|")
        if not fields:
            continue
        kind = fields[0]
        if kind == "DOMAIN" and len(fields) >= 3:
            domains.append({"name": fields[1], "size": fields[2]})
        elif kind == "DUMP" and len(fields) >= 7:
            dumps.append(
                {
                    "frame": int(fields[1]),
                    "region": fields[2],
                    "path": fields[3],
                    "bytes": int(fields[4]),
                    "hash": fields[5],
                    "reason": fields[6],
                }
            )
        elif kind == "DMA" and len(fields) >= 9:
            dma.append(
                {
                    "frame": int(fields[1]),
                    "channel": int(fields[2]),
                    "source": fields[3],
                    "destination": fields[4],
                    "count": int(fields[5]),
                    "unit_bytes": int(fields[6]),
                    "bytes": int(fields[7]),
                    "control": fields[8],
                }
            )
        elif kind == "DMA_SRC" and len(fields) >= 8:
            dma_sources.append(
                {
                    "frame": int(fields[1]),
                    "channel": int(fields[2]),
                    "source": fields[3],
                    "destination": fields[4],
                    "bytes": int(fields[5]),
                    "domain": fields[6],
                    "path": fields[7],
                }
            )
        elif kind == "BUS_WRITE" and len(fields) >= 7:
            attributes: dict[str, str] = {}
            for item in fields[3:]:
                if "=" in item:
                    key, value = item.split("=", 1)
                    attributes[key] = value
            bus_writes.append(
                {
                    "frame": int(fields[1]),
                    "region": fields[2],
                    "count": int(attributes.get("count", "0")),
                    "min": attributes.get("min", ""),
                    "max": attributes.get("max", ""),
                    "samples": attributes.get("samples", ""),
                }
            )
        elif kind == "SHOT" and len(fields) >= 4:
            screenshots.append(
                {
                    "frame": int(fields[1]),
                    "label": fields[2],
                    "path": fields[3],
                    "status": "|".join(fields[4:]),
                }
            )
        elif kind == "SUMMARY" and len(fields) >= 2:
            for item in fields[1:]:
                if "=" in item:
                    key, value = item.split("=", 1)
                    summary[key] = value
    return {
        "domains": domains,
        "dumps": dumps,
        "dma": dma,
        "dma_sources": dma_sources,
        "bus_writes": bus_writes,
        "screenshots": screenshots,
        "summary": summary,
        "lines": len(lines),
    }


def choose_paths(profile: Path | None, emu: Path | None) -> tuple[Path, Path]:
    profile_path = (profile or DEFAULT_PROFILE).resolve()
    emu_path = (emu or (profile_path / "EmuHawk.exe")).resolve()
    if not emu_path.exists():
        packaged = (ROOT.parent / "BizHawk-2.11.1-win-x64" / "EmuHawk.exe").resolve()
        if packaged.exists():
            emu_path = packaged
            profile_path = packaged.parent
    return profile_path, emu_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--lua", type=Path, default=DEFAULT_LUA)
    parser.add_argument("--profile", type=Path, default=None, help="BizHawk working directory")
    parser.add_argument("--emu", type=Path, default=None, help="EmuHawk.exe")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "graphics_runtime_capture")
    parser.add_argument("--tag", default="original_graphics")
    parser.add_argument("--frames", type=int, default=4200)
    parser.add_argument("--input", choices=("scripted", "none"), default="scripted")
    parser.add_argument("--screen-every", type=int, default=120)
    parser.add_argument("--sample-every", type=int, default=1)
    parser.add_argument("--ram-every", type=int, default=120)
    parser.add_argument("--max-dma", type=int, default=0x20000)
    parser.add_argument(
        "--bus-trace",
        action="store_true",
        help="aggregate CPU writes to VRAM, palette RAM, OAM, and DMA registers",
    )
    parser.add_argument("--timeout", type=float, default=240.0)
    args = parser.parse_args()

    rom = args.rom.resolve()
    lua = args.lua.resolve()
    out_dir = args.out_dir.resolve()
    profile, emu = choose_paths(args.profile, args.emu)
    for path in (rom, lua, emu):
        if not path.is_file():
            raise SystemExit(f"missing input: {path}")
    if not profile.is_dir():
        raise SystemExit(f"missing BizHawk profile directory: {profile}")
    if args.frames < 0 or args.sample_every < 1:
        raise SystemExit("frames must be non-negative and sample-every must be positive")

    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / f"{args.tag}.log"
    env = dict(os.environ)
    env.update(
        {
            "GGA_CAPTURE_OUT": str(out_dir),
            "GGA_CAPTURE_TAG": args.tag,
            "GGA_CAPTURE_FRAMES": str(args.frames),
            "GGA_CAPTURE_INPUT": args.input,
            "GGA_CAPTURE_SCREEN_EVERY": str(args.screen_every),
            "GGA_CAPTURE_SAMPLE_EVERY": str(args.sample_every),
            "GGA_CAPTURE_RAM_EVERY": str(args.ram_every),
            "GGA_CAPTURE_MAX_DMA": str(args.max_dma),
            "GGA_CAPTURE_BUS_TRACE": "1" if args.bus_trace else "0",
        }
    )

    rom_digest = sha256(rom)
    started = time.time()
    process = subprocess.Popen(
        [str(emu), f"--lua={lua}", str(rom)],
        cwd=str(profile),
        env=env,
    )
    done = False
    deadline = started + args.timeout
    while time.time() < deadline:
        if log_path.exists():
            content = log_path.read_text(encoding="utf-8", errors="replace")
            if "DONE|" in content:
                done = True
                break
        if process.poll() is not None:
            break
        time.sleep(0.25)

    if process.poll() is None:
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    elapsed = round(time.time() - started, 1)

    if not log_path.exists():
        raise SystemExit(f"EmuHawk produced no log: {log_path}")
    parsed = parse_log(log_path)
    summary = parsed.pop("summary")
    report = {
        "schema_version": 1,
        # BizHawk may return a non-zero GUI process code after client.exit(),
        # even when the Lua script reached its explicit DONE marker.  The
        # marker is the authoritative completion signal for this harness;
        # retain the process code in the report for diagnostics.
        "result": "PASS" if done else "INCOMPLETE",
        "rom": {
            "path": str(rom),
            "bytes": rom.stat().st_size,
            "sha256": rom_digest,
        },
        "emulator": {
            "frontend": str(emu),
            "profile": str(profile),
            "core": str(profile / "dll" / "mgba.dll"),
            "expected_frontend": "BizHawk 2.11.1",
        },
        "capture": {
            "tag": args.tag,
            "input": args.input,
            "frames_requested": args.frames,
            "bus_trace": args.bus_trace,
            "elapsed_seconds": elapsed,
            "process_returncode": process.returncode,
            "log": str(log_path),
            "summary": summary,
            **parsed,
        },
    }
    report_path = out_dir / f"{args.tag}_runtime_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({"report": str(report_path), **report}, ensure_ascii=False, indent=2))
    return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
