# CareFlow Evidence Review Packet — CF-REF-001

**DOCUMENTATION_READY** · revision 2 · as of 2026-10-13

Request: REF-A · type: referral · patient: SYN-CF-A · encounter: ENC-A

Service: careflow-demo / specialty-consult · requested date: 2026-11-01

Rules: careflow-referral / 1.0.0 · synthetic_project_checklist

Packet SHA-256: a857f09a5c8b5dd0af1acfd8963a7885f6ce3efdff69a2d7ff31aec03db1d3b5
Rules SHA-256: ed68d9f0d7f48a59db27065a644ac39a55c7c4a360c1bb905663e64056f246c8

Documentation readiness only; no medical approval, payment eligibility or compliance certification.

Exact provenance validates location, not clinical interpretation or signature authenticity. Supplied assertions require independent human or advanced-AI review when warranted.

## Documentation checks

| Rule / version | Requirement | Trigger | Result | Fact IDs |
| --- | --- | --- | --- | --- |
| CF-DOC-001 / 1.0.0 | request_intent | always; value=True | SUPPORTED | fact-2d3da32fe73ce8ef |
| CF-DOC-002 / 1.0.0 | referral_reason | always; value=True | SUPPORTED | fact-58f71a57f8ac3a99 |
| CF-DOC-003 / 1.0.0 | clinical_summary | always; value=True | SUPPORTED | fact-edb63b6f97cd5ecc |
| CF-DOC-004 / 1.0.0 | investigation_result | investigation_required == true; value=False | NOT_APPLICABLE | fact-0c7152a778a03a35 |
| CF-DOC-005 / 1.0.0 | therapy_completed | therapy_required == true; value=False | NOT_APPLICABLE | fact-f53ddd3b2dfb4ad1 |
| CF-REF-001 / 1.0.0 | destination | always; value=True | SUPPORTED | fact-28b5ad56f92d1923 |

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

### fact-2d3da32fe73ce8ef — request_intent — ORIGINAL

Assertion: ASSERTED_PRESENT · effective: [True] · origin: human

```
Provider requests specialty consultation for REF-A.
```

Request/patient/service: REF-A / SYN-CF-A / careflow-demo:specialty-consult

Amends: None

Source: doc-2d3da32fe73ce8ef · locator: doc-2d3da32fe73ce8ef:L001 · hash: f173d9de604b57ab953bf24fd5b75ecc31874cfac65891369e1acedf63d1219d

Unicode offsets: [0, 51) · method: unicode_line_anchor

```
Provider requests specialty consultation for REF-A.
```


### fact-58f71a57f8ac3a99 — referral_reason — ORIGINAL

Assertion: ASSERTED_PRESENT · effective: [True] · origin: human

```
Reason for REF-A: persistent symptoms requiring specialist evaluation.
```

Request/patient/service: REF-A / SYN-CF-A / careflow-demo:specialty-consult

Amends: None

Source: doc-58f71a57f8ac3a99 · locator: doc-58f71a57f8ac3a99:L001 · hash: 4ce53d554021169aa12bec3253b2fcfebdd8c278d6f39b17e683e8b5d36a22b0

Unicode offsets: [0, 70) · method: unicode_line_anchor

```
Reason for REF-A: persistent symptoms requiring specialist evaluation.
```


### fact-0c7152a778a03a35 — investigation_required — ORIGINAL

Assertion: ASSERTED_ABSENT · effective: [False] · origin: human

```
No investigation result is required for REF-A in this constructed request.
```

Request/patient/service: REF-A / SYN-CF-A / careflow-demo:specialty-consult

Amends: None

Source: doc-0c7152a778a03a35 · locator: doc-0c7152a778a03a35:L001 · hash: 420a028e07d14236b69c79618de51b7706d9d5a1939a430c7a0264c749d47c7b

Unicode offsets: [0, 74) · method: unicode_line_anchor

```
No investigation result is required for REF-A in this constructed request.
```


### fact-f53ddd3b2dfb4ad1 — therapy_required — ORIGINAL

Assertion: ASSERTED_ABSENT · effective: [False] · origin: human

```
Prior therapy documentation is not required for REF-A.
```

Request/patient/service: REF-A / SYN-CF-A / careflow-demo:specialty-consult

Amends: None

Source: doc-f53ddd3b2dfb4ad1 · locator: doc-f53ddd3b2dfb4ad1:L001 · hash: d9d33d8c8c2a15389fe1ff766c04c839fbfadb45223140744afcf2847449c5c9

Unicode offsets: [0, 54) · method: unicode_line_anchor

```
Prior therapy documentation is not required for REF-A.
```


### fact-28b5ad56f92d1923 — destination — ORIGINAL

