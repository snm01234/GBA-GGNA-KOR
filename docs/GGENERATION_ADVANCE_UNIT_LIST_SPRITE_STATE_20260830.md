# G Generation Advance — fresh unit-list savestate / right-panel sprite owner (2026-08-30)

## 1. Input and main-TIP identity

The newly captured state is:

- `outputs/20260830_ggen_advance_status_badges/ggen_advance_status_badges_hold_fixed_list_detail_followup_candidate_20260830.ss1`

Before analyzing it, the tested candidate was promoted to the canonical main TIP at the user's request:

- canonical: `SD Gundam GGeneration Advance (Korean).gba`
- SHA-256: `1a416cd86af1492f8b5a6a21f6536392bd156189c0a667c9933e619375db41a0`
- promotion reason: `approved_current_status_badge_followup_pending_state_analysis_20260830`
- previous canonical `f033b480...` was backed up by the normal promotion tool.

The mGBA state serialized header contains ROM CRC32 `0x95519DE5`.  The promoted main TIP has CRC32 `0x95519DE5`, so this is a byte-identity-compatible runtime state from the ROM that was just promoted.  The previous stale-state explanation is therefore rejected for this fresh capture.

## 2. The right panel is OBJ, not a directly visible E0518 BG atlas

The state uses OBJ 1D mapping (`DISPCNT` has OBJ and 1D mapping enabled).  The important OAM entry is object 28:

- screen position: `x=128, y=80`
- size: `64x64`
- OBJ tile base: `0x155`
- palette bank: `5`
- priority: `3`

This object is a large piece of the visible right-side unit information panel.  Additional OAM objects continue the panel to the right and downward.

This changes the consumer model.  E0518 still provides the familiar status graphics elsewhere, but the pixels visible in this list/detail pane have been composed into OBJ VRAM.  Editing only the E0518 BG atlas cannot change a separately sourced OBJ copy.

## 3. Neighboring Japanese labels prove the source family

The live OBJ canvas contains byte-exact Japanese E0518 label fragments even though the active main-TIP E0518 atlas is already Korean.

Examples:

- live OBJ `0x157/158/159` = clean-JP E0518 `0x147/148/149` (`運動` fragments)
- live OBJ `0x15F/160/161` = clean-JP E0518 `0x14F/150/151`
- live OBJ `0x167/168/169` = clean-JP E0518 `0x14B/14C/14D` (`装甲` fragments)
- live OBJ `0x177/178/179` = clean-JP E0518 `0x15B/15C/149` (`移動`, with the original shared `動` fragment)
- live OBJ `0x196/197` and `0x199/19A/19B` = clean-JP `限界` fragments.

For every one of these anchors the live OBJ bytes differ from the corresponding Korean tile in the promoted main's active E0518 atlas (`table[0] -> 0x09240000`).  Thus the right pane is not displaying the promoted E0518 graphics.

## 4. Runtime owner: C5A5DC sprite package

The sprite-object manager table is rooted at IWRAM `0x03001F98`; object records are 40 bytes and store the resource pointer at offset `+0`.

In the supplied state the active resource pointer `0x08C5A5DC` is resident in object-manager slots 2 and 8.  The alternate/look-alike package `0x08C64140` is not resident.

The panel's live OBJ tile bytes independently match raw graphic data inside the `0x08C5A5DC` package region.  Relevant examples are concentrated in `0x00C5CBB0..0x00C5CFF0`.

### `運動`

Live OBJ:

`156 157 158 159 / 15E 15F 160 161`

Raw ROM sources:

`C5CBB0 C5CBD0 C5CBF0 C5CC10 / C5CC50 C5CC70 C5CC90 C5CCB0`

### `装甲`

Live OBJ:

`166 167 168 169 / 16E 16F 170 171`

Raw ROM sources:

`C5CCF0 C5CD10 C5CD30 C5CD50 / C5CD70 C5CD90 C5CDB0 C5CDD0`

### `移動`

Live OBJ:

`176 177 178 179 / 17E 17F 180 181`

Raw ROM sources:

`C5CDF0 C5CE10 C5CE30 C5CC10 / C5CE50 C5CE70 C5CC90 C5CCB0`

The reuse of `C5CC10 / C5CC90 / C5CCB0` mirrors the original Japanese shared `動` structure and is an especially strong ownership signal.

### `限界`

The label crosses the following panel segment; the state still gives direct raw anchors at:

`C5CF50 C5CF70 C5CF90 / C5CFB0 C5CFD0 C5CFF0`

## 5. Exact remaining `持` source

The small badge seen before `I 필드` lies inside OAM object 28 at screen x `136`, y `128..143`.

Under 1D OBJ mapping:

- top: OBJ tile `0x186`, full VRAM tile `0x986`, screen `(136,128)`
- bottom: OBJ tile `0x18E`, full VRAM tile `0x98E`, screen `(136,136)`

Those two live tiles are byte-exact copies of:

- `0x00C5CEB0`
- `0x00C5CF10`

respectively.

This is the exact final consumer source for the still-visible right-pane `持` in the supplied state.

## 6. Why the previous C491 patch had no effect

The translated private C491 descriptors at `0x01280000` and `0x01280040` decode correctly in the promoted ROM, but **neither decoded tile appears anywhere in live OBJ VRAM** in this state.

Therefore C491 was only a visually similar fixed resource selected by another renderer path.  It is not the final right-panel consumer and should not be extended further.

Conversely the already-successful C439 left-list translated tiles are present in BG VRAM, which is consistent with the earlier runtime observation that the left-list badge changed while the right pane did not.

## 7. Corrected conclusion

The previous cache-only hypothesis from 22.90 is superseded by the fresh state.

The current consumer model is:

- left list `持`: C439 fixed graphic — already translated
- lower/detail E0518 copies: translated in the active E0518 atlas
- visible list **right pane**: **C5A5DC OBJ sprite package**
- visible right-pane `持`: raw package tiles `0x00C5CEB0 / 0x00C5CF10`
- neighboring `運動 / 装甲 / 限界 / 移動`: same C5A5DC package sheet family
- C491: unrelated look-alike; no live OBJ hit
- D54: unrelated clone for this consumer

The next ROM patch should therefore operate on the C5A5DC package sheet, not on E0518/D54/C491.  Before writing, package-sharing and alternate-state copies should be audited so the Japanese shared `動` geometry can be preserved cleanly when rendering Korean `운동/이동`.

## 8. Artifacts

- analyzer: `tools/analyze_ggen_advance_unit_list_sprite_state_20260830.py`
- report: `analysis/ggen_advance_unit_list_sprite_state_20260830.json`
- result: **PASS**

No new patch ROM was generated in this state-analysis step.
