"""Candidate for the actual supply loop and shared entry animation.

Reuses the approved gated overlay. Flash removal remains runtime-pending:
the original frame helper includes a VBlank wait before the overlay runs.
"""
from pathlib import Path
import hashlib
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_ggen_advance_owned_count_ab_candidates_20260903 as thumb
import build_ggen_advance_owned_count_live_overlay_candidate_20260904 as overlay
from ggen_advance_project_paths import ADVANCE_ROOT, MAIN_TIP_ROM, MAIN_TIP_MANIFEST, advance_relative

EXPECTED = 'f4ec36f115ea03af0b8f40f84686a5f6f5b2b5526e5d857b84703a3bcc8c3db4'
SITES = {0x0806E6F0: 'supply steady loop', 0x0806E0AE: 'shared entry animation'}
OUT = ADVANCE_ROOT / 'outputs/20260905_ggen_advance_owned_count_actual_paths'
STEM = 'ggen_advance_owned_count_actual_paths_candidate_20260905'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def gate(condition, message):
    if not condition:
        raise SystemExit(message)


def main():
    parent = MAIN_TIP_ROM.read_bytes()
    gate(digest(parent) == EXPECTED, 'main ROM hash drift')
    gate(json.loads(MAIN_TIP_MANIFEST.read_text(encoding='utf-8'))['sha256'] == EXPECTED, 'main manifest drift')
    stub = overlay.build_stub_clean()
    gate(parent[overlay.STUB_FILE:overlay.STUB_FILE + len(stub)] == stub, 'approved stub drift')
    gate(thumb.thumb_bl_target(parent, 0x0806EB3E) == overlay.STUB_ADDR, 'disposal hook drift')
    # Verify the menu branch and the shared entry call before selecting sites.
    for site, target in {0x0806DA78: 0x0806E778, 0x0806DA9A: 0x0806E37C,
                         0x0806E800: 0x0806E048, 0x0806E404: 0x0806E048}.items():
        gate(thumb.thumb_bl_target(parent, site) == target, f'controller call drift: {site:08X}')
    child = bytearray(parent)
    allowed = set()
    patches = []
    for site, purpose in SITES.items():
        gate(thumb.thumb_bl_target(parent, site) == 0x08063194, f'frame call drift: {site:08X}')
        off = site - 0x08000000
        replacement = thumb.encode_thumb_bl(site, overlay.STUB_ADDR)
        child[off:off + 4] = replacement
        allowed.update(range(off, off + 4))
        gate(thumb.thumb_bl_target(child, site) == overlay.STUB_ADDR, 'BL verification failed')
        patches.append(dict(address=f'0x{site:08X}', purpose=purpose,
                            before=parent[off:off + 4].hex(), after=replacement.hex()))
    changed = [i for i, (a, b) in enumerate(zip(parent, child)) if a != b]
    gate(bool(changed) and set(changed) <= allowed, 'diff escaped two BLs')
    for site in (0x0806D384, 0x0806D398):
        gate(thumb.thumb_bl_target(child, site) == 0x08063194, 'failed D350 hook unexpectedly retained')
    sav_path = ADVANCE_ROOT / 'SD Gundam GGeneration Advance (Korean).sav'
    sav = sav_path.read_bytes()
    OUT.mkdir(parents=True, exist_ok=True)
    rom_out, sav_out = OUT / (STEM + '.gba'), OUT / (STEM + '.sav')
    # Do not overwrite a user's subsequent gameplay save on a repeated build.
    if sav_out.exists():
        gate(sav_out.read_bytes() == sav, 'output SAV contains user changes; choose a fresh output')
    rom_out.write_bytes(child)
    sav_out.write_bytes(sav)
    gate(rom_out.read_bytes() == child and sav_out.read_bytes() == sav, 'output readback failed')
    gate(MAIN_TIP_ROM.read_bytes() == parent and sav_path.read_bytes() == sav, 'canonical inputs changed')
    report = dict(
        kind=STEM, status='candidate_not_promoted',
        source_sha256=digest(parent), output=dict(path=advance_relative(rom_out), sha256=digest(child), size=len(child)),
        sav=dict(path=advance_relative(sav_out), sha256=digest(sav)),
        patches=patches, changed_bytes=len(changed),
        verification=dict(static='PASS', runtime='PENDING', approved_overlay_and_payload_preserved=True,
                          disposal_hook_preserved=True, failed_D350_hooks_absent=True, input_files_unchanged=True),
        rationale='Supply uses E6F0; both entry paths call E048, whose animation loop calls E0AE before the steady loop.',
        limitations='Overlay still runs after a frame helper containing VBlankIntrWait. Earliest visible frame and gate timing require runtime observation; flash elimination is not yet proven.',
        corrections=['0300177C is input state, not transfer-completion status.',
                     'D350/CFC4 ownership of the visible label was not established.'],
        checkpoints=['Fresh boot with the companion SAV; enter supply and check stable 소유수.',
                     'Move cursor in supply and disposal; check label, number, and bottom totals.',
                     'Re-enter both screens and observe Japanese flash during entry animation.'])
    (ADVANCE_ROOT / 'analysis' / (STEM + '.json')).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
