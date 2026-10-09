# Semantic contract v1 — scoped source statements

This contract is an AI-assisted engineering review, not human annotation or clinical expert review. It preserves source facts separately from countability; code retains responsibility for arithmetic and reconciliation.

| Field / layer | Scope and evidence | Unknown / negation |
|---|---|---|
| `ServiceClaim.source.content_kind` | The specific record's clinical, attendance, schedule, draft, billing or correction content. | Transmission is a separate axis; document-wide labels do not determine every entry. |
| `source.transmission_status` | `original`, `retransmitted`, or `unknown`, for this service record/section. | An old attachment does not mark new content retransmitted. |
| `source.original_signed` / `current_signed` | Signature of the reproduced original / this current record entry. Multiple support spans may cite header and item. | Nullable; Final register/export alone does not establish a clinical signature for each entry. |
| `source.source_disposition` | Literal appointment/roster status, retained without making it clinical authority. | Missing status is null; Completed is not actual clock evidence. |
| `patient_present` / `delivered` | This source's assertion about the patient's presence / receipt of the described patient service, for the identified appointment/encounter. Completed supports the administrative disposition unless a linked entry explicitly limits it (partner-only, absence). | Clinic cancellation describes no attendance at that cancelled slot; it does not deny an independent contact. Partial absence does not negate subsequent patient contact. Draft assertions remain source assertions, not established care. |
| IDs | Literal roles assigned by source, scoped to patient and entry. Header/table may label Encounter and prose may label Appointment for the same token. | Preserve both supported roles; no prefix guessing and no global token-only merge. |
| Assessment `source_role` | `result` for an actual form/result; `historical_mention` for a referenced old score without a newly supplied result. | Historical mentions remain retained; they do not create a new measured timeline entry or automatically bind by equal score. |
| Assessment `reference_date` | Date explicitly attached to a historical mention, including a recorded date. | It is not an assessment completion date. Completion/entry/review/receipt remain distinct. |
| Assessment `copied` | Reproduced old result or summary, rather than review of an attached original form. | Review alone does not mean copied. Missing completion dates/scores stay null. |
| Observation `statement`, `polarity`, reporter | Statement is readable source-faithful language; polarity categorizes the asserted clinical concept. No second logical negation of the sentence. Reporter is the actual attributed speaker/observer. | Unknown reporter remains `not specified`; signer is not automatically every quotation's reporter. |
| `context_span_ids` (model boundary) | Exact source spans for identity, signature, transmission, ID roles and other inherited support. Adapter retains all passages. | Existence and binding checks are necessary checks, not semantic proof. |

Deterministic projection: when the source status is retransmitted, `evidence_kind=retransmission` and `signed` uses original_signed. Otherwise evidence_kind uses content_kind and signed uses current_signed. Null signature never becomes signed true. Source metadata remains stored beside the projected fields, and raw responses remain immutable. No language fact is inferred from gold or patient-specific rules.

A remains the previous clinical_partition prompt/schema. B changes only this source contract, its aligned examples, multi-span adapter and scoped reconciliation. Historical scorer critical-fields-9 stays intact. Common comparisons use the same required source facts and separately review supported historical mentions / duplicate representations; new metadata is scored separately. Disputed scope or annotation is not silently made correct. C is considered only if a specific residual generation mechanism survives B; any check must have runtime-only triggers and finite calls.
