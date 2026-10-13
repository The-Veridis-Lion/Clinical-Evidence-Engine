"""Raw label integrity across valid, malformed and structurally broken cases."""
import json

import pytest

from clinical_intelligence.careflow.evaluation.corpus import freeze_corpus, load_acn
from clinical_intelligence.careflow.evaluation.references import freeze_acn_reference_inventory


def setup_inventory(tmp_path):
    rows = [{'idx': i, 'note': f'Note {i}', 'full_note': f'Full note {i}', 'conversation': f'Dialogue {i}', 'summary': value}
            for i, value in enumerate(['{"symptom":"pain"}', '{"symptom":"pain\nwhen moving"}', '{"diagnosis":broken}'])]
    source, frozen = tmp_path / 'raw.jsonl', tmp_path / 'frozen'
    source.write_text('\n'.join(json.dumps(r) for r in rows) + '\n', encoding='utf-8')
    freeze_corpus(load_acn(source), frozen, development_groups=2, holdout_groups=1, source_metadata={})
    return source, frozen


def test_original_reference_errors_stay_frozen_and_no_case_is_dropped(tmp_path):
    source, frozen = setup_inventory(tmp_path)
    original_manifest = (frozen / 'manifest.json').read_bytes()
    original_documents = (frozen / 'documents.jsonl').read_bytes()
    output = tmp_path / 'references'
    result = freeze_acn_reference_inventory(source, frozen, output)
    assert result['cases'] == 3 and result['strict_json_valid'] == 1 and result['strict_json_invalid'] == 2
    assert result['permissive_diagnostic_only'] == 1 and result['unparsed'] == 1
    references = [json.loads(line) for line in (output / 'references.jsonl').read_text().splitlines()]
    assert all(r['diagnostic_used_for_scoring'] is False and r['clinical_gold'] is False for r in references)
    assert len([r for r in references if r['strict_parse_error']]) == 2
    assert (frozen / 'manifest.json').read_bytes() == original_manifest
    assert (frozen / 'documents.jsonl').read_bytes() == original_documents
    assert freeze_acn_reference_inventory(source, frozen, output) == result


@pytest.mark.parametrize('mutation', ['raw_label', 'source_text'])
def test_changed_original_archive_cannot_replace_reference_inventory(tmp_path, mutation):
    source, frozen = setup_inventory(tmp_path)
    rows = [json.loads(line) for line in source.read_text().splitlines()]
    rows[0]['summary' if mutation == 'raw_label' else 'full_note'] = 'changed'
    source.write_text('\n'.join(json.dumps(r) for r in rows), encoding='utf-8')
    with pytest.raises(ValueError, match='differs'):
        freeze_acn_reference_inventory(source, frozen, tmp_path / 'references')