Assertion: ASSERTED_PRESENT · effective: [True] · origin: human

```
Destination for REF-A: specialty clinic.
```

Request/patient/service: REF-A / SYN-CF-A / careflow-demo:specialty-consult

Amends: None

Source: doc-28b5ad56f92d1923 · locator: doc-28b5ad56f92d1923:L001 · hash: b0d86ff60850a5db4a1b3b9066bf9d5d276540447b94f5009024751ce04fce06

Unicode offsets: [0, 40) · method: unicode_line_anchor

```
Destination for REF-A: specialty clinic.
```


### fact-edb63b6f97cd5ecc — clinical_summary — ORIGINAL

Assertion: ASSERTED_PRESENT · effective: [True] · origin: human

```
Clinical summary for REF-A: symptoms, relevant history and examination documented.
```

Request/patient/service: REF-A / SYN-CF-A / careflow-demo:specialty-consult

Amends: None

Source: doc-edb63b6f97cd5ecc · locator: doc-edb63b6f97cd5ecc:L001 · hash: 588767c780d754ea6307ce21fbf83f3fcd280d5defe7e668bda81030edee7101

Unicode offsets: [0, 82) · method: unicode_line_anchor

```
Clinical summary for REF-A: symptoms, relevant history and examination documented.
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
    "fact-2d3da32fe73ce8ef": {
      "content/value": {
        "values": [
          true
        ],
        "status": "ORIGINAL",
        "source_ids": [
          "fact-2d3da32fe73ce8ef"
        ]
      },
      "event_date": {
        "values": [
          null
        ],
        "status": "ORIGINAL",
        "source_ids": [
          "fact-2d3da32fe73ce8ef"
        ]
      }
    },
    "fact-58f71a57f8ac3a99": {
      "content/value": {
        "values": [
          true
        ],
        "status": "ORIGINAL",
        "source_ids": [
          "fact-58f71a57f8ac3a99"
        ]
      },
      "event_date": {
        "values": [
          null
        ],
        "status": "ORIGINAL",
        "source_ids": [
          "fact-58f71a57f8ac3a99"
        ]
      }
    },
    "fact-0c7152a778a03a35": {
      "content/value": {
        "values": [
          false
        ],
        "status": "ORIGINAL",
        "source_ids": [
          "fact-0c7152a778a03a35"
        ]
      },
      "event_date": {
        "values": [
          null
        ],
        "status": "ORIGINAL",
        "source_ids": [
          "fact-0c7152a778a03a35"
        ]
      }
    },
    "fact-f53ddd3b2dfb4ad1": {
      "content/value": {
        "values": [
          false
        ],
        "status": "ORIGINAL",
        "source_ids": [
          "fact-f53ddd3b2dfb4ad1"
        ]
      },
      "event_date": {
        "values": [
          null
        ],
        "status": "ORIGINAL",
        "source_ids": [
          "fact-f53ddd3b2dfb4ad1"
        ]
      }
    },
    "fact-28b5ad56f92d1923": {
      "content/value": {
        "values": [
          true
        ],
        "status": "ORIGINAL",
        "source_ids": [
          "fact-28b5ad56f92d1923"
        ]
      },
      "event_date": {
        "values": [
          null
        ],
        "status": "ORIGINAL",
        "source_ids": [
          "fact-28b5ad56f92d1923"
        ]
      }
    },
    "fact-edb63b6f97cd5ecc": {
      "content/value": {
        "values": [
          true
        ],
        "status": "ORIGINAL",
        "source_ids": [
          "fact-edb63b6f97cd5ecc"
        ]
      },
      "event_date": {
        "values": [
          null
        ],
        "status": "ORIGINAL",
        "source_ids": [
          "fact-edb63b6f97cd5ecc"
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
  "case_id": "CF-REF-001",
  "event_type": "REVIEW_RECORDED",
  "payload": {
    "basis_packet_sha256": "e53c6aa4280a9549ef7f026f83d48d705a5451e1cdb9e36d5dfb90ef23f73159",
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
  "previous_sha256": "7df7e56b411b0814c6f07f62dc8b79ca1e72a6a001115dfabdfabb90149161a4",
  "sequence": 2,
  "timestamp": "2026-10-13T09:52:02.732838+00:00",
  "event_sha256": "2085a4c60f39b681757bfd7a276d028d7aaa22c390e7b2dc801927e256d88a6b"
}
```

## Preserved original documents

