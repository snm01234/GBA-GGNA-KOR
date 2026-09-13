# G Generation Advance action-menu Korean follow-up (2026-08-30)

## User-observed regressions

The first candidate `outputs/20260830_ggen_advance_fixed_action_graphics/ggen_advance_action_menu_ko_candidate_20260830.gba` showed three problems during runtime verification:

1. opening the unit action menu could corrupt tiles in the map background;
2. Korean normal/focus labels still carried Japanese glyph shadow/contour remnants, especially around the focus label perimeter;
3. the `移動` secondary menu remained Japanese. Its first item is `全体` (`전체`), not `合体` (`합체`).

## Root cause and correction

### Background corruption

The first builder appended eight private tiles for every translated state. The native action atlas is 239 decoded 4bpp tiles (7,648 bytes), while the first candidate expanded it to 415 tiles (13,280 bytes): an excess of 176 tiles / 5,632 bytes beyond the native runtime footprint. The follow-up keeps the decoded runtime atlas exactly 239 tiles / 7,648 bytes and repacks translated tiles into source slots that become unreachable after private tilemap redirection.

### Japanese focus/normal remnants

The first builder cleared only a fixed 28x12 central rectangle and drew the Korean face pixels. Native Japanese contour pixels extend beyond that rectangle. The follow-up reconstructs a glyph-free panel template from the complete native normal/focus label families and then draws the Korean glyph plus an 8-neighbour contour, matching the already-approved battle-weapon shadow-fix method.

The inferred native contour palette indices are:

- normal: index 10
- focus: index 8

As an additional static gate, every non-background pixel in each reconstructed
glyph-free template must be connected to the fixed 32x16 panel edge. An
interior Japanese face/contour fragment would be an isolated component and now
fails the build.

### `全体` / `個別` secondary menu

The previous semantic scan misread resource 28 as `合体`; direct in-game verification establishes it as `全体`.

The normal `全体` / `個別` tile IDs from resources 28/29 are also embedded in the larger 11-column menu-frame resources 10..17. Redirecting only resources 28/29 therefore cannot change the secondary menu as rendered. The follow-up clones resources 10..17 and redirects their shared secondary-menu cells to the Korean `전체` / `개별` tiles while preserving palette-bank and flip bits.

## Follow-up artifacts

Builder:

`tools/build_ggen_advance_action_menu_ko_followup.py`

Candidate:

`outputs/20260830_ggen_advance_fixed_action_graphics/ggen_advance_action_menu_ko_followup_candidate_20260830.gba`

SHA-256:

`acb87a9d2c1d2cfd1c7a20199d0f14627c320eae69f3ce185e36545f38123c39`

Manifest:

`analysis/ggen_advance_action_menu_ko_followup_20260830.json`

Preview:

`outputs/20260830_ggen_advance_fixed_action_graphics/ggen_advance_action_menu_ko_followup_preview_20260830.png`

## Static verification

The builder completed with `PASS` and verifies all of the following before writing the candidate:

- the input hash matches the user-tested first candidate;
- reversing only that candidate's proven private allocation and three pointer
  edits reproduces its recorded main-TIP source SHA-256 exactly;
- original action atlas remains unchanged in place;
- private decoded atlas remains exactly 239 tiles / 7,648 bytes;
- repacking never changes a tile still needed by an unredirected resource;
- `ID` normal/focus resources remain untouched;
- unknown trailing resources 42/43 remain untouched;
- Korean contours are regenerated from the Korean glyph masks;
- `全体 -> 전체`, `個別 -> 개별` are included in translated normal/focus label resources;
- resources 10..17 are cloned so their shared secondary-menu cells use Korean tiles;
- ROM changes are restricted to the private action allocation plus the three already-proven resource-table literals.

## Runtime verification before main-TIP promotion

- Open/close the unit action menu on the city and desert/background types that exposed the regression and confirm map tiles no longer change or glitch.
- Verify normal and focus states for `이동`, `대열`, `공격`, and the other translated commands.
- Confirm that no Japanese contour/stroke remains around Korean focus labels.
- Enter the `이동` secondary menu and verify `전체` / `개별` in both selected and unselected states.
- Verify that `ID` remains native and unchanged.

Do not promote this follow-up to main TIP until runtime verification passes.

## Runtime palette/style correction

The follow-up runtime screenshot proved that the earlier diagnostic preview had
the normal palette roles reversed and that palette index 10 had been applied as
an all-around Korean glyph contour. Screenshot-to-clean-ROM registration closes
the actual normal palette roles as follows:

- index 5: dark-brown button interior;
- index 9: orange-brown fixed panel bevel;
- index 10: yellow fixed panel bevel;
- index 11: pale-yellow glyph face.

The native normal Japanese face plane has no independent contour. Indices 9 and
10 around the source resources belong to the rounded panel bevel, not the text.
The style-fix therefore rebuilds the exact symmetric native panel, adds only
index-11 Korean face pixels, and statically proves that indices 9/10 remain only
at their original bevel coordinates. Focus retains its native white-face and
cyan-contour treatment.

Style-fix candidate:

`outputs/20260830_ggen_advance_fixed_action_graphics/ggen_advance_action_menu_ko_stylefix_candidate_20260830.gba`

