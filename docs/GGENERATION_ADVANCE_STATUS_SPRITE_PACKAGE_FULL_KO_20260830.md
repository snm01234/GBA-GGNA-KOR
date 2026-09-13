# G Generation Advance — status sprite-package duplicate Koreanization (2026-08-30)

## 1. Runtime correction from the fresh `.ss1`

The fresh mGBA state
`outputs/20260830_ggen_advance_status_badges/ggen_advance_status_badges_hold_fixed_list_detail_followup_candidate_20260830.ss1`
CRC-matches the promoted main TIP (`0x95519DE5`).  Its right unit-list pane is an OBJ sprite canvas, not a direct E0518 BG rendering.

The live owner is the `0x08C5A5DC` sprite package.  The visible Japanese `運動 / 装甲 / 限界 / 移動` tiles and the small `持` badge match raw ROM graphics in the C5CBxx-C5CFxx sheet.  This supersedes the earlier stale-VRAM and C491 hypotheses.

Fresh-state evidence:

- analyzer: `tools/analyze_ggen_advance_unit_list_sprite_state_20260830.py`
- report: `analysis/ggen_advance_unit_list_sprite_state_20260830.json`
- right-panel OAM object: index 28, x=128, y=80, 64x64, tile base `0x155`, palette 5
- active package: `0x08C5A5DC`
- exact remaining `持` source: `0x00C5CEB0 / 0x00C5CF10`

## 2. Same-case duplicate audit

The already approved Korean E0518 atlas is treated as the canonical Korean artwork.  Clean-JP E0518 tiles are compared with the raw sprite/fixed copies, and only mappings with zero translation conflicts are admitted.

Audit:

- analyzer: `tools/analyze_ggen_advance_status_sprite_package_duplicates_20260830.py`
- report: `analysis/ggen_advance_status_sprite_package_duplicates_20260830.json`
- result: **PASS**

### 2.1 Active C5A5DC package

The following duplicated status labels are safely mapped and patched:

- `近接 -> 근접`
- `射撃 -> 사격`
- `反応 -> 반응`
- `運動 -> 운동`
- `装甲 -> 장갑`
- `限界 -> 한계`
- `移動 -> 이동`
- `汎用 -> 범용`
- right-panel `持 -> 지`

The first-column variants of several 4x2 labels differ from E0518 only in package-specific panel-edge pixels.  The JP->KO translation delta does not conflict with those edge pixels, so the border is preserved instead of replacing the whole tile blindly.

`運動` and `移動` continue to share the same source `動` tiles in the C5 sheet.  Because the approved E0518 Korean art also shares `동`, the package copy preserves the same sharing automatically.

### 2.2 C64140 alternate package

The second raw sprite-copy family contains zero-conflict duplicates for:

- `運動 -> 운동`
- `限界 -> 한계`
- `汎用 -> 범용`

Only these proven mappings are patched.  `装甲/移動` were not forced because this package did not provide a complete zero-conflict mapping for those labels.

### 2.3 C43 direct terrain/type descriptors

A broader scan found six independent direct 4x2 descriptors whose 8 graphic tiles are **byte-exact clean-JP E0518 copies**:

| descriptor | JP | KO |
|---|---|---|
| `0x00C43E80` | 汎用 | 범용 |
| `0x00C43FA0` | 地上 | 지상 |
| `0x00C440C0` | 水陸 | 수륙 |
| `0x00C441E0` | 宇宙 | 우주 |
| `0x00C44300` | 万能 | 만능 |
| `0x00C44420` | 飛行 | 비행 |

These six descriptors are patched to the approved Korean E0518 payload byte-for-byte.  This closes the same fixed-graphic duplication case that can leave the terrain/type badge Japanese even though the E0518 BG atlas itself is already Korean.

The neighboring descriptor `0x00C44540` is a blank 4x2 panel frame, not another text label, and is preserved.

### 2.4 `持` shifted-delta proof

The C5 right-panel `持` is not byte-identical to E0518 resource[12], because the package badge is horizontally cropped/shifted.

For package x=0..5, the pixels correspond to E0518 x=2..7.  Across this six-column overlap:

- JP->KO changed pixels: **50**
- translation conflicts: **0**
- package-specific right edge x=6..7: untouched

Therefore the approved `지` translation delta can be shifted left two pixels without altering the sprite-package border.

## 3. Candidate implementation

Builder:

`tools/build_ggen_advance_status_sprite_package_full_ko_20260830.py`

Parent main TIP:

- `SD Gundam GGeneration Advance (Korean).gba`
- SHA-256 `1a416cd86af1492f8b5a6a21f6536392bd156189c0a667c9933e619375db41a0`

Candidate:

- `outputs/20260830_ggen_advance_status_badges/ggen_advance_status_sprite_package_full_ko_candidate_20260830.gba`
- SHA-256 `1144cbc817eeb0aa1d33e63593ffd0c89db047bf9300982d655778a503817d2a`
- manifest: `analysis/ggen_advance_status_sprite_package_full_ko_20260830.json`
- preview: `outputs/20260830_ggen_advance_status_badges/ggen_advance_status_sprite_package_full_ko_preview_20260830.png`

Implementation summary:

- unique raw source tiles patched: **135**
- changed bytes vs current main TIP: **2,711**
- palette changes: **0**
- pointer changes: **0**
- active E0518 compressed resource: byte-exact preserved
- D54 table[0]: `0x080D45DC` preserved
- already measured C439 left-list `지`: byte-exact preserved
- previous C491 private clones: byte-exact preserved
- C43 type descriptors themselves: unchanged; only their 8-tile graphic payloads change
- six C43 type payloads equal the approved Korean E0518 blocks byte-for-byte after patch

Regression:

`python -m unittest tools.test_ggen_advance_unified_pipeline tools.test_ggen_advance_intermission_development_fix`

Result: **10/10 PASS**.

## 4. Explicitly not forced

`操縦系 -> 조종계` was searched in the same pass, but no byte-exact or zero-conflict C5/C64/direct duplicate mapping was established.  It is intentionally left out rather than patching a visually similar but unproven block.

Other labels outside the proven C5/C64/C43 duplication sets are likewise untouched.

## 5. Runtime checkpoints

Primary unit-list/right-pane checks:

1. `運動 / 装甲 / 限界 / 移動` -> `운동 / 장갑 / 한계 / 이동`.
2. `I 필드` and equivalent ability text prefix `持` -> `지`.
3. terrain/type badge variants: `범용 / 지상 / 수륙 / 우주 / 만능 / 비행`.
4. existing left-list `지`, `방패`, `만`, `간` remain unchanged.

Additional same-package checks when reachable:

5. pilot-status duplicate copies `近接 / 射撃 / 反応` -> `근접 / 사격 / 반응`.
6. `조종계` is expected to remain outside this candidate until its actual duplicate consumer is separately proven.

The candidate is **not promoted automatically**.  Runtime measurement should precede promotion.
