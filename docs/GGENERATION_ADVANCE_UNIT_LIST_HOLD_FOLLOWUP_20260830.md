# G Generation Advance — unit-list `持 -> 지` follow-up (2026-08-30)

## 1. Runtime feedback

The status/detail follow-up candidate
`outputs/20260830_ggen_advance_status_badges/ggen_advance_status_badges_hold_full_followup_candidate_20260830.gba`
was measured in-game.  The three right-edge residue pixels disappeared and the
unit-information/detail consumers changed to `지`, but the left unit-list rows
still showed the original `持` badge.

This proves that the remaining list row is not another consumer of the active
E0518 status atlas alone.

## 2. Exact clone search across known UI atlases

The clean Japanese E0518 source tiles used by the status `持` badges were
searched byte-for-byte through every previously catalogued UI atlas family.

Status source tiles:

- `0x09B / 0x09C` — standalone `持` copy
- `0x09F / 0x0A0` — `持` prefix used by combined status badges

The only non-status exact clones are in the D54 family:

| clean status | D54 clone | byte-exact |
|---|---|---|
| `0x09B` | `0x0B8` | yes |
| `0x09C` | `0x0B9` | yes |
| `0x09F` | `0x0BC` | yes |
| `0x0A0` | `0x0BD` | yes |

No exact clone exists in the map-action D23 family, the D87 list-word family,
or the DAB deployment family.

The D54 family is:

- resource table: file `0x000D54E4`, GBA `0x080D54E4`
- compressed atlas: file `0x000D45DC`, GBA `0x080D45DC`
- decoded size: `6,080 bytes = 190 tiles`
- decoded SHA-256: `e7dcb1b0e4ab59cbafab5cffb0fd3720256019979c01cb2522f77e618f61976b`
- known renderer: `0x0801D09C`
- table literal refs: `0x0801D10C`, `0x0801D468`, `0x0801D574`

## 3. Resource ownership

The four cloned tiles are private to exactly two D54 resources:

- resource[14] `3x2`: `0x07E, 0x0B8, 0x036 / 0x07E, 0x0B9, 0x036`
- resource[16] `3x2`: `0x07E, 0x0BC, 0x0BA / 0x07E, 0x0BD, 0x0BB`

resource[15] uses only the suffix tiles `0x0BA/0x0BB` and is preserved byte-exact.
No other D54 resource references `0x0B8/0x0B9/0x0BC/0x0BD`.

This ownership matches the runtime symptom: the list row has a small right-side
badge with optional suffix state, independent from the E0518 detail panel.

## 4. Implementation policy

The new list patch deliberately does **not** rasterize a second `지` glyph.
Because the clean Japanese D54 payloads are exact clones of the clean Japanese
status payloads, the safest implementation is to copy the already runtime-tested
Korean replacements from the active status atlas:

- active status `0x09B -> D54 0x0B8`
- active status `0x09C -> D54 0x0B9`
- active status `0x09F -> D54 0x0BC`
- active status `0x0A0 -> D54 0x0BD`

Thus list/detail glyph shape, contour, clear zone and palette geometry are
identical by construction.

The original D54 compressed resource is only 2,411 bytes and cannot safely be
overwritten with a literal-only rebuild.  The decoded 190-tile atlas is cloned
into the measured zero-filled page at file `0x01280000` / GBA `0x09280000`, and
only D54 table[0] is redirected.  The D54 tilemaps/resources remain unchanged.

## 5. Candidate

- analyzer: `tools/analyze_ggen_advance_unit_list_hold_consumer_20260830.py`
- audit: `analysis/ggen_advance_unit_list_hold_consumer_20260830.json`
- builder: `tools/build_ggen_advance_unit_list_hold_followup_20260830.py`
- input: `outputs/20260830_ggen_advance_status_badges/ggen_advance_status_badges_hold_full_followup_candidate_20260830.gba`
- input SHA-256: `de69dbc5f20a83784a1edc39760e3a4a5cb73210b584964fcb0c2070b6ca0ad1`
- candidate: `outputs/20260830_ggen_advance_status_badges/ggen_advance_status_badges_hold_full_list_followup_candidate_20260830.gba`
- candidate SHA-256: `27f0a505e7946879332e5d37133fc71b77db9665122e89abc5cef59b016cd552`
- manifest: `analysis/ggen_advance_status_badges_hold_full_list_followup_20260830.json`
- preview: `outputs/20260830_ggen_advance_status_badges/ggen_advance_status_badges_hold_full_list_followup_preview_20260830.png`

Static verification:

- changed D54 tiles: `0x0B8, 0x0B9, 0x0BC, 0x0BD`
- changed D54 resources: `14, 16` only
- resource[15] suffix-only payload: byte-exact
- all other D54 tiles: byte-exact
- all D54 tilemaps: unchanged
- active E0518/status atlas: byte-exact versus the already tested input candidate
- palette changes: none
- original-half changes: D54 table[0] pointer 4 bytes only
- new private allocation: `0x01280000`
- changed bytes versus input candidate: `6,642`
- unified/development regression: `10/10 PASS`

## 6. Runtime checkpoints

1. The left unit-list rows that still showed `持` should now show the same `지`
   shape as the already-tested detail/status panel.
2. Rows with the small right-side suffix/N variant must keep that suffix and its
   alignment; only the `持` component should change.
3. The right detail panel `지`, `방패`, `만`, and existing `간` must look exactly
   like the preceding tested candidate.
4. Scroll through enough rows to exercise both D54 resource[14] and resource[16].

Main TIP remains unchanged until this candidate is measured in-game.