```json
[
  {
    "source_id": "doc-2d3da32fe73ce8ef",
    "availability_scope_issue": null,
    "referenced_by_fact_ids": [
      "fact-2d3da32fe73ce8ef"
    ]
  },
  {
    "source_id": "doc-58f71a57f8ac3a99",
    "availability_scope_issue": null,
    "referenced_by_fact_ids": [
      "fact-58f71a57f8ac3a99"
    ]
  },
  {
    "source_id": "doc-0c7152a778a03a35",
    "availability_scope_issue": null,
    "referenced_by_fact_ids": [
      "fact-0c7152a778a03a35"
    ]
  },
  {
    "source_id": "doc-f53ddd3b2dfb4ad1",
    "availability_scope_issue": null,
    "referenced_by_fact_ids": [
      "fact-f53ddd3b2dfb4ad1"
    ]
  },
  {
    "source_id": "doc-28b5ad56f92d1923",
    "availability_scope_issue": null,
    "referenced_by_fact_ids": [
      "fact-28b5ad56f92d1923"
    ]
  },
  {
    "source_id": "doc-edb63b6f97cd5ecc",
    "availability_scope_issue": null,
    "referenced_by_fact_ids": [
      "fact-edb63b6f97cd5ecc"
    ]
  }
]
```

### doc-2d3da32fe73ce8ef

```json
{
  "source_id": "doc-2d3da32fe73ce8ef",
  "patient_id": "SYN-CF-A",
  "encounter_id": "ENC-A",
  "available_at": "2026-10-10",
  "origin": "constructed_synthetic",
  "source_kind": "synthetic_note",
  "recorded_at": "2026-10-09",
  "event_date": "2026-10-09",
  "record_type": "note",
  "event_link_id": null,
  "content": "Provider requests specialty consultation for REF-A.",
  "availability_basis": "explicit_case_metadata",
  "original_locator": null
}
```

### doc-58f71a57f8ac3a99

```json
{
  "source_id": "doc-58f71a57f8ac3a99",
  "patient_id": "SYN-CF-A",
  "encounter_id": "ENC-A",
  "available_at": "2026-10-10",
  "origin": "constructed_synthetic",
  "source_kind": "synthetic_note",
  "recorded_at": "2026-10-09",
  "event_date": "2026-10-09",
  "record_type": "note",
  "event_link_id": null,
  "content": "Reason for REF-A: persistent symptoms requiring specialist evaluation.",
  "availability_basis": "explicit_case_metadata",
  "original_locator": null
}
```

### doc-0c7152a778a03a35

```json
{
  "source_id": "doc-0c7152a778a03a35",
  "patient_id": "SYN-CF-A",
  "encounter_id": "ENC-A",
  "available_at": "2026-10-10",
  "origin": "constructed_synthetic",
  "source_kind": "synthetic_note",
  "recorded_at": "2026-10-09",
  "event_date": "2026-10-09",
  "record_type": "note",
  "event_link_id": null,
  "content": "No investigation result is required for REF-A in this constructed request.",
  "availability_basis": "explicit_case_metadata",
  "original_locator": null
}
```

### doc-f53ddd3b2dfb4ad1

```json
{
  "source_id": "doc-f53ddd3b2dfb4ad1",
  "patient_id": "SYN-CF-A",
  "encounter_id": "ENC-A",
  "available_at": "2026-10-10",
  "origin": "constructed_synthetic",
  "source_kind": "synthetic_note",
  "recorded_at": "2026-10-09",
  "event_date": "2026-10-09",
  "record_type": "note",
  "event_link_id": null,
  "content": "Prior therapy documentation is not required for REF-A.",
  "availability_basis": "explicit_case_metadata",
  "original_locator": null
}
```

### doc-28b5ad56f92d1923

```json
{
  "source_id": "doc-28b5ad56f92d1923",
  "patient_id": "SYN-CF-A",
  "encounter_id": "ENC-A",
  "available_at": "2026-10-10",
  "origin": "constructed_synthetic",
  "source_kind": "synthetic_note",
  "recorded_at": "2026-10-09",
  "event_date": "2026-10-09",
  "record_type": "note",
  "event_link_id": null,
  "content": "Destination for REF-A: specialty clinic.",
  "availability_basis": "explicit_case_metadata",
  "original_locator": null
}
```

### doc-edb63b6f97cd5ecc

```json
{
  "source_id": "doc-edb63b6f97cd5ecc",
  "patient_id": "SYN-CF-A",
  "encounter_id": "ENC-A",
  "available_at": "2026-10-10",
  "origin": "constructed_synthetic",
  "source_kind": "synthetic_note",
  "recorded_at": "2026-10-09",
  "event_date": "2026-10-09",
  "record_type": "note",
  "event_link_id": null,
  "content": "Clinical summary for REF-A: symptoms, relevant history and examination documented.",
  "availability_basis": "explicit_case_metadata",
  "original_locator": null
}
```

