# CareFlow Evidence Review Packet — CF-CORRECTION-001

**DOCUMENTATION_READY** · revision 2 · as of 2026-10-13

Request: REF-CORRECTION · type: referral · patient: SYN-CF-CORRECTION · encounter: ENC-A

Service: careflow-demo / specialty-consult · requested date: 2026-11-01

Rules: careflow-referral / 1.0.0 · synthetic_project_checklist

Packet SHA-256: 227c0aa5ea30ddd6de52ef8a6368a6ecea81e8e8ce0666d97a0f03285aef5d43
Rules SHA-256: ed68d9f0d7f48a59db27065a644ac39a55c7c4a360c1bb905663e64056f246c8

Documentation readiness only; no medical approval, payment eligibility or compliance certification.

Exact provenance validates location, not clinical interpretation or signature authenticity. Supplied assertions require independent human or advanced-AI review when warranted.

## Documentation checks

| Rule / version | Requirement | Trigger | Result | Fact IDs |
| --- | --- | --- | --- | --- |
| CF-DOC-001 / 1.0.0 | request_intent | always; value=True | SUPPORTED | fact-b8ca69991b7abf48 |
| CF-DOC-002 / 1.0.0 | referral_reason | always; value=True | SUPPORTED | fact-007717ef15f82a64 |
| CF-DOC-003 / 1.0.0 | clinical_summary | always; value=True | SUPPORTED | fact-40ee7175e8d1617f, fact-4d00e9180b9b6143 |
| CF-DOC-004 / 1.0.0 | investigation_result | investigation_required == true; value=False | NOT_APPLICABLE | fact-649af0caf46f5e65 |
| CF-DOC-005 / 1.0.0 | therapy_completed | therapy_required == true; value=False | NOT_APPLICABLE | fact-36b37fcd19ff534a |
| CF-REF-001 / 1.0.0 | destination | always; value=True | SUPPORTED | fact-086a9af79f3b4699 |

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

### CF-REF-001 — SUPPORTED

Referral destination is documented.

Traceable assertions support the required document or fact.


## Evidence gaps

No missing requirements under this exact checklist.

## Assertions and exact evidence

### fact-b8ca69991b7abf48 — request_intent — ORIGINAL

Assertion: ASSERTED_PRESENT · effective: [True] · origin: human

```
Provider requests specialty consultation for REF-CORRECTION.
```

Request/patient/service: REF-CORRECTION / SYN-CF-CORRECTION / careflow-demo:specialty-consult

Amends: None

Source: doc-b8ca69991b7abf48 · locator: doc-b8ca69991b7abf48:L001 · hash: 2cbe8e238fb7f6ab0bb290b96604906b85c702b214fa543afe04645bbf99bf40

Unicode offsets: [0, 60) · method: unicode_line_anchor

```
Provider requests specialty consultation for REF-CORRECTION.
```


### fact-007717ef15f82a64 — referral_reason — ORIGINAL

Assertion: ASSERTED_PRESENT · effective: [True] · origin: human

```
Reason for REF-CORRECTION: persistent symptoms requiring specialist evaluation.
```

Request/patient/service: REF-CORRECTION / SYN-CF-CORRECTION / careflow-demo:specialty-consult

Amends: None

Source: doc-007717ef15f82a64 · locator: doc-007717ef15f82a64:L001 · hash: 7be14ff9620b08f4376dc98263c40e31f5d7ca96680bd8a8985b4763044d4740

Unicode offsets: [0, 79) · method: unicode_line_anchor

```
Reason for REF-CORRECTION: persistent symptoms requiring specialist evaluation.
```


### fact-649af0caf46f5e65 — investigation_required — ORIGINAL

Assertion: ASSERTED_ABSENT · effective: [False] · origin: human

```
No investigation result is required for REF-CORRECTION in this constructed request.
```

Request/patient/service: REF-CORRECTION / SYN-CF-CORRECTION / careflow-demo:specialty-consult

Amends: None

Source: doc-649af0caf46f5e65 · locator: doc-649af0caf46f5e65:L001 · hash: 46688af16de35a5d6a4ca21c326836750d781fe8a9974302b1754e6fdf071b4a

Unicode offsets: [0, 83) · method: unicode_line_anchor

```
No investigation result is required for REF-CORRECTION in this constructed request.
```


