# CareFlow Evidence Review Packet — CF-PA-001

**DOCUMENTATION_READY** · revision 2 · as of 2026-10-13

Request: PA-B · type: prior_authorization · patient: SYN-CF-B · encounter: ENC-A

Service: careflow-demo / specialty-consult · requested date: 2026-11-01

Rules: careflow-pa / 1.0.0 · synthetic_project_checklist

Packet SHA-256: 5b7d8615a7d0a3ebd2687cd02a0e834b8fc7b0f691a0473bcd11ad58a6a1ce95
Rules SHA-256: 73850a73cacb35188f20026cff0dc880262ad39ed63c514b6c66620fdd6a6b50

Documentation readiness only; no medical approval, payment eligibility or compliance certification.

Exact provenance validates location, not clinical interpretation or signature authenticity. Supplied assertions require independent human or advanced-AI review when warranted.

## Documentation checks

| Rule / version | Requirement | Trigger | Result | Fact IDs |
| --- | --- | --- | --- | --- |
| CF-DOC-001 / 1.0.0 | request_intent | always; value=True | SUPPORTED | fact-dbe37f401576f7c6 |
| CF-DOC-002 / 1.0.0 | referral_reason | always; value=True | SUPPORTED | fact-32847b7b9dacb01e |
| CF-DOC-003 / 1.0.0 | clinical_summary | always; value=True | SUPPORTED | fact-2c3b2c11918d20cf |
| CF-DOC-004 / 1.0.0 | investigation_result | investigation_required == true; value=False | NOT_APPLICABLE | fact-5efd6ca12ccd910e |
| CF-DOC-005 / 1.0.0 | therapy_completed | therapy_required == true; value=False | NOT_APPLICABLE | fact-3a47d927c1cedaab |
| CF-PA-001 / 1.0.0 | pa_form | always; value=True | SUPPORTED | fact-8cf5e5112acdf0ba |
| CF-PA-002 / 1.0.0 | payer_context | always; value=True | SUPPORTED | fact-f6234458491c54af |

## Check details and actionable review questions

### CF-DOC-001 — SUPPORTED

Request-specific provider intent is documented.

Traceable assertions support the required document or fact.

### CF-DOC-002 — SUPPORTED

The requested service has a documented clinical reason.

Traceable assertions support the required document or fact.

### CF-DOC-003 — SUPPORTED

A request-specific clinical summary is available.

Traceable assertions support the required document or fact.

### CF-DOC-004 — NOT_APPLICABLE

Attach results when the documented request requires an investigation.

Source-linked explicit false trigger establishes inapplicability.

### CF-DOC-005 — NOT_APPLICABLE

Attach documented prior therapy when the request explicitly requires it.

Source-linked explicit false trigger establishes inapplicability.

### CF-PA-001 — SUPPORTED

A request-specific PA form is available.

Traceable assertions support the required document or fact.

### CF-PA-002 — SUPPORTED

The supplied payer/request identifiers are documented.

Traceable assertions support the required document or fact.


## Evidence gaps

No missing requirements under this exact checklist.

## Assertions and exact evidence

### fact-dbe37f401576f7c6 — request_intent — ORIGINAL

Assertion: ASSERTED_PRESENT · effective: [True] · origin: structured_mapping

```
Provider requests specialty consultation for PA-B.
```

Request/patient/service: PA-B / SYN-CF-B / careflow-demo:specialty-consult

Amends: None

Source: doc-dbe37f401576f7c6 · locator: /sources/0/content/statement · hash: afaa0a3f634670d6e9b0c5bc265d2748a200130c73c21a8f8a4ea003a0977db8

Unicode offsets: [None, None) · method: input_json_pointer

```
Provider requests specialty consultation for PA-B.
```


### fact-32847b7b9dacb01e — referral_reason — ORIGINAL

Assertion: ASSERTED_PRESENT · effective: [True] · origin: structured_mapping

```
Reason for PA-B: persistent symptoms requiring specialist evaluation.
```

Request/patient/service: PA-B / SYN-CF-B / careflow-demo:specialty-consult

Amends: None

Source: doc-32847b7b9dacb01e · locator: /sources/1/content/statement · hash: 845de8da1a79377fb4c0afd6165e6af768a9e6eeef246db5f37e3963d77a666d

Unicode offsets: [None, None) · method: input_json_pointer

```
Reason for PA-B: persistent symptoms requiring specialist evaluation.
```


### fact-5efd6ca12ccd910e — investigation_required — ORIGINAL

