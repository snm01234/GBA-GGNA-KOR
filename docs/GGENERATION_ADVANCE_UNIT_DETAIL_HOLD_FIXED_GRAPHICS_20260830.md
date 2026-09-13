# G Generation Advance — right unit-detail `持` fixed graphic (2026-08-30)

## Runtime feedback

The C439 fixed-resource follow-up successfully changes the **left list** `持` to
`지`.  A separate Japanese `持` remains on the **right unit-detail pane**, in
the small square badge immediately before ability text such as `Iフィールド`.

This final visible copy is not the E0518 status-atlas badge and is not the
previously rejected D54 clone.

## Consumer class

The remaining copy is another fixed-graphic consumer, matching the structural
pattern already seen in the battle `実/攻/命/弾` work:

- property predicate: `0x08005D24`
- generic fixed-graphic draw helper: `0x080638E4`
- because the descriptor has flag bit `0x10`, `0x080638E4` sends its graphic
  payload through decoder `0x08001A84` before uploading it
- resource size: `1x1` tile = `8x8`

So the right-pane badge is structurally different from the left-list C439
`8x16` fixed graphic even though both are selected by the same property test.

## Fixed resources

Two normal/alternate background variants are used:

### B variant

- descriptor file offset: `0x00C491C0`
- GBA address: `0x08C491C0`
- literal references: `0x080752F0`, `0x08075458`
- predicate calls immediately selecting this branch: `0x080752C2`, `0x0807542A`
- descriptor flags: `0x1A`
- map size: `1x1`
- map cell: `0x3000`
- compressed payload offset: `+0x14`
- compressed payload length: `0x1E`
- decompressed size: `32 bytes`

Decoded 8x8 tile:

```text
B444444B
4FFD4F4B
4FFFDF4B
4FFFFF4B
4FFDFF4B
4FF4DF4B
444B444B
FFFFFFFF
```

### A variant

- descriptor file offset: `0x00C491F4`
- GBA address: `0x08C491F4`
- literal references: `0x080758F4`, `0x08075A5C`
- predicate calls: `0x080758C6`, `0x08075A2E`
- compressed payload length: `0x1E`
- decompressed size: `32 bytes`

Decoded tile:

```text
A444444A
4FFD4F4A
4FFFDF4A
4FFFFF4A
4FFDFF4A
4FF4DF4A
444A444A
FFFFFFFF
```

The A/B pair has the same Japanese glyph.  Their differences are only the
expected `B -> A` background-edge pixels.

## Cross-check against sibling fixed resources

The same renderer family also contains direct/uncompressed siblings:

- B: `0x00C43ACC`
- A: `0x00C43B00`

The compressed right-pane copy and the direct sibling preserve the same inner
Japanese glyph.  D/E/F bright-mask Dice is greater than `0.96`, while the
4/D/E/F glyph+contour mask Dice is greater than `0.99`; the residual difference
is the closed right/bottom plaque edge of the 1x1 right-pane resource.

This explains why the previous searches missed it:

1. E0518 scanning only sees status-atlas copies.
2. D54 contains another visual clone but is not the left-list final consumer.
3. C439 closes the left list, but that object is `8x16` direct fixed graphics.
4. The remaining right-pane badge is a separate **compressed 8x8 fixed graphic**
   in C491xx selected by the same `0x08005D24` predicate.

## Analysis artifact

- analyzer: `tools/analyze_ggen_advance_unit_detail_hold_fixed_graphics_20260830.py`
- report: `analysis/ggen_advance_unit_detail_hold_fixed_graphics_20260830.json`
- result: `PASS`

The initial investigation step did not modify the ROM.  A follow-up implementation was then built from the runtime-approved left-list candidate.

## Follow-up implementation

Parent candidate:

- `outputs/20260830_ggen_advance_status_badges/ggen_advance_status_badges_hold_fixed_list_followup_candidate_20260830.gba`
- SHA-256 `04bf4f64b3f0512f86152029680fb58cbebb93c64943bf3a09aaff40ec578d80`

The native compressed payload for each C491 descriptor is only `0x1E` bytes.  A conservative literal-only rebuild of a translated 32-byte 8x8 tile is `0x24` bytes, so an in-place overwrite would collide with the next native descriptor.  Instead, two private descriptor clones are placed in verified zero-filled expanded-ROM space:

- B clone: file `0x01280000`, GBA `0x09280000`
- A clone: file `0x01280040`, GBA `0x09280040`

Only the four verified literal references are redirected:

- `0x080752F0`, `0x08075458` -> `0x09280000`
- `0x080758F4`, `0x08075A5C` -> `0x09280040`

The original C491C0/C491F4 descriptors therefore remain byte-exact.  The new 8x8 `지` uses the same accepted Galmuri7 6x7 mask already used by the status/list work, fitted into rows 0..6.  Palette index `F` is used for the face and index `4` for the contour; the native A/B background variant is retained, and row 7 remains the fixed `F` delimiter.

Builder and outputs:

- builder: `tools/build_ggen_advance_unit_detail_hold_fixed_graphics_followup_20260830.py`
- candidate: `outputs/20260830_ggen_advance_status_badges/ggen_advance_status_badges_hold_fixed_list_detail_followup_candidate_20260830.gba`
- SHA-256: `1a416cd86af1492f8b5a6a21f6536392bd156189c0a667c9933e619375db41a0`
- manifest: `analysis/ggen_advance_status_badges_hold_fixed_list_detail_followup_20260830.json`
- preview: `outputs/20260830_ggen_advance_status_badges/ggen_advance_status_badges_hold_fixed_list_detail_followup_preview_20260830.png`

Static verification:

- parent hash verified
- source audit re-run: PASS
- both A/B cloned descriptors decode back to the translated 32-byte tile
- original C491 descriptors unchanged
- direct C43ACC/C43B00 siblings unchanged
- previously approved C439 left-list `지` graphics unchanged
- rejected D54 redirect absent; D54 table[0] stays `0x080D45DC`
- changes limited to four code literals plus the two private descriptor clones
- changed bytes versus parent: `104`
- unified/development regression: `10/10 PASS`

## Superseded after runtime re-check

Runtime testing showed that this C491 candidate did **not** change the visible right-pane `持`.  A follow-up investigation that connected the still-Japanese neighboring `運動 / 限界 / 移動` labels proved that the visible right pane is using E0518 resource graphics already resident in VRAM, while the current ROM's active E0518 atlas is already Korean for those labels and for resource[12] in the `04bf...` candidate.

The C491 pair is therefore an unrelated fixed-resource lookalike selected by a similar predicate path.  This candidate must not be promoted or used as the parent for further `持` work.

Superseding analysis:

- `tools/analyze_ggen_advance_unit_list_status_atlas_cache_20260830.py`
- `analysis/ggen_advance_unit_list_status_atlas_cache_20260830.json`
- `docs/GGENERATION_ADVANCE_UNIT_LIST_STATUS_ATLAS_CACHE_20260830.md`

Correct runtime-validation parent returns to `04bf4f64b3f0512f86152029680fb58cbebb93c64943bf3a09aaff40ec578d80`.  E0518 graphics must be tested after a fresh screen entry so a savestate captured inside the unit-list/status screen does not restore stale Japanese character VRAM.
