"""Apply the user-approved Torrington/Uso/Heero and Creuset review.

Reuse the existing live-token-preserving patcher and its pointer/width gates.
"""
import json
import shutil

import patch_ggen_advance_name_unify_20260909 as patch

EXACT = {
    "GGA-MAPSCRIPT-00FBDE9D": "OZ의 섬멸을 확인\n이제부터 귀환한다……",
    "GGA-MAPSCRIPT-00F84C0C": "자미토프 님을 오래\n기다리게 할 수는 없네",
    "GGA-MAPSCRIPT-00FB587F": "자네는 지온 지원군으로\n자브로로 가 주게",
    "GGA-MAPSCRIPT-00FB58D7": "분명 자네 친구가\n파일럿이라고 들었네",
    "GGA-MAPSCRIPT-00FB5919": "……쏘지 않으면 다음엔\n자네가 맞을지도 모르네",
    "GGA-MAPSCRIPT-00F5A928": "출격 준비를 해 두게",
    "GGA-MAPSCRIPT-00FB58C4": "……스트라이크가 걱정인가",
    "GGA-MAPSCRIPT-00FA2379": "역시 자네는 현실이라는 걸\n모르고 있군",
    "GGA-MAPSCRIPT-00FA2450": "자네도 이용 가치는 있었지만\n별수 없군",
    "GGA-MAPSCRIPT-00F7F497": "「자네 친구라지?\n저 MS의 파일럿은」",
    "GGA-MAPSCRIPT-00F9E01D": "「자네를 믿고 일부러\n 연락까지 했는데…」",
}


def main():
    patch.BATCH_ID = "torrington-uso-heero-creuset-20260909"
    patch.IDENTITY_KEY = "torrington_uso_heero_creuset_sha256"
    patch.BATCH_KEY = "torrington_uso_heero_creuset_20260909"
    patch.REPORT_KIND = "ggen_advance_creuset_names_candidate_20260909"
    patch.OUT_DIR = patch.ROOT / "outputs/20260909_ggen_advance_creuset_names"
    patch.OUTPUT = patch.OUT_DIR / "ggen_advance_creuset_names_candidate_20260909.gba"
    patch.OUT_SAV = patch.OUTPUT.with_suffix(".sav")
    patch.MANIFEST = patch.OUT_DIR / "manifest.json"
    patch.REPORT = patch.ROOT / "analysis/ggen_advance_creuset_names_candidate_20260909.json"
    patch.SNAPSHOT = patch.ROOT / "analysis/ggen_advance_translation_merged_20260909_creuset_names.json"
    patch.CAVE_START = 0x012B3000
    patch.CAVE_END = 0x012BF000
    patch.NOTES = "사용자 승인: 토링턴·웃소 표기 통일, 히이로 귀환, 크루제 하오체를 하게체로 정리하고 아스란 호칭을 자네로 통일"
    merged = json.loads(patch.TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    replacements = {}
    targets = {}
    for row in merged["records"]:
        old = row.get("translation_ko") or ""
        new = EXACT.get(row["record_id"], old.replace("트리턴", "토링턴").replace("우소", "웃소"))
        if old != new:
            targets[row["record_id"]] = new
            replacements[old] = new
    patch.gate(len(targets) == 24, f"target count drift: {len(targets)}")
    patch.gate(set(EXACT) <= set(targets), "exact review target missing")
    def apply_row(row):
        new = targets[row["record_id"]]
        old_segments = row.get("translation_segments") or []
        return new, new.split("\n") if old_segments else []

    patch.rewrite_text = lambda text: replacements.get(text, text)
    patch.needs_rewrite = lambda text: text in replacements
    patch.apply_row_text = apply_row
    patch.OUT_DIR.mkdir(parents=True, exist_ok=True)
    for source in (patch.TRANSLATION_MERGED_JSON, patch.ROOT / "integrated/translation/ggen_advance_translation_manifest.json", patch.ROOT / "integrated/translation/ggen_advance_translation_master.xlsx"):
        backup = patch.OUT_DIR / ("before_" + source.name)
        patch.gate(not backup.exists(), f"backup already exists: {backup}")
        shutil.copy2(source, backup)
    return patch.main()


if __name__ == "__main__":
    raise SystemExit(main())
