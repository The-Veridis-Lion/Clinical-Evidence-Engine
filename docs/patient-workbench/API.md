# Patient workbench contract, workbench/1

Copilot hosts `/workbench/` and the same-origin `/ui` facade. Existing `/api` and separate CareFlow `/v1` endpoints remain usable. Mutating `/ui` calls use `X-Copilot-Token` from `/api/config`; preserve local Host/Origin and body bounds. JSON UTF-8 text upload is supported; no implicit PDF/OCR support.

## Core routes

- `GET /ui/patients`: `{patients:[{patient_id,display_label}]}`.
- `POST /ui/patients`: `{patient_id,display_label}` creates explicit identity.
- `GET /ui/patients/{id}/workspace`: `{contract_version,patient,encounters,documents,extraction_jobs,active_encounter_id,evidence_version,capabilities}`.
- `POST /ui/patients/{id}/files`: `{files:[{document_id,filename,text,input_kind,encounter_id,encounter_time,source_patient_id?}]}`. `encounter_id` and date may be null; unknown membership is not a new visit. Returns durable per-file jobs. Duplicate same patient/source/kind reuses the existing document; conflicting metadata is reported, not silently rebound. At most one first extraction dispatch per new source. No automatic retries for failed/uncertain work.
- `GET /ui/patients/{id}/encounters/{encounter_id}/soap`: selected encounter only; `{sections:{S:[],O:[],A:[],P:[]},sentence_evidence_links,saved_version,evidence_version,editable,polishing_capability}`. Section rows retain existing presentation fields plus `case_id`, `document_id`, `packet_version`. A row's evidence references identify its saved packet and original offsets.
- `GET /ui/patients/{id}/evidence/{case_id}?version=N`: saved packet and full original source, after patient ownership check.
- `GET /ui/patients/{id}/query-capabilities`: finite supported query families and parameters.
- `POST /ui/patients/{id}/queries`: `{family,filters:{start?,end?,concept?,experiencer?,service_type?}}`, deterministic, zero model calls. Natural language mode uses `{question,allow_model:true,request_id}` and only produces a validated finite query spec, not an answer or code.
- Query response: `{answer,query_spec,evidence_version,computed_from,calculation_steps,excluded_records,missing_data,source_refs,model_used_for_interpretation,model_calls}`. A source ref carries `case_id,packet_version,document_id,fact_id?,start,end,quote`; a metadata-only encounter association is explicitly distinct from a clinical source span.
- `POST /ui/patients/{id}/facts/{case_id}/{fact_id}/corrections`: existing versioned review body, including base version, human reviewer, reason and replacement; typed semantics may use `kind:"semantics"`. Saves through existing review/semantics functions. Then refresh affected shared material requests or return an explicit stale/error state.
- `POST /ui/patients/{id}/soap/polish`: explicit optional call, bounded saved encounter claims only; returns a separate source-linked prose proposal and call receipt. Never updates clinical facts. Model interpretation/polish outputs and dispatch attempts use a separate durable auxiliary ledger.

The current polish contract permits grouping/reordering saved statement IDs within their original SOAP section. The server reconstructs their exact clinical sentences and checks every statement appears once; it does not accept arbitrary rewritten medical prose. Only `gpt-6-luna` is enabled for this optional operation. Clinical facts, citations and raw extraction stay unchanged.

## Query implementation boundary

`copilot.patient_queries.capabilities()` and `query_patient_packets(workspace, packets, query)` are the deterministic Python entrypoints. `packets` are current verified CaseStore packets; `workspace.documents` bind `case_id` to `document_id`, explicit `encounter_id`, `encounter_time`, and status. `workspace.encounters` contain unique IDs and explicit dates, not upload order. Query families: `visit_count`, `documented_duration_sum`, `visit_frequency`, `symptom_timeline`, `observation_history`. Reuse existing Engine computation/normalization where applicable, retain traceable exclusions, never equate duration with date span or prescribed frequency with attendance.

## CareFlow sharing

CareFlow receives a server-configured, read-only path to the Copilot database. Callers send saved case/version/hash references, never a trusted-fact toggle or a filesystem path. New `POST /v1/shared-intake` creates a request using those saved sources and supplied formal materials. `POST /v1/cases/{id}/sync-shared` creates a new revision from current referenced evidence while retaining the old source snapshot, formal materials, and audit. No Luna dispatch is permitted in either operation.

Facade routes under `/ui/patients/{id}/careflow/requests` create/list requests; `/{case_id}` reads details and `/{case_id}/{documents|recalculate|reviews|sync-shared}` forward allowed operations. The facade verifies patient ownership and forwards the locally obtained CareFlow token. Clinical evidence cannot synthesize orders/forms/payer context. Source corrections require new revisions; a failed synchronization remains visibly stale.