Assertion: ASSERTED_ABSENT · effective: [False] · origin: structured_mapping

```
No investigation result is required for PA-B in this constructed request.
```

Request/patient/service: PA-B / SYN-CF-B / careflow-demo:specialty-consult

Amends: None

Source: doc-5efd6ca12ccd910e · locator: /sources/2/content/statement · hash: d39f91482c9649c57cb28f3e29dbda813ee381249e31f25163dc2f98dfe6a340

Unicode offsets: [None, None) · method: input_json_pointer

```
No investigation result is required for PA-B in this constructed request.
```


### fact-3a47d927c1cedaab — therapy_required — ORIGINAL

Assertion: ASSERTED_ABSENT · effective: [False] · origin: structured_mapping

```
Prior therapy documentation is not required for PA-B.
```

Request/patient/service: PA-B / SYN-CF-B / careflow-demo:specialty-consult

Amends: None

Source: doc-3a47d927c1cedaab · locator: /sources/3/content/statement · hash: 08e3b6542d657a54d7f852fdca2db3a1a8addc0c900c7540abe4e50f381479fc

Unicode offsets: [None, None) · method: input_json_pointer

```
Prior therapy documentation is not required for PA-B.
```


### fact-8cf5e5112acdf0ba — pa_form — ORIGINAL

Assertion: ASSERTED_PRESENT · effective: [True] · origin: structured_mapping

```
PA request form for PA-B is attached.
```

Request/patient/service: PA-B / SYN-CF-B / careflow-demo:specialty-consult

Amends: None

Source: doc-8cf5e5112acdf0ba · locator: /sources/4/content/statement · hash: 5a82688e70d8fd7415ed76d50c9aec5b70b3222e4da0f6448d6c3e47e02cabd4

Unicode offsets: [None, None) · method: input_json_pointer

```
PA request form for PA-B is attached.
```


### fact-f6234458491c54af — payer_context — ORIGINAL

Assertion: ASSERTED_PRESENT · effective: [True] · origin: structured_mapping

```
Constructed payer request identifier for PA-B: DEMO-PLAN. This is not eligibility verification.
```

Request/patient/service: PA-B / SYN-CF-B / careflow-demo:specialty-consult

Amends: None

Source: doc-f6234458491c54af · locator: /sources/5/content/statement · hash: df331a46bc2ed414e1ac02e428d5ca24fa8a62d62d7b221743fda382973dce5a

Unicode offsets: [None, None) · method: input_json_pointer

```
Constructed payer request identifier for PA-B: DEMO-PLAN. This is not eligibility verification.
```


### fact-2c3b2c11918d20cf — clinical_summary — ORIGINAL

Assertion: ASSERTED_PRESENT · effective: [True] · origin: structured_mapping

```
Clinical summary for PA-B: symptoms, relevant history and examination documented.
```

Request/patient/service: PA-B / SYN-CF-B / careflow-demo:specialty-consult

Amends: None

Source: doc-2c3b2c11918d20cf · locator: /sources/6/content/statement · hash: c62e19f252319ac967ad3de420d8b733eab938dbc5ca6b41fbc4fb8bf7459b52

Unicode offsets: [None, None) · method: input_json_pointer

```
Clinical summary for PA-B: symptoms, relevant history and examination documented.
```


## Unresolved conflicts and source relationships

```json
[]
```

