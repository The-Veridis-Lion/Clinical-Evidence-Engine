"""Small HTTP facade shared by the workbench and the two existing products."""
from urllib.parse import unquote


def route(workbench, method, path, query=None, body=None):
    parts = [unquote(p) for p in path.strip('/').split('/')]
    query, body = query or {}, body or {}
    if parts == ['ui', 'patients']:
        if method == 'GET':
            return workbench.patients(), 200
        if method == 'POST':
            return workbench.create_patient(body), 201
    if len(parts) < 4 or parts[:2] != ['ui', 'patients']:
        raise KeyError('Unknown workbench endpoint')
    patient, suffix = parts[2], parts[3:]
    if method == 'GET':
        if suffix == ['workspace']:
            return workbench.workspace(patient), 200
        if suffix == ['audit']:
            return workbench.audit(patient), 200
        if suffix == ['query-capabilities']:
            workbench.patient(patient)
            from .patient_queries import capabilities
            return capabilities(), 200
        if len(suffix) == 3 and suffix[0] == 'encounters' and suffix[2] == 'soap':
            return workbench.soap(patient, suffix[1]), 200
        if len(suffix) == 2 and suffix[0] == 'evidence':
            version = int(query['version'][0]) if 'version' in query else None
            return workbench.evidence(patient, suffix[1], version), 200
        if suffix == ['careflow', 'requests']:
            return workbench.cf_requests(patient), 200
        if len(suffix) == 3 and suffix[:2] == ['careflow', 'requests']:
            return workbench.cf_detail(patient, suffix[2]), 200
    if method == 'POST':
        if suffix == ['files']:
            return workbench.upload(patient, body), 202
        if suffix == ['queries']:
            return workbench.query(patient, body), 200
        if len(suffix) == 4 and suffix[0] == 'facts' and suffix[3] == 'corrections':
            return workbench.correct(patient, suffix[1], suffix[2], body), 200
        if suffix == ['soap', 'polish']:
            from .workbench_calls import polish_soap
            return polish_soap(workbench, patient, body), 200
        if suffix == ['careflow', 'requests']:
            return workbench.cf_create(patient, body), 201
        if len(suffix) == 4 and suffix[:2] == ['careflow', 'requests']:
            return workbench.cf_action(patient, suffix[2], suffix[3], body), 200
    raise KeyError('Unknown workbench endpoint')
