#!/usr/bin/env python3
"""Measure unit-name visual widths and decode the Korean.ss7 name row."""
from __future__ import annotations

import json
import re
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import analyze_ggen_advance_intermission_cycle_states_20260830 as bg  # noqa: E402
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt  # noqa: E402
from analyze_ggen_advance_pending_names_ingame_jp_20260904 import (  # noqa: E402
    owner_offsets,
    payload_at,
    u32,
)
from build_ggen_advance_unified_rom_poc import (  # noqa: E402
    CHARMAP_8X16_PATH,
    DICT_8X16_BASE,
    DICT_8X16_END,
    leading_reserved_prefix,
    load_dictionary,
    load_identified_slot_to_char,
    raw_hex_bytes,
    tokens_from_bytes,
)
from ggen_advance_project_paths import (  # noqa: E402
    MAIN_TIP_ROM,
    ORIGINAL_ROM,
    TRANSLATION_MERGED_JSON,
)
from ggen_advance_text_codec import expand_to_slots  # noqa: E402

TAG_RE = re.compile(r"<[^>]+>")
SS7 = ROOT / "SD Gundam GGeneration Advance (Korean).ss7"
OUT = ROOT / "analysis" / "ggen_advance_unit_name_widths_20260911.json"
OUT_DIR = ROOT / "outputs" / "20260911_ggen_advance_unit_name_widths"


def vis_raw(text: str) -> int:
    return len(text.replace("\n", ""))


def vis_tag1(text: str) -> int:
    tags = TAG_RE.findall(text)
    return len(TAG_RE.sub("", text)) + len(tags)


def decode_payload(raw: bytes, dictionary, charmap: dict[int, str]) -> tuple[str, int]:
    slots = expand_to_slots(tokens_from_bytes(raw), dictionary)
    chars = []
    for slot in slots:
        char = charmap.get(slot)
        if char is None:
            chars.append(f"<{slot:04X}>")
        else:
            chars.append(char)
    return "".join(chars), len(slots)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    rom = MAIN_TIP_ROM.read_bytes()
    original = ORIGINAL_ROM.read_bytes()
    dict8 = load_dictionary(original, DICT_8X16_BASE, DICT_8X16_END)
    map8 = load_identified_slot_to_char(CHARMAP_8X16_PATH)

    rows = []
    unique: dict[tuple[str, str], dict] = {}
    for row in merged["records"]:
        cat = str(row.get("semantic_category") or "")
        if cat not in {"unit_name", "unit_name_alternate"}:
            continue
        if str(row.get("translation_status") or "") != "translated":
            continue
        ko = str(row.get("translation_ko") or "")
        jp = str(row.get("source_text") or "")
        item = {
            "record_id": row["record_id"],
            "cat": cat,
            "families": list(row.get("source_families") or []),
            "jp": jp,
            "ko": ko,
            "jp_raw": vis_raw(jp),
            "ko_raw": vis_raw(ko),
            "jp_tag1": vis_tag1(jp),
            "ko_tag1": vis_tag1(ko),
            "spaces": ko.count(" "),
        }
        rows.append(item)
        key = (cat, ko)
        unique.setdefault(key, {"ko": ko, "cat": cat, "jp": jp, "count": 0, "ids": [], **{k: item[k] for k in ("jp_raw", "ko_raw", "jp_tag1", "ko_tag1", "spaces")}})
        unique[key]["count"] += 1
        unique[key]["ids"].append(row["record_id"])

    long_unique = sorted(
        unique.values(),
        key=lambda item: (-item["ko_raw"], -item["ko_tag1"], item["ko"]),
    )
    print("=== unique unit names by raw KO length ===")
    print("len>=12:", sum(1 for item in long_unique if item["ko_raw"] >= 12))
    print("len>=13:", sum(1 for item in long_unique if item["ko_raw"] >= 13))
    print("len>=14:", sum(1 for item in long_unique if item["ko_raw"] >= 14))
    print("len>=15:", sum(1 for item in long_unique if item["ko_raw"] >= 15))
    print("len>=16:", sum(1 for item in long_unique if item["ko_raw"] >= 16))
    print("max raw", max(item["ko_raw"] for item in long_unique), "max tag1", max(item["ko_tag1"] for item in long_unique))
    print("--- raw>=12 ---")
    for item in long_unique:
        if item["ko_raw"] < 12:
            continue
        print(f"{item['ko_raw']:2d}/{item['ko_tag1']:2d} n={item['count']:3d} {item['cat']:22s} {item['ko']!r}  jp={item['jp']!r}")

    print("\n=== Doan live payloads ===")
    doan_live = []
    for row in merged["records"]:
        ko = str(row.get("translation_ko") or "")
        if "도안 전용기" not in ko and "ドアン" not in str(row.get("source_text") or ""):
            continue
        owners = owner_offsets(row)
        orig = raw_hex_bytes(str(row.get("raw_hex") or ""))
        prefix = leading_reserved_prefix(orig)
        for owner in owners:
            ptr = u32(rom, owner)
            live = payload_at(rom, ptr)
            decoded, nslots = decode_payload(live or b"", dict8, map8)
            rec = {
                "record_id": row["record_id"],
                "ko": ko,
                "owner": hex(owner),
                "ptr": hex(ptr),
                "live_hex": (live or b"").hex(" "),
                "orig_hex": orig.hex(" "),
                "prefix_hex": prefix.hex(" "),
                "decoded": decoded,
                "live_slots": nslots,
            }
            doan_live.append(rec)
            print(
                rec["record_id"],
                rec["ko"],
                "ptr",
                rec["ptr"],
                "slots",
                nslots,
                "decoded",
                decoded,
                "live",
                rec["live_hex"],
            )

    ss_info = {"exists": SS7.exists(), "size": SS7.stat().st_size if SS7.exists() else 0}
    print("\n=== ss7", ss_info, "===")
    if SS7.exists():
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        st, _meta = statefmt.parse_png_state(SS7)
        for layer in range(4):
            info = bg.bg_info(st, layer)
            print("BG", layer, info)
            bg.render_bg(st, info, OUT_DIR / f"ss7_bg{layer}.png")
            vram = st[statefmt.STATE_VRAM : statefmt.STATE_IWRAM]
            # dump a few interesting map rows
            for y in range(0, 20):
                cells = [bg.map_entry(vram, info["screen_base"], info["size"], x, y) for x in range(30)]
                if any(cell & 0x3FF for cell in cells):
                    print(f"  L{layer} y={y:02d}", [hex(c) for c in cells])

    report = {
        "counts": dict(Counter(item["ko_raw"] for item in long_unique)),
        "unique_ge12": [item for item in long_unique if item["ko_raw"] >= 12],
        "doan_live": doan_live,
        "ss7": ss_info,
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