```json
{
  "version": "claims-review-relationships/1",
  "relationships": [],
  "derived": {
    "fact-dbe37f401576f7c6": {
      "content/value": {
        "values": [
          true
        ],
        "status": "ORIGINAL",
        "source_ids": [
          "fact-dbe37f401576f7c6"
        ]
      },
      "event_date": {
        "values": [
          null
        ],
        "status": "ORIGINAL",
        "source_ids": [
          "fact-dbe37f401576f7c6"
        ]
      }
    },
    "fact-32847b7b9dacb01e": {
      "content/value": {
        "values": [
          true
        ],
        "status": "ORIGINAL",
        "source_ids": [
          "fact-32847b7b9dacb01e"
        ]
      },
      "event_date": {
        "values": [
          null
        ],
        "status": "ORIGINAL",
        "source_ids": [
          "fact-32847b7b9dacb01e"
        ]
      }
    },
    "fact-5efd6ca12ccd910e": {
      "content/value": {
        "values": [
          false
        ],
        "status": "ORIGINAL",
        "source_ids": [
          "fact-5efd6ca12ccd910e"
        ]
      },
      "event_date": {
        "values": [
          null
        ],
        "status": "ORIGINAL",
        "source_ids": [
          "fact-5efd6ca12ccd910e"
        ]
      }
    },
    "fact-3a47d927c1cedaab": {
      "content/value": {
        "values": [
          false
        ],
        "status": "ORIGINAL",
        "source_ids": [
          "fact-3a47d927c1cedaab"
        ]
      },
      "event_date": {
        "values": [
          null
        ],
        "status": "ORIGINAL",
        "source_ids": [
          "fact-3a47d927c1cedaab"
        ]
      }
    },
    "fact-8cf5e5112acdf0ba": {
      "content/value": {
        "values": [
          true
        ],
        "status": "ORIGINAL",
        "source_ids": [
          "fact-8cf5e5112acdf0ba"
        ]
      },
      "event_date": {
        "values": [
          null
        ],
        "status": "ORIGINAL",
        "source_ids": [
          "fact-8cf5e5112acdf0ba"
        ]
      }
    },
    "fact-f6234458491c54af": {
      "content/value": {
        "values": [
          true
        ],
        "status": "ORIGINAL",
        "source_ids": [
          "fact-f6234458491c54af"
        ]
      },
      "event_date": {
        "values": [
          null
        ],
        "status": "ORIGINAL",
        "source_ids": [
          "fact-f6234458491c54af"
        ]
      }
    },
    "fact-2c3b2c11918d20cf": {
      "content/value": {
        "values": [
          true
        ],
        "status": "ORIGINAL",
        "source_ids": [
          "fact-2c3b2c11918d20cf"
        ]
      },
      "event_date": {
        "values": [
          null
        ],
        "status": "ORIGINAL",
        "source_ids": [
          "fact-2c3b2c11918d20cf"
        ]
      }
    }
  },
  "authority_limit": "Explicit source declarations only; signature authenticity/provider credentials not independently verified."
}
```

## Optional risk review

```json
{
  "recommended": false,
  "reasons": [],
  "reviewer_types": [
    "human",
    "advanced_ai"
  ],
  "mandatory": false
}
```

## Reviewer opinions (separate from rule results)

```json
{
  "case_id": "CF-PA-001",
  "event_type": "REVIEW_RECORDED",
  "payload": {
    "basis_packet_sha256": "c9129f3c40facc6d21721598614a4ee362033bd4a02e59ebbde896ee49e9682e",
    "basis_revision": 1,
    "fact_ids": [],
    "judgment": "AGREE",
    "model": null,
    "model_version": null,
    "proposed_actions": [],
    "reason": "New request-specific summary received; retain the original gap report.",
    "reviewer_id": "demo-document-intake",
    "reviewer_type": "human"
  },
  "previous_sha256": "5bc9c8b6ebff566e0ab9f9af8f3a28ed05adea7bcce2e3e2fbaf8f165301bb0b",
  "sequence": 2,
  "timestamp": "2026-10-13T09:52:02.746839+00:00",
  "event_sha256": "53f18c6c0328f14495ad470120966f25f31a91e57d2d6673562bd3f3ce7a0f6c"
}
```

## Preserved original documents

```json
[
  {
    "source_id": "doc-dbe37f401576f7c6",
    "availability_scope_issue": null,
    "referenced_by_fact_ids": [
      "fact-dbe37f401576f7c6"
    ]
  },
  {
    "source_id": "doc-32847b7b9dacb01e",
    "availability_scope_issue": null,
    "referenced_by_fact_ids": [
      "fact-32847b7b9dacb01e"
    ]
  },
  {
    "source_id": "doc-5efd6ca12ccd910e",
    "availability_scope_issue": null,
    "referenced_by_fact_ids": [
      "fact-5efd6ca12ccd910e"
    ]
  },
  {
    "source_id": "doc-3a47d927c1cedaab",
    "availability_scope_issue": null,
    "referenced_by_fact_ids": [
      "fact-3a47d927c1cedaab"
    ]
  },
  {
    "source_id": "doc-8cf5e5112acdf0ba",
    "availability_scope_issue": null,
    "referenced_by_fact_ids": [
      "fact-8cf5e5112acdf0ba"
    ]
  },
  {
    "source_id": "doc-f6234458491c54af",
    "availability_scope_issue": null,
    "referenced_by_fact_ids": [
      "fact-f6234458491c54af"
    ]
  },
  {
    "source_id": "doc-2c3b2c11918d20cf",
    "availability_scope_issue": null,
    "referenced_by_fact_ids": [
      "fact-2c3b2c11918d20cf"
    ]
  }
]
```

