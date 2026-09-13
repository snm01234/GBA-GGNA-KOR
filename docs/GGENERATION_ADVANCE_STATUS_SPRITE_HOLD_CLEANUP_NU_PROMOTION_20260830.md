# G Generation Advance — status sprite `지` cleanup + Nu Gundam correction promotion (2026-08-30)

## 1. Scope

This promotion combines three approved/follow-up layers into one canonical main TIP:

1. the measured status OBJ/fixed duplicate Koreanization candidate (`1144cbc8...`),
2. a minimal cleanup of the remaining Japanese vertical stroke immediately left of the right-panel `지`,
3. the previously audited Nu Gundam context correction that replaces the erroneous `턴에이 건담` translation with `ν건담` only on the eight context-proven Nu Gundam unit-name rows.

True Turn A Gundam rows remain protected by the existing Nu audit.

## 2. `지` left-residue cleanup

Fresh runtime measurement proved that the visible right-panel badge is sourced from the C5A5DC package, with the two 8x8 source tiles at:

- top: `0x00C5CEB0`
- bottom: `0x00C5CF10`

The `1144...` candidate successfully changed the badge to Korean, but the screenshot showed a narrow stale Japanese vertical stroke on the far left. Pixel inspection localized it to exactly `x=0, y=3..10` of the composed 8x16 badge.

Before cleanup the eight pixels were:

`4, A, 4, 4, A, A, 4, 4`

They were restored to the native panel background index `8`. No other Korean-glyph pixels were touched. The surrounding top/bottom edge sequence remains `6,7,8,...,8,7,6`.

This is an 8-byte/nibble-localized source mutation inside the two already proven C5A5DC tiles; no palette, pointer, or unrelated graphics are changed.

## 3. Nu Gundam correction merge

The existing audited candidate:

`outputs/20260830_ggen_advance_nu_gundam_main_tip/ggen_advance_nu_gundam_main_tip_candidate_20260830.gba`

already proved eight unit-name records that had been incorrectly encoded as `턴에이 건담` but are contextually Nu Gundam (adjacent New Hyper Bazooka / Fin Funnel data and owner-proven unit-name mappings).

Its exact diff against the historical `f033b480...` base is 82 bytes:

- eight owner-pointer edits,
- eight compact payloads in the safe extension area `0x01112A60..0x01112AA3`.

The final merge checked every one of those 82 positions against the historical base before applying them to the measured sprite candidate. Merge conflicts: **0**.

The result therefore reuses the already audited mapping:

`턴에이 건담 -> ν건담`

for the eight Nu records only, while the genuine Turn A rows remain untouched.

## 4. Final candidate and promotion

Builder:

`tools/build_ggen_advance_status_sprite_package_cleanup_nu_merge_20260830.py`

Candidate:

`outputs/20260830_ggen_advance_status_badges/ggen_advance_status_sprite_package_full_ko_hold_cleanup_nu_candidate_20260830.gba`

Candidate/final SHA-256:

`b244f4103e2ae870cfe888dee569feca17c96f0bf55b71f74675ed76983f0a10`

Manifest:

`analysis/ggen_advance_status_sprite_package_full_ko_hold_cleanup_nu_20260830.json`

Static verification:

- measured full-KO parent hash verified,
- exact 8-byte `지` residue cleanup scope,
- Korean `지` body preserved outside the left residue column,
- Nu audited diff replayed exactly,
- Nu merge conflicts: 0,
- all eight Nu owner pointers and payloads verified,
- palette changes: 0,
- hold-cleanup resource-pointer changes: 0,
- unified/development regression: **10/10 PASS**.

The candidate was promoted with:

`approved_status_sprite_full_ko_hold_cleanup_nu_gundam_20260830`

Canonical main TIP:

`SD Gundam GGeneration Advance (Korean).gba`

SHA-256:

`b244f4103e2ae870cfe888dee569feca17c96f0bf55b71f74675ed76983f0a10`

The previous main TIP `1a416cd8...` is preserved under the standard `integrated/main_tip/backups/` promotion backup path.
