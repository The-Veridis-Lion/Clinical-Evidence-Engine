"""Thin application bridge to the one versioned Evidence Verification package."""
from __future__ import annotations

import importlib
import hashlib
import json
import sys
from pathlib import Path

_loaded_identity = None


def verification_package():
    try:
        return importlib.import_module('evidence_verification')
    except ModuleNotFoundError as exc:
        if exc.name != 'evidence_verification':
            raise
        # A source checkout and an editable installation use the same package.
        for root in Path(__file__).resolve().parents:
            source = root / 'packages/evidence-verifier/src'
            if (source / 'evidence_verification/__init__.py').is_file():
                sys.path.insert(0, str(source))
                return importlib.import_module('evidence_verification')
        raise RuntimeError('Install packages/evidence-verifier before source verification') from exc


def verification_configuration() -> dict:
    core = verification_package()
    folder = Path(core.__file__).resolve().parent
    registry = folder / 'resources/calibration.json'
    calibrations = []
    if registry.is_file():
        value = json.loads(registry.read_text(encoding='utf-8'))
        if value['engine_version'] != core.ENGINE_VERSION:
            raise ValueError('Calibration belongs to a different verifier version')
        for name, expected in value['implementation_sha256'].items():
            path = folder / name
            if path.parent != folder or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError('Verifier changed after calibration; freeze a new candidate')
        calibrations = value['calibrations']
    return {'engine_version': core.ENGINE_VERSION, 'calibrations': calibrations}


def verification_identity() -> dict:
    global _loaded_identity
    core = verification_package()
    folder = Path(core.__file__).resolve().parent
    identity = {'engine_version':core.ENGINE_VERSION,
                'implementation_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest()
                                         for p in sorted(folder.glob('*.py'))}}
    if _loaded_identity is not None and _loaded_identity != identity:
        raise ValueError('Shared verifier changed on disk; restart before verifying a revision')
    _loaded_identity = identity
    configuration = verification_configuration()
    return {**identity, 'configuration':configuration,
            'configuration_sha256':hashlib.sha256(json.dumps(configuration,sort_keys=True,
                                         separators=(',',':')).encode('utf-8')).hexdigest()}


def verify_source_claim(source: dict, claim: dict, *, reviews=(), calibrations=None) -> dict:
    core = verification_package()
    verification_identity()
    configuration = verification_configuration() if calibrations is None else {
        'engine_version': core.ENGINE_VERSION, 'calibrations': calibrations}
    result = core.EvidenceVerifier(calibrations=configuration['calibrations']).verify(
        core.Source.model_validate(source), core.Claim.model_validate(claim), reviews=reviews)
    return result.model_dump(mode='json')