### fact-36b37fcd19ff534a — therapy_required — ORIGINAL

Assertion: ASSERTED_ABSENT · effective: [False] · origin: human

```
Prior therapy documentation is not required for REF-CORRECTION.
```

Request/patient/service: REF-CORRECTION / SYN-CF-CORRECTION / careflow-demo:specialty-consult

Amends: None

Source: doc-36b37fcd19ff534a · locator: doc-36b37fcd19ff534a:L001 · hash: d9d0fe7d3ddb469db2044aba7b969513588e945fadbddcb9ef6ad096a5995e28

Unicode offsets: [0, 63) · method: unicode_line_anchor

```
Prior therapy documentation is not required for REF-CORRECTION.
```


### fact-086a9af79f3b4699 — destination — ORIGINAL

Assertion: ASSERTED_PRESENT · effective: [True] · origin: human

```
Destination for REF-CORRECTION: specialty clinic.
```

Request/patient/service: REF-CORRECTION / SYN-CF-CORRECTION / careflow-demo:specialty-consult

Amends: None

Source: doc-086a9af79f3b4699 · locator: doc-086a9af79f3b4699:L001 · hash: ac33cc5ecd9bb3b608c564e8b12265e23de20e1ebec6f91ce01ac74a8b436dfb

Unicode offsets: [0, 49) · method: unicode_line_anchor

```
Destination for REF-CORRECTION: specialty clinic.
```


### fact-40ee7175e8d1617f — clinical_summary — AMENDED

Assertion: ASSERTED_ABSENT · effective: [True] · origin: human

```
Original attachment record: the clinical summary was absent.
```

Request/patient/service: REF-CORRECTION / SYN-CF-CORRECTION / careflow-demo:specialty-consult

Amends: None

Source: doc-40ee7175e8d1617f · locator: doc-40ee7175e8d1617f:L001 · hash: b1c95df199f2b264a31d034c3755cd86b479f0bd824e5373160d9f7c94bbd7a1

Unicode offsets: [0, 60) · method: unicode_line_anchor

```
Original attachment record: the clinical summary was absent.
```


### fact-4d00e9180b9b6143 — clinical_summary — ORIGINAL

Assertion: ASSERTED_PRESENT · effective: [True] · origin: structured_mapping

```
Authenticated amendment: a request-specific summary is now attached.
```

Request/patient/service: REF-CORRECTION / SYN-CF-CORRECTION / careflow-demo:specialty-consult

Amends: fact-40ee7175e8d1617f

Source: doc-4d00e9180b9b6143 · locator: /sources/6/content/statement · hash: 8a6ae59de8db9f571211120117fdaa75fff9552a7b5cf08cb883b7e663082918

Unicode offsets: [None, None) · method: input_json_pointer

```
Authenticated amendment: a request-specific summary is now attached.
```


Source: doc-4d00e9180b9b6143 · locator: /sources/6/content/amendment_authority_confirmed · hash: 8a6ae59de8db9f571211120117fdaa75fff9552a7b5cf08cb883b7e663082918

Unicode offsets: [None, None) · method: input_json_pointer

```
true
```


## Unresolved conflicts and source relationships

```json
[]
```