### doc-dbe37f401576f7c6

```json
{
  "source_id": "doc-dbe37f401576f7c6",
  "patient_id": "SYN-CF-B",
  "encounter_id": "ENC-A",
  "available_at": "2026-10-10",
  "origin": "constructed_synthetic",
  "source_kind": "structured_record",
  "recorded_at": "2026-10-09",
  "event_date": "2026-10-09",
  "record_type": "order",
  "event_link_id": null,
  "content": {
    "documented": true,
    "statement": "Provider requests specialty consultation for PA-B."
  },
  "availability_basis": "explicit_case_metadata",
  "original_locator": null
}
```

### doc-32847b7b9dacb01e

```json
{
  "source_id": "doc-32847b7b9dacb01e",
  "patient_id": "SYN-CF-B",
  "encounter_id": "ENC-A",
  "available_at": "2026-10-10",
  "origin": "constructed_synthetic",
  "source_kind": "structured_record",
  "recorded_at": "2026-10-09",
  "event_date": "2026-10-09",
  "record_type": "order",
  "event_link_id": null,
  "content": {
    "documented": true,
    "statement": "Reason for PA-B: persistent symptoms requiring specialist evaluation."
  },
  "availability_basis": "explicit_case_metadata",
  "original_locator": null
}
```

### doc-5efd6ca12ccd910e

```json
{
  "source_id": "doc-5efd6ca12ccd910e",
  "patient_id": "SYN-CF-B",
  "encounter_id": "ENC-A",
  "available_at": "2026-10-10",
  "origin": "constructed_synthetic",
  "source_kind": "structured_record",
  "recorded_at": "2026-10-09",
  "event_date": "2026-10-09",
  "record_type": "order",
  "event_link_id": null,
  "content": {
    "documented": false,
    "statement": "No investigation result is required for PA-B in this constructed request."
  },
  "availability_basis": "explicit_case_metadata",
  "original_locator": null
}
```

### doc-3a47d927c1cedaab

```json
{
  "source_id": "doc-3a47d927c1cedaab",
  "patient_id": "SYN-CF-B",
  "encounter_id": "ENC-A",
  "available_at": "2026-10-10",
  "origin": "constructed_synthetic",
  "source_kind": "structured_record",
  "recorded_at": "2026-10-09",
  "event_date": "2026-10-09",
  "record_type": "order",
  "event_link_id": null,
  "content": {
    "documented": false,
    "statement": "Prior therapy documentation is not required for PA-B."
  },
  "availability_basis": "explicit_case_metadata",
  "original_locator": null
}
```

### doc-8cf5e5112acdf0ba

```json
{
  "source_id": "doc-8cf5e5112acdf0ba",
  "patient_id": "SYN-CF-B",
  "encounter_id": "ENC-A",
  "available_at": "2026-10-10",
  "origin": "constructed_synthetic",
  "source_kind": "structured_record",
  "recorded_at": "2026-10-09",
  "event_date": "2026-10-09",
  "record_type": "order",
  "event_link_id": null,
  "content": {
    "documented": true,
    "statement": "PA request form for PA-B is attached."
  },
  "availability_basis": "explicit_case_metadata",
  "original_locator": null
}
```

### doc-f6234458491c54af

```json
{
  "source_id": "doc-f6234458491c54af",
  "patient_id": "SYN-CF-B",
  "encounter_id": "ENC-A",
  "available_at": "2026-10-10",
  "origin": "constructed_synthetic",
  "source_kind": "structured_record",
  "recorded_at": "2026-10-09",
  "event_date": "2026-10-09",
  "record_type": "order",
  "event_link_id": null,
  "content": {
    "documented": true,
    "statement": "Constructed payer request identifier for PA-B: DEMO-PLAN. This is not eligibility verification."
  },
  "availability_basis": "explicit_case_metadata",
  "original_locator": null
}
```

### doc-2c3b2c11918d20cf

```json
{
  "source_id": "doc-2c3b2c11918d20cf",
  "patient_id": "SYN-CF-B",
  "encounter_id": "ENC-A",
  "available_at": "2026-10-10",
  "origin": "constructed_synthetic",
  "source_kind": "structured_record",
  "recorded_at": "2026-10-09",
  "event_date": "2026-10-09",
  "record_type": "order",
  "event_link_id": null,
  "content": {
    "statement": "Clinical summary for PA-B: symptoms, relevant history and examination documented.",
    "documented": true
  },
  "availability_basis": "explicit_case_metadata",
  "original_locator": null
}
```

