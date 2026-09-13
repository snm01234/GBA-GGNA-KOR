# G Generation Advance — unit-list `持 -> 지` fixed-graphic follow-up (2026-08-30)

## 1. Runtime rejection of the D54 hypothesis

The candidate
`outputs/20260830_ggen_advance_status_badges/ggen_advance_status_badges_hold_full_list_followup_candidate_20260830.gba`
changed the D54 atlas clones of the status `持` tiles, but the user measured the
left unit-list `持` as completely unchanged.

Therefore the D54 clone was only a visually identical copy, not the final
consumer for the list badge.  The D54 hypothesis is **rejected** and is not
carried into the new candidate.

The new base is the already measured-good status/detail candidate:

- `outputs/20260830_ggen_advance_status_badges/ggen_advance_status_badges_hold_full_followup_candidate_20260830.gba`
- SHA-256 `de69dbc5f20a83784a1edc39760e3a4a5cb73210b584964fcb0c2070b6ca0ad1`
- D54 table[0] remains original `0x080D45DC`

## 2. Why the `実/攻/命/弾` analogy was correct

The battle mini-label investigation previously proved that a glyph can be
visually duplicated in an atlas while the actual renderer consumes an
independent fixed graphic descriptor.  The remaining list `持` has the same
architecture.

A pointer-targeted scan for the measured clean status resource[12] `持` outline
found two independent C439-family 8x16 graphics:

| variant | descriptor | graphic payload | literal references |
|---|---:|---:|---|
| B | `0x00C43954` | `0x00C43968` | `0x08075014`, `0x0807517C` |
| A | `0x00C439A8` | `0x00C439BC` | `0x08075610`, `0x08075780` |

The descriptor is a different subtype from the battle A8D descriptor but follows
the same fixed-resource idea:

- `0x14` bytes descriptor/header
- `0x40` bytes vertical 1x2 / 8x16 4bpp graphic
- palette/state is supplied externally rather than embedded as a trailing local palette
- common header prefix: `0A 00 01 02 10 00 04 00 14 00 40 00`

There are nine descriptors with this exact C439-family prefix in the clean ROM.
Only the two above have the `持` geometry and the relevant runtime literal refs.

## 3. Pixel proof

Clean status resource[12] contains the known Japanese `持`.  Its dark outline is
palette index `4` and has exactly **45 pixels**.

For both C439 targets:

- extract the 8x16 payload
- select palette index `4`
- shift the fixed graphic one scanline down for comparison
- compare against the clean status resource[12] index-4 outline

Result for **both** variants:

- Dice score: `1.0000`
- intersection: `45 / 45`
- observed fixed outline: `45`
- relation: fixed art is exactly **one scanline above** the status art

The two fixed variants share the same Japanese glyph pixels.  Their only mutual
pixel differences are **25 background pixels**, all `B -> A`.  This identifies
them as two display/state variants of the same badge rather than unrelated
lookalikes.

## 4. Runtime path

The code path also closes independently of the pixel match.

The same unit/status predicate used by the status-family badge is called in the
list renderer:

- predicate: `0x08005D24`
- calls: `0x08074FEE`, `0x08075156`, `0x080755EA`, `0x0807575A`

When true, the fixed descriptor is supplied to the fixed graphic draw helper:

- draw helper: `0x080638E4`
- draw calls for the two state families: `0x08075072`, `0x080751DA`, `0x0807566E`, `0x080757DE`

The nearby literal pools contain the exact C439 descriptor addresses listed
above.  Adjacent fixed resources (`0x00C43C04/58`, `0x00C43ACC/B00`) are separate
pre-status/suffix graphics and are explicitly protected.

This is the missing consumer that the E0518 and D54 patches could not affect.

## 5. Korean fixed graphic construction

The user already approved the Galmuri7 `지` appearance in the status/detail
screen.  The list fixed graphic therefore reuses that exact Galmuri7 8x16 mask
rather than introducing another font treatment.

Native Japanese fixed art is one scanline above the status art, so the Korean
mask is shifted **-1 Y** to preserve the native fixed-resource baseline.

For each fixed variant:

1. clear the old Japanese 8x16 silhouette back to that variant's native flat
   background (`B` or `A`), preserving the bottom `F` delimiter row;
2. render the same Galmuri7 `지` mask;
3. face palette index `A` (`10`);
4. 8-neighbour dark contour palette index `4`;
5. modify only the `0x40` graphic payload.

The descriptor header, code, pointer literals, suffix graphics, D54 atlas and
E0518 status atlas are not changed.

## 6. Candidate

- analyzer: `tools/analyze_ggen_advance_unit_list_hold_fixed_graphics_20260830.py`
- audit: `analysis/ggen_advance_unit_list_hold_fixed_graphics_20260830.json`
- builder: `tools/build_ggen_advance_unit_list_hold_fixed_graphics_followup_20260830.py`
- candidate: `outputs/20260830_ggen_advance_status_badges/ggen_advance_status_badges_hold_fixed_list_followup_candidate_20260830.gba`
- candidate SHA-256: `04bf4f64b3f0512f86152029680fb58cbebb93c64943bf3a09aaff40ec578d80`
- manifest: `analysis/ggen_advance_status_badges_hold_fixed_list_followup_20260830.json`
- preview: `outputs/20260830_ggen_advance_status_badges/ggen_advance_status_badges_hold_fixed_list_followup_preview_20260830.png`

Static verification:

- changed bytes versus measured-good `de69...` input: **93 bytes**
- mutable locations only: `0x00C43968..A7`, `0x00C439BC..FB`
- only two `0x40` fixed-graphic payloads may differ
- both `0x14` descriptor headers byte-exact
- C439 sibling fixed resources byte-exact
- D54 pointer remains `0x080D45DC`; rejected D54 redirect is absent
- status/detail `지`, `방패`, `만`, `간` carried forward from `de69...`
- regression: **10/10 PASS**

## 7. Runtime checkpoints

1. In the left unit list, the previously unchanged `持` must now read `지`.
2. Scroll across enough rows/states to exercise both C439 B/A variants.
3. The small suffix / `N`-like graphic to the right must remain unchanged and
   aligned.
4. Right-side detail/status `지`, `방패`, `만`, and existing `간` must remain
   identical to the already measured-good `de69...` candidate.

Main TIP is intentionally unchanged until this new fixed-resource candidate is
measured in-game.
