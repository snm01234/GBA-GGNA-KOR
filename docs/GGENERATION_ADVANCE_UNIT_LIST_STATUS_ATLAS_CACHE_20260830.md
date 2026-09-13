# G Generation Advance — unit-list right-pane E0518 atlas cache / savestate interaction (2026-08-30)

## Runtime symptom

After the C439 fixed-resource follow-up, the **left list** `持` changed to `지`, but the right unit-detail pane still displayed Japanese `持`.  The same pane also visibly showed Japanese `運動 / 限界 / 移動`.

That combination is the key clue: those neighboring labels are already Korean in the current main TIP's active E0518 status atlas.

## ROM-side proof

Current canonical main TIP:

- `SD Gundam GGeneration Advance (Korean).gba`
- SHA-256 `f033b480bb36aabed3533bdea6dc0ff6da7884ea4ff1e9372cf662edb3295fd6`
- E0518 table[0] → `0x09240000`

The active atlas contains Korean versions of:

- `運動 -> 운동`
- `限界 -> 한계`
- `移動 -> 이동`

Their block hashes differ from clean Japanese and match the approved status-UI Korean payload.

The measured-good C439 list candidate:

- `outputs/20260830_ggen_advance_status_badges/ggen_advance_status_badges_hold_fixed_list_followup_candidate_20260830.gba`
- SHA-256 `04bf4f64b3f0512f86152029680fb58cbebb93c64943bf3a09aaff40ec578d80`

additionally contains Korean `지` in E0518 resource[12], logical tiles `0x09B/0x09C`.

Therefore a runtime screen that simultaneously shows Japanese `運動/限界/移動/持` cannot be displaying the current ROM's active E0518 graphics payload.

## Tilemap relationship

The unit-list right pane uses E0518 resource[35] as the 32×20 base map.  The neighboring labels are the same logical tiles already documented for standalone unit status:

- `運動`: `146 147 148 149 / 14E 14F 150 151`
- `限界`: `156 157 158 159 / 15D 15E 15F 160`
- `移動`: `15A 15B 15C 149 / 161 162 150 151`

The narrow `持` badge is E0518 resource[12]:

- `1×2`
- tiles `09B / 09C`

The user screenshot's badge shape matches the clean-Japanese resource[12] 8×16 plaque, while the `04bf...` ROM's active resource[12] payload is already Korean `지`.

## Setup vs redraw path

### Screen setup

At `0x0801E2D6..0x0801E2E0`:

1. load literal `0x080E0518` (`0x0801E334`),
2. dereference table[0],
3. set `r1 = 1`,
4. call `0x0800261C`.

`0x0800261C` is the compressed graphics uploader.  With `r1=1`, it loads the active E0518 character atlas into BG character VRAM starting at tile base 1.

### Right-pane row redraw

`0x0801E8D4` uses literal `0x080E0518` (`0x0801EBE8`) and repeatedly calls `0x0800269C` to blit resource tilemaps.  It **does not call `0x0800261C`**.

So row changes redraw tilemap entries, but reuse whatever tile graphics are already resident in VRAM.

## Why a savestate can hide ROM graphic changes

A savestate captured while already inside the unit-list/status screen contains the existing VRAM state.  Loading that state after switching to a new candidate ROM restores the old character graphics along with CPU/RAM state.

Because `0x0801E8D4` does not reload E0518 character graphics on each row update, the screen can continue showing old Japanese `運動/限界/移動/持` even though the new ROM contains Korean graphics.

This also explains the apparently contradictory result that the left C439 badge changed: that badge is a direct fixed-resource draw path and can be refreshed from ROM when the list row redraws, while the right-pane E0518 character atlas remains cached in VRAM.

## C491 hypothesis status

The previous C491 compressed fixed-resource candidate:

- `outputs/20260830_ggen_advance_status_badges/ggen_advance_status_badges_hold_fixed_list_detail_followup_candidate_20260830.gba`
- SHA-256 `1a416cd86af1492f8b5a6a21f6536392bd156189c0a667c9933e619375db41a0`

is **superseded**.  Its changes do not affect the E0518 atlas used by the right pane, and the active E0518 payload in that candidate is byte-exact to the `04bf...` parent.

Do not promote or continue from `1a416...`.

## Correct validation protocol

Use `04bf4f64...` as the test parent.

For E0518 graphics validation:

1. boot the candidate normally, or load SRAM/normal save;
2. enter the unit-list screen fresh;
3. do **not** load a savestate captured while already inside this screen;
4. if a savestate must be used, use one from before the screen initializes, or leave the unit-list screen and re-enter it after loading the state.

On a valid fresh entry the following should occur together:

- `運動 -> 운동`
- `限界 -> 한계`
- `移動 -> 이동`
- right-pane resource[12] `持 -> 지`
- left-list C439 `持 -> 지`

If all of the first four still remain Japanese **after a confirmed fresh screen entry**, capture a new savestate from that fresh candidate.  That state would then be suitable for VRAM/source tracing because it would rule out stale character VRAM.

## Artifacts

- analyzer: `tools/analyze_ggen_advance_unit_list_status_atlas_cache_20260830.py`
- report: `analysis/ggen_advance_unit_list_status_atlas_cache_20260830.json`
- result: `PASS`

No new ROM patch is required by this finding; the correct test candidate remains `04bf4f64...` until fresh-entry runtime verification is performed.
