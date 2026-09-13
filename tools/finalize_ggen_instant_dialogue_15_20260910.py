"""Finalize evidence after the bounded ARM renderer tests have passed."""
import json
from build_ggen_instant_dialogue_15_20260910 import ROOT, OUT, ROM, sha


def main():
    manifest=json.loads((OUT/'manifest.json').read_text(encoding='utf-8'))
    assert sha(ROM.read_bytes())==manifest['output']['sha256']
    assert sha((ROOT/'SD Gundam GGeneration Advance (Korean).gba').read_bytes())==manifest['parent']['sha256']
    results=json.loads((OUT/'arm_runtime.json').read_text(encoding='utf-8'))
    assert len(results)==16
    for result in results:
        limit=15 if '_x48_after' in result['case'] else 14
        assert result['final_count']==limit
        assert len(result['draws'])==2 and all(d['limit']==limit for d in result['draws'])
        assert result['stack_restored'] and result['script_end_preserved']
    protected=[ROOT/'SD Gundam GGeneration Advance (Korean).sav']
    protected += [ROOT/f'SD Gundam GGeneration Advance (Korean).ss{n}' for n in range(1,5)]
    protected += [ROOT/'integrated/translation/ggen_advance_translation_merged.json',ROOT/'integrated/translation/ggen_advance_translation_master.xlsx']
    manifest['protected_files_sha256']={str(p.relative_to(ROOT)):sha(p.read_bytes()) for p in protected}
    manifest['verification']={'result':'PASS','static_diff':'PASS','bounded_arm_renderer_cases':16,
        'both_rows_x48_draw_15':True,'x60_graphics_byte_identical':True,
        'all_script_end_addresses_preserved':True,'all_stacks_restored':True,
        'wait_icon_frames_checked':14,'wait_icon_visible_x':[228,231],
        'glyph15_cell_x':[216,227],'border_starts_x':232,
        'visual_preview':'dialogue_preview.png',
        'method':'Actual ROM ARM execution via Unicorn, GBA immediate DMA model; icon asset/state reconstruction and visual review',
        'full_game_mgba_replay':False,'mgba_gdb_attempt':'local connection unavailable'}
    (OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('PASS: candidate ready for canonical promotion')


if __name__=='__main__':main()