```json
{
  "version": "claims-review-relationships/1",
  "relationships": [
    {
      "relationship": {
        "relationship_id": "816fdca1826ffda2e8066482",
        "patient_id": "SYN-CF-CORRECTION",
        "source_id": "fact-4d00e9180b9b6143",
        "target_source_id": "fact-40ee7175e8d1617f",
        "event_link_id": "REF-CORRECTION:clinical_summary",
        "relation": "amends",
        "field": "content/value",
        "replacement": true,
        "authenticated": true,
        "authority_scope": "content/value",
        "citations": [
          {
            "patient_id": "SYN-CF-CORRECTION",
            "source_id": "fact-4d00e9180b9b6143",
            "source_sha256": "41900e9a54880129703d81d403bf4098fa016a9d49923ce986b39d9f3e54789a",
            "method": "input_json_pointer",
            "locator": "/facts/6/content",
            "quote": null,
            "start": null,
            "end": null,
            "raw_value": {
              "value": true,
              "source_relationship": {
                "relation": "amends",
                "target_source_id": "fact-40ee7175e8d1617f",
                "field": "content/value",
                "replacement": true,
                "authenticated": true,
                "authority_scope": "content/value"
              }
            },
            "original_locator": {
              "careflow_fact_id": "fact-4d00e9180b9b6143",
              "citations": [
                {
                  "patient_id": "SYN-CF-CORRECTION",
                  "source_id": "doc-4d00e9180b9b6143",
                  "source_sha256": "8a6ae59de8db9f571211120117fdaa75fff9552a7b5cf08cb883b7e663082918",
                  "method": "input_json_pointer",
                  "locator": "/sources/6/content/statement",
                  "quote": null,
                  "start": null,
                  "end": null,
                  "raw_value": "Authenticated amendment: a request-specific summary is now attached.",
                  "original_locator": null
                },
                {
                  "patient_id": "SYN-CF-CORRECTION",
                  "source_id": "doc-4d00e9180b9b6143",
                  "source_sha256": "8a6ae59de8db9f571211120117fdaa75fff9552a7b5cf08cb883b7e663082918",
                  "method": "input_json_pointer",
                  "locator": "/sources/6/content/amendment_authority_confirmed",
                  "quote": null,
                  "start": null,
                  "end": null,
                  "raw_value": true,
                  "original_locator": null
                }
              ]
            }
          },
          {
            "patient_id": "SYN-CF-CORRECTION",
            "source_id": "fact-4d00e9180b9b6143",
            "source_sha256": "41900e9a54880129703d81d403bf4098fa016a9d49923ce986b39d9f3e54789a",
            "method": "input_json_pointer",
            "locator": "/facts/6/event_link_id",
            "quote": null,
            "start": null,
            "end": null,
            "raw_value": "REF-CORRECTION:clinical_summary",
            "original_locator": {
              "careflow_fact_id": "fact-4d00e9180b9b6143",
              "citations": [
                {
                  "patient_id": "SYN-CF-CORRECTION",
                  "source_id": "doc-4d00e9180b9b6143",
                  "source_sha256": "8a6ae59de8db9f571211120117fdaa75fff9552a7b5cf08cb883b7e663082918",
                  "method": "input_json_pointer",
                  "locator": "/sources/6/content/statement",
                  "quote": null,
                  "start": null,
                  "end": null,
                  "raw_value": "Authenticated amendment: a request-specific summary is now attached.",
                  "original_locator": null
                },
                {
                  "patient_id": "SYN-CF-CORRECTION",
                  "source_id": "doc-4d00e9180b9b6143",
                  "source_sha256": "8a6ae59de8db9f571211120117fdaa75fff9552a7b5cf08cb883b7e663082918",
                  "method": "input_json_pointer",
                  "locator": "/sources/6/content/amendment_authority_confirmed",
                  "quote": null,
                  "start": null,
                  "end": null,
                  "raw_value": true,
                  "original_locator": null
                }
              ]
            }
          }
        ]
      },
      "status": "VALID",
      "reasons": []
    }
  ],
  "derived": {
    "fact-b8ca69991b7abf48": {
      "content/value": {
        "values": [
          true
        ],
        "status": "ORIGINAL",
        "source_ids": [
          "fact-b8ca69991b7abf48"
        ]
      },
      "event_date": {
        "values": [
          null
        ],
        "status": "ORIGINAL",
        "source_ids": [
          "fact-b8ca69991b7abf48"
        ]
      }
    },
    "fact-007717ef15f82a64": {
      "content/value": {
        "values": [
          true
        ],
        "status": "ORIGINAL",
        "source_ids": [
          "fact-007717ef15f82a64"
        ]
      },
      "event_date": {
        "values": [
          null
        ],
        "status": "ORIGINAL",
        "source_ids": [
          "fact-007717ef15f82a64"
        ]
      }
    },
    "fact-649af0caf46f5e65": {
      "content/value": {
        "values": [
          false
        ],
        "status": "ORIGINAL",
        "source_ids": [
          "fact-649af0caf46f5e65"
        ]
      },
      "event_date": {
        "values": [
          null
        ],
        "status": "ORIGINAL",
        "source_ids": [
          "fact-649af0caf46f5e65"
        ]
      }
    },
    "fact-36b37fcd19ff534a": {
      "content/value": {
        "values": [
          false
        ],
        "status": "ORIGINAL",
        "source_ids": [
          "fact-36b37fcd19ff534a"
        ]
      },
      "event_date": {
        "values": [
          null
        ],
        "status": "ORIGINAL",
        "source_ids": [
          "fact-36b37fcd19ff534a"
        ]
      }
    },
    "fact-086a9af79f3b4699": {
      "content/value": {
        "values": [
          true
        ],
        "status": "ORIGINAL",
        "source_ids": [
          "fact-086a9af79f3b4699"
        ]
      },
      "event_date": {
        "values": [
          null
        ],
        "status": "ORIGINAL",
        "source_ids": [
          "fact-086a9af79f3b4699"
        ]
      }
    },
    "fact-40ee7175e8d1617f": {
      "content/value": {
        "values": [
          true
        ],
        "status": "AMENDED",
        "source_ids": [
          "fact-40ee7175e8d1617f",
          "fact-4d00e9180b9b6143"
        ]
      },
      "event_date": {
        "values": [
          null
        ],
        "status": "ORIGINAL",
        "source_ids": [
          "fact-40ee7175e8d1617f"
        ]
      }
    },
    "fact-4d00e9180b9b6143": {
      "content/value": {
        "values": [
          true
        ],
        "status": "ORIGINAL",
        "source_ids": [
          "fact-4d00e9180b9b6143"
        ]
      },
      "event_date": {
        "values": [
          null
        ],
        "status": "ORIGINAL",
        "source_ids": [
          "fact-4d00e9180b9b6143"
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
  "recommended": true,
  "reasons": [
    "fact_correction_present"
  ],
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
  "case_id": "CF-CORRECTION-001",
  "event_type": "REVIEW_RECORDED",
  "payload": {
    "basis_packet_sha256": "497928091def998505ffb1f1b9516567d2d969747dcc3e06be2802fe35f84cf3",
    "basis_revision": 1,
    "fact_ids": [
      "fact-40ee7175e8d1617f"
    ],
    "judgment": "PROPOSE_CORRECTION",
    "model": "scripted-offline-fixture",
    "model_version": "1",
    "proposed_actions": [
      "Recompute the deterministic documentation checks from the new evidence."
    ],
    "reason": "Constructed demo opinion: independent corrective evidence explicitly amends the absent attachment assertion.",
    "reviewer_id": "constructed-ai-review-fixture",
    "reviewer_type": "advanced_ai"
  },
  "previous_sha256": "11d8ffe63e0471626fed1c80f747ee0511890657af9beb1d4661729cec6c3cbe",
  "sequence": 2,
  "timestamp": "2026-10-13T09:53:59.595033+00:00",
  "event_sha256": "d7f7e5ae196a34c9ee1f79f84a405576c676c98a262bc3dbe96163385b694437"
}
```

