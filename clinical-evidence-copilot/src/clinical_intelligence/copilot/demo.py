"""Synthetic, authored software examples; no rules parse these into facts."""
import json
from importlib.resources import files

from .runtime import create_from_bundle


def bundles():
    return json.loads(files('clinical_intelligence.copilot').joinpath('resources/demo.json').read_text(encoding='utf-8'))


def seed_demo(store):
    saved = []
    for bundle in bundles():
        try:
            p = store.get(bundle['case_id'])
        except KeyError:
            p = create_from_bundle(bundle)
            store.save(p, expected_version=0)
        saved.append(p)
    return saved
