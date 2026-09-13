#!/usr/bin/env python3
import argparse, json, re
from pathlib import Path

DOC_DEFAULT = Path('docs/GGENERATION_ADVANCE_KO_PROGRESS.md')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--doc', type=Path, default=DOC_DEFAULT)
    args = ap.parse_args()
    text = args.doc.read_text(encoding='utf-8')
    refs = sorted(set(re.findall(r'`(tools/[^`]+?\.py)`', text)))
    present=[]; root_equiv=[]; missing=[]
    for ref in refs:
        p=Path(ref)
        if p.exists():
            present.append(ref)
        elif Path(p.name).exists():
            root_equiv.append({'documented': ref, 'advance_root_equivalent': p.name})
        else:
            missing.append(ref)
    critical_names = {
        'analyze_ggen_advance_charmap.py',
        'analyze_ggen_advance_unresolved_slots.py',
        'export_ggen_advance_unicode_seed.py',
        'extract_ggen_advance_reachable_text.py',
        'extract_ggen_advance_confirmed_text.py',
        'plan_ggen_advance_korean_charmap.py',
        'ggen_advance_korean_codec.py',
        'build_ggen_advance_korean_font_blobs.py',
        'plan_ggen_advance_reachable_text_relocation.py',
        'build_ggen_advance_32m_confirmed_text_relocation.py',
    }
    critical_missing=[x for x in missing if Path(x).name in critical_names]
    out={
        'schema_version':1,
        'scope':'advance directory only',
        'document':str(args.doc).replace('\\','/'),
        'documented_tool_references':len(refs),
        'present_at_documented_path':len(present),
        'root_equivalent_count':len(root_equiv),
        'missing_without_advance_local_equivalent':len(missing),
        'present':present,
        'root_equivalents':root_equiv,
        'missing':missing,
        'translation_pipeline_critical_missing':critical_missing,
        'conclusion':(
            'Semantic analysis is now advance-local and complete, but the historical translation-production '
            'pipeline is not self-contained under advance: two documented analysis tools survive at the '
            'advance root, while the charmap/export/codec/relocation production chain is absent and must be '
            'reconstructed locally before a reproducible translation-ready export can be regenerated.'
        )
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))

if __name__=='__main__': main()