SHA-256:

`13280b7f59c544ed751c8f260cee644206fd1238296f6379328770536d425c8b`

Manifest:

`analysis/ggen_advance_action_menu_ko_stylefix_20260830.json`

Runtime-color preview:

`outputs/20260830_ggen_advance_fixed_action_graphics/ggen_advance_action_menu_ko_stylefix_preview_20260830.png`

## Explicit palette-role correction

The next measured clarification fixes the composition explicitly rather than
deriving text colors from the native resource distribution:

- normal: yellow background and yellow glyph face (index 11), with a single
  8-neighbour brown contour layer (index 5);
- focus: sky-blue background (index 8), white glyph face (index 12), with a
  single 8-neighbour navy contour layer (index 4).

The contour is generated only in pixels immediately adjacent to the Korean
glyph mask. No contour color is used as the surrounding panel fill.

Palette-fix candidate:

`outputs/20260830_ggen_advance_fixed_action_graphics/ggen_advance_action_menu_ko_palettefix_candidate_20260830.gba`

SHA-256:

`8a206d81092162df77a5057563daa91c81ee5f0ff86a8c22a8b1058245e907d0`

Manifest:

`analysis/ggen_advance_action_menu_ko_palettefix_20260830.json`

Preview:

`outputs/20260830_ggen_advance_fixed_action_graphics/ggen_advance_action_menu_ko_palettefix_preview_20260830.png`

## Focus fill bounds correction

The focus sky-blue fill is limited to the bounding box occupied by the normal
panel's orange/yellow bevel: `x=1..30`, `y=1..14` inside each 32x16 label.
Pixels outside that box remain the same index-11 yellow used by the normal
state. The white face and one-pixel navy contour are unchanged.

Candidate:

`outputs/20260830_ggen_advance_fixed_action_graphics/ggen_advance_action_menu_ko_focusbounds_candidate_20260830.gba`

SHA-256:

`ce9f9fc7414f7ea1fde3237f73e125fe6322dd763fa8544387d26787caf838ac`

Manifest:

`analysis/ggen_advance_action_menu_ko_focusbounds_20260830.json`

Preview:

`outputs/20260830_ggen_advance_fixed_action_graphics/ggen_advance_action_menu_ko_focusbounds_preview_20260830.png`

## Normal background match to the turn-end menu

Screenshot measurement identifies the normal button fill in the UI containing
the turn-end command as RGB `(254, 231, 65)`, which is action palette index 10.
The action-menu normal background now uses index 10 while retaining index 11
for the pale-yellow Korean face and index 5 for its one-pixel brown contour.
The one-pixel area outside the bounded focus fill also uses the same index-10
normal background.

Candidate:

`outputs/20260830_ggen_advance_fixed_action_graphics/ggen_advance_action_menu_ko_normalbgfix_candidate_20260830.gba`

SHA-256:

`032ce7b10cfddfd34325400441778827761bc2b058421520b34eb338577bf1cc`

Manifest:

`analysis/ggen_advance_action_menu_ko_normalbgfix_20260830.json`

Preview:

`outputs/20260830_ggen_advance_fixed_action_graphics/ggen_advance_action_menu_ko_normalbgfix_preview_20260830.png`

## Rounded focus fill mask

The focus fill now uses the exact union of the normal panel's index-10 bright-
yellow interior and index-9 orange bevel pixels instead of their rectangular
bounding box. This produces a 416-pixel rounded sky-blue region. The remaining
96 pixels stay index-11 pale yellow, matching the normal outer region. A static
gate also prevents sky-blue, navy, or white focus pixels from escaping that
rounded mask.

Candidate:

`outputs/20260830_ggen_advance_fixed_action_graphics/ggen_advance_action_menu_ko_focusrounded_candidate_20260830.gba`

SHA-256:

`c9d02ea744c0c143d612dc83e3955946813669d9abd32fd972c8a04043450a0d`

Manifest:

`analysis/ggen_advance_action_menu_ko_focusrounded_20260830.json`

Preview:

`outputs/20260830_ggen_advance_fixed_action_graphics/ggen_advance_action_menu_ko_focusrounded_preview_20260830.png`

## Main-TIP promotion

The user-approved rounded-focus result was rebuilt on top of the then-current
main TIP `4810effa2bde8dc1b61f3a2dde01109d22a330235a4cbb61513f630c1892c5e0`
so the intervening unit-name promotion remained intact. The rebased candidate
passed all action-menu gates and was promoted through the canonical promotion
tool.

- promotion reason: `approved_action_menu_focusrounded_20260830`
- canonical main TIP SHA-256: `f033b480bb36aabed3533bdea6dc0ff6da7884ea4ff1e9372cf662edb3295fd6`
- source candidate: `outputs/20260830_ggen_advance_fixed_action_graphics/ggen_advance_action_menu_ko_focusrounded_main_tip_candidate_20260830.gba`
- source manifest: `analysis/ggen_advance_action_menu_ko_focusrounded_main_tip_20260830.json`
- previous main TIP backup: `integrated/main_tip/backups/20260830T062015Z_approved_action_menu_focusrounded_20260830/`