## Preserved original documents

```json
[
  {
    "source_id": "doc-b8ca69991b7abf48",
    "availability_scope_issue": null,
    "referenced_by_fact_ids": [
      "fact-b8ca69991b7abf48"
    ]
  },
  {
    "source_id": "doc-007717ef15f82a64",
    "availability_scope_issue": null,
    "referenced_by_fact_ids": [
      "fact-007717ef15f82a64"
    ]
  },
  {
    "source_id": "doc-649af0caf46f5e65",
    "availability_scope_issue": null,
    "referenced_by_fact_ids": [
      "fact-649af0caf46f5e65"
    ]
  },
  {
    "source_id": "doc-36b37fcd19ff534a",
    "availability_scope_issue": null,
    "referenced_by_fact_ids": [
      "fact-36b37fcd19ff534a"
    ]
  },
  {
    "source_id": "doc-086a9af79f3b4699",
    "availability_scope_issue": null,
    "referenced_by_fact_ids": [
      "fact-086a9af79f3b4699"
    ]
  },
  {
    "source_id": "doc-40ee7175e8d1617f",
    "availability_scope_issue": null,
    "referenced_by_fact_ids": [
      "fact-40ee7175e8d1617f"
    ]
  },
  {
    "source_id": "doc-4d00e9180b9b6143",
    "availability_scope_issue": null,
    "referenced_by_fact_ids": [
      "fact-4d00e9180b9b6143"
    ]
  }
]
```

### doc-b8ca69991b7abf48

