#!/usr/bin/env python3
"""Production-oriented 32 MiB append layout and allocator for G Generation Advance.

The original ROM occupies file offsets 0x00000000-0x00FFFFFF.  The appended
16 MiB half occupies 0x01000000-0x01FFFFFF and maps linearly to GBA addresses
0x09000000-0x09FFFFFF.

This module does not patch a ROM.  It provides deterministic allocation,
overlap/range checks and a JSON-serializable manifest that future extract/rebuild
and translation tools can share.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, asdict


ROM_BASE = 0x08000000
ORIGINAL_END = 0x01000000
APPEND_START = 0x01000000
APPEND_END = 0x02000000

# Production partition.  The sizes are intentionally generous relative to the
# current ~0.4 MiB conservative localization projection.  They are policy, not a
# GBA hardware requirement, and can be versioned later if a category outgrows its
# region.
REGIONS = {
    "static": (0x01000000, 0x01040000),   # 256 KiB: fonts/dicts/charmap/static tables
    "text": (0x01040000, 0x01240000),     # 2 MiB: relocated token streams
    "graphics": (0x01240000, 0x01640000), # 4 MiB: translated image/tile assets
    "future": (0x01640000, 0x01F00000),   # 8.75 MiB: overflow/new subsystems
    "metadata": (0x01F00000, 0x02000000), # 1 MiB: build/debug maps, optional ROM metadata
}

DEFAULT_ALIGNMENTS = {
    "static": 0x20,
    "text": 4,
    "graphics": 0x20,
    "future": 0x20,
    "metadata": 0x10,
}


class LayoutError(ValueError):
    pass


def align_up(value: int, alignment: int) -> int:
    if alignment <= 0 or alignment & (alignment - 1):
        raise LayoutError(f"alignment must be a positive power of two: {alignment}")
    return (value + alignment - 1) & ~(alignment - 1)


def gba_address(file_offset: int) -> int:
    if not 0 <= file_offset < APPEND_END:
        raise LayoutError(f"file offset outside 32 MiB ROM: 0x{file_offset:08X}")
    return ROM_BASE + file_offset


@dataclass(frozen=True)
class Allocation:
    name: str
    region: str
    file_offset: int
    size: int
    alignment: int
    category: str
    source: str | None = None
    notes: str | None = None

    @property
    def end_exclusive(self) -> int:
        return self.file_offset + self.size

    @property
    def address(self) -> int:
        return gba_address(self.file_offset)

    def to_manifest(self) -> dict[str, object]:
        return {
            "name": self.name,
            "category": self.category,
            "region": self.region,
            "file_offset": f"0x{self.file_offset:08X}",
            "end_exclusive": f"0x{self.end_exclusive:08X}",
            "gba_address": f"0x{self.address:08X}",
            "size": self.size,
            "alignment": self.alignment,
            "source": self.source,
            "notes": self.notes,
        }


class AppendAllocator:
    def __init__(self) -> None:
        self._cursor = {name: start for name, (start, _end) in REGIONS.items()}
        self._allocations: list[Allocation] = []
        self._names: set[str] = set()

    @property
    def allocations(self) -> tuple[Allocation, ...]:
        return tuple(self._allocations)

    def allocate(
        self,
        name: str,
        size: int,
        *,
        region: str,
        category: str,
        alignment: int | None = None,
        source: str | None = None,
        notes: str | None = None,
    ) -> Allocation:
        if name in self._names:
            raise LayoutError(f"duplicate allocation name: {name}")
        if region not in REGIONS:
            raise LayoutError(f"unknown region: {region}")
        if size <= 0:
            raise LayoutError(f"allocation {name} must have positive size")
        if alignment is None:
            alignment = DEFAULT_ALIGNMENTS[region]
        start, end = REGIONS[region]
        offset = align_up(self._cursor[region], alignment)
        finish = offset + size
        if finish > end:
            raise LayoutError(
                f"region {region} overflow allocating {name}: "
                f"0x{offset:08X}+0x{size:X} > 0x{end:08X}"
            )
        allocation = Allocation(
            name=name,
            region=region,
            file_offset=offset,
            size=size,
            alignment=alignment,
            category=category,
            source=source,
            notes=notes,
        )
        self._allocations.append(allocation)
        self._names.add(name)
        self._cursor[region] = finish
        self.validate()
        return allocation

    def validate(self) -> None:
        ordered = sorted(self._allocations, key=lambda item: item.file_offset)
        for item in ordered:
            region_start, region_end = REGIONS[item.region]
            if not (APPEND_START <= item.file_offset < item.end_exclusive <= APPEND_END):
                raise LayoutError(f"allocation outside appended half: {item.name}")
            if not (region_start <= item.file_offset < item.end_exclusive <= region_end):
                raise LayoutError(f"allocation outside region {item.region}: {item.name}")
            if item.file_offset % item.alignment:
                raise LayoutError(f"misaligned allocation: {item.name}")
        for left, right in zip(ordered, ordered[1:]):
            if left.end_exclusive > right.file_offset:
                raise LayoutError(f"overlap: {left.name} and {right.name}")

    def region_summary(self) -> dict[str, dict[str, object]]:
        result: dict[str, dict[str, object]] = {}
        for name, (start, end) in REGIONS.items():
            used = sum(item.size for item in self._allocations if item.region == name)
            cursor = self._cursor[name]
            padding = max(0, cursor - start - used)
            result[name] = {
                "start": f"0x{start:08X}",
                "end_exclusive": f"0x{end:08X}",
                "gba_start": f"0x{gba_address(start):08X}",
                "capacity": end - start,
                "used_payload": used,
                "alignment_padding": padding,
                "high_water": f"0x{cursor:08X}",
                "remaining_after_high_water": end - cursor,
                "payload_utilization_percent": round(used * 100 / (end - start), 3),
            }
        return result

    def manifest(self) -> dict[str, object]:
        self.validate()
        total_payload = sum(item.size for item in self._allocations)
        return {
            "schema_version": 1,
            "rom_mapping": {
                "original_file_range": "0x00000000-0x00FFFFFF",
                "append_file_range": "0x01000000-0x01FFFFFF",
                "append_gba_range": "0x09000000-0x09FFFFFF",
                "formula": "gba_address = 0x08000000 + file_offset",
            },
            "regions": self.region_summary(),
            "allocations": [item.to_manifest() for item in self._allocations],
            "totals": {
                "append_capacity": APPEND_END - APPEND_START,
                "allocated_payload": total_payload,
                "allocated_payload_percent": round(
                    total_payload * 100 / (APPEND_END - APPEND_START), 4
                ),
            },
        }


def make_reference_plan() -> AppendAllocator:
    """Allocate a conservative whole-localization reference budget.

    This is not final content.  It proves the production partition has ample
    capacity using the current static measurements:
      * both complete original-format fonts;
      * both 319-entry dictionaries at their current sizes;
      * 16 KiB charmap/encoding metadata budget;
      * 320 KiB text budget (slightly above the 298,134 B 1.4x projection);
      * 2 MiB translated graphics budget;
      * 64 KiB optional build metadata.
    """
    a = AppendAllocator()
    a.allocate(
        "font_12x12",
        35856,
        region="static",
        category="font",
        source="original 0x0008AC40",
    )
    a.allocate(
        "font_8x16",
        66176,
        region="static",
        category="font",
        source="original 0x00094028",
    )
    a.allocate(
        "dictionary_8x16",
        1924,
        region="static",
        category="dictionary",
        source="original 0x000A42A8-0x000A4A2C",
    )
    a.allocate(
        "dictionary_12x12",
        1928,
        region="static",
        category="dictionary",
        source="original 0x00093850-0x00093FD8",
    )
    a.allocate(
        "charmap_encoding_tables",
        16 * 1024,
        region="static",
        category="encoding",
        notes="budget; final table format not fixed yet",
    )
    a.allocate(
        "translated_text_budget",
        320 * 1024,
        region="text",
        category="text",
        notes="budget > current 298,134 B 1.4x/all-2-byte projection",
    )
    a.allocate(
        "translated_graphics_budget",
        2 * 1024 * 1024,
        region="graphics",
        category="graphics",
        notes="placeholder budget for title/UI/sprite/tile translations",
    )
    a.allocate(
        "build_metadata_budget",
        64 * 1024,
        region="metadata",
        category="metadata",
        notes="optional embedded build map/debug identifiers",
    )
    return a


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reference-plan",
        action="store_true",
        help="print the current conservative production reference plan",
    )
    args = parser.parse_args()
    allocator = make_reference_plan() if args.reference_plan else AppendAllocator()
    print(json.dumps(allocator.manifest(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
