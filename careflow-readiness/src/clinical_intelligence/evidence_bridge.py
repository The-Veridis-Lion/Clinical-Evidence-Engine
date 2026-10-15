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


def verify_source_claim(source: dict, claim: dict, *, reviews=(), calibrations=None, source_interpretation_version=None, event_support_version=None) -> dict:
    core = verification_package()
    verification_identity()
    configuration = verification_configuration() if calibrations is None else {
        'engine_version': core.ENGINE_VERSION, 'calibrations': calibrations}
    options={'source_interpretation_version':source_interpretation_version} if source_interpretation_version is not None else {}
    result = core.EvidenceVerifier(calibrations=configuration['calibrations'], **options).verify(
        core.Source.model_validate(source), core.Claim.model_validate(claim), reviews=reviews)
    if event_support_version is not None:
        configuration=verification_event_configuration()
        if event_support_version != configuration['event_support_version']:
            raise ValueError('Unavailable explicit event source configuration')
        from evidence_verification.extensions.explicit_action import apply_explicit_action
        result=apply_explicit_action(source,claim,result,reviews=reviews)
    return result.model_dump(mode='json')


def verification_contextual_configuration() -> dict:
    """Explicit opt-in v2 scope; old packet configurations remain unchanged."""
    core=verification_package()
    folder=Path(core.__file__).resolve().parent
    value=json.loads((folder/'resources/contextual-calibration.json').read_text(encoding='utf-8'))
    if value.get('engine_version') != core.ENGINE_VERSION or value.get('version') != 'contextual-source-configuration/2':
        raise ValueError('Unavailable contextual source configuration')
    for name,expected in value['implementation_sha256'].items():
        path=folder/'extensions'/name
        if path.parent != folder/'extensions' or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
            raise ValueError('Contextual verifier changed after calibration; retain candidate and recalibrate')
    return {**verification_configuration(), 'contextual_calibrations':value['contextual_calibrations'],
        'contextual_version':value['version'],'contextual_implementation_sha256':value['implementation_sha256']}


def verify_contextual_source_claim(source: dict, claim: dict, *, reviews=(), calibrations=None, event_comparability_version=None, source_interpretation_version=None, risk_scope_version=None, local_scope_calibrations=None, event_support_version=None) -> dict:
    verification_identity()
    configuration=(verification_local_configuration() if risk_scope_version is not None
                   else verification_contextual_configuration())
    if event_support_version is not None:
        verification_event_configuration()
    from evidence_verification.extensions.contextual import verify_contextual_claim
    return verify_contextual_claim(source,claim,reviews=reviews,
        calibrations=configuration['contextual_calibrations'] if calibrations is None else calibrations,
        event_comparability_version=event_comparability_version, event_support_version=event_support_version,
        risk_scope_version=risk_scope_version, local_scope_calibrations=(
            configuration.get('local_scope_calibrations', []) if local_scope_calibrations is None else local_scope_calibrations),
        source_interpretation_version=source_interpretation_version).model_dump(mode='json')


def verification_local_configuration() -> dict:
    """Explicit finite local source proof; historical configurations stay unchanged."""
    core=verification_package()
    folder=Path(core.__file__).resolve().parent
    value=json.loads((folder/'resources/local-scope-calibration.json').read_text(encoding='utf-8'))
    if value.get('engine_version') != core.ENGINE_VERSION or value.get('version') != 'local-source-configuration/1':
        raise ValueError('Unavailable local source proof configuration')
    for name,expected in value['implementation_sha256'].items():
        path=folder/'extensions'/name
        if path.parent != folder/'extensions' or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
            raise ValueError('Local source proof changed after calibration; retain candidate and recalibrate')
    return {**verification_contextual_configuration(), 'risk_scope_version':value['risk_scope_version'],
        'local_scope_calibrations':value['local_scope_calibrations'],
        'local_scope_implementation_sha256':value['implementation_sha256']}


def verification_event_configuration() -> dict:
    """Explicit execution dimensions, with independent implementation identity."""
    core=verification_package()
    folder=Path(core.__file__).resolve().parent
    value=json.loads((folder/'resources/event-support.json').read_text(encoding='utf-8'))
    if value.get('version') != 'explicit-source-action/1' or value.get('engine_version') != core.ENGINE_VERSION:
        raise ValueError('Unavailable explicit event source configuration')
    for name,expected in value['implementation_sha256'].items():
        path=folder/'extensions'/name
        if path.parent != folder/'extensions' or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
            raise ValueError('Explicit event verifier changed after validation')
    return {'event_support_version':value['version'],
            'event_support_implementation_sha256':value['implementation_sha256']}