```json
{
  "source_id": "doc-b8ca69991b7abf48",
  "patient_id": "SYN-CF-CORRECTION",
  "encounter_id": "ENC-A",
  "available_at": "2026-10-10",
  "origin": "constructed_synthetic",
  "source_kind": "synthetic_note",
  "recorded_at": "2026-10-09",
  "event_date": "2026-10-09",
  "record_type": "note",
  "event_link_id": null,
  "content": "Provider requests specialty consultation for REF-CORRECTION.",
  "availability_basis": "explicit_case_metadata",
  "original_locator": null
}
```

### doc-007717ef15f82a64

```json
{
  "source_id": "doc-007717ef15f82a64",
  "patient_id": "SYN-CF-CORRECTION",
  "encounter_id": "ENC-A",
  "available_at": "2026-10-10",
  "origin": "constructed_synthetic",
  "source_kind": "synthetic_note",
  "recorded_at": "2026-10-09",
  "event_date": "2026-10-09",
  "record_type": "note",
  "event_link_id": null,
  "content": "Reason for REF-CORRECTION: persistent symptoms requiring specialist evaluation.",
  "availability_basis": "explicit_case_metadata",
  "original_locator": null
}
```

### doc-649af0caf46f5e65

```json
{
  "source_id": "doc-649af0caf46f5e65",
  "patient_id": "SYN-CF-CORRECTION",
  "encounter_id": "ENC-A",
  "available_at": "2026-10-10",
  "origin": "constructed_synthetic",
  "source_kind": "synthetic_note",
  "recorded_at": "2026-10-09",
  "event_date": "2026-10-09",
  "record_type": "note",
  "event_link_id": null,
  "content": "No investigation result is required for REF-CORRECTION in this constructed request.",
  "availability_basis": "explicit_case_metadata",
  "original_locator": null
}
```

### doc-36b37fcd19ff534a

```json
{
  "source_id": "doc-36b37fcd19ff534a",
  "patient_id": "SYN-CF-CORRECTION",
  "encounter_id": "ENC-A",
  "available_at": "2026-10-10",
  "origin": "constructed_synthetic",
  "source_kind": "synthetic_note",
  "recorded_at": "2026-10-09",
  "event_date": "2026-10-09",
  "record_type": "note",
  "event_link_id": null,
  "content": "Prior therapy documentation is not required for REF-CORRECTION.",
  "availability_basis": "explicit_case_metadata",
  "original_locator": null
}
```

### doc-086a9af79f3b4699

```json
{
  "source_id": "doc-086a9af79f3b4699",
  "patient_id": "SYN-CF-CORRECTION",
  "encounter_id": "ENC-A",
  "available_at": "2026-10-10",
  "origin": "constructed_synthetic",
  "source_kind": "synthetic_note",
  "recorded_at": "2026-10-09",
  "event_date": "2026-10-09",
  "record_type": "note",
  "event_link_id": null,
  "content": "Destination for REF-CORRECTION: specialty clinic.",
  "availability_basis": "explicit_case_metadata",
  "original_locator": null
}
```

### doc-40ee7175e8d1617f

```json
{
  "source_id": "doc-40ee7175e8d1617f",
  "patient_id": "SYN-CF-CORRECTION",
  "encounter_id": "ENC-A",
  "available_at": "2026-10-10",
  "origin": "constructed_synthetic",
  "source_kind": "synthetic_note",
  "recorded_at": "2026-10-09",
  "event_date": "2026-10-09",
  "record_type": "note",
  "event_link_id": null,
  "content": "Original attachment record: the clinical summary was absent.",
  "availability_basis": "explicit_case_metadata",
  "original_locator": null
}
```

### doc-4d00e9180b9b6143

```json
{
  "source_id": "doc-4d00e9180b9b6143",
  "patient_id": "SYN-CF-CORRECTION",
  "encounter_id": "ENC-A",
  "available_at": "2026-10-10",
  "origin": "constructed_synthetic",
  "source_kind": "structured_record",
  "recorded_at": "2026-10-09",
  "event_date": "2026-10-09",
  "record_type": "order",
  "event_link_id": null,
  "content": {
    "statement": "Authenticated amendment: a request-specific summary is now attached.",
    "documented": true,
    "amendment_authority_confirmed": true,
    "amends_fact_id": "fact-40ee7175e8d1617f",
    "amendment_scope": "assertion"
  },
  "availability_basis": "explicit_case_metadata",
  "original_locator": null
}
```

