# Original claim workflow, contract v1

Use Python 3.12+ and the existing pinned dependencies. Install the project with `python -m pip install --no-deps -e .`, or set `PYTHONPATH=src` in a source checkout. Commands are also available as `clinical claims ...` and `python -m clinical_intelligence.claims_engine ...`. The general workflow has no live-provider option.

PowerShell examples use the original local archive; substitute its path on other machines:

```powershell
$archive = 'C:/Users/sunxi/Downloads/synthea_sample_data_csv_latest.zip'
$env:PYTHONPATH = 'src'
python -m clinical_intelligence claims inventory --archive $archive --split docs/general-claims/split.json --output artifacts/new-inventory.json
python -m clinical_intelligence claims inspect-claim --archive $archive --claim-id cc3eac4a-34a7-9a15-b0e6-038869c0c457 --output artifacts/new-original-claim.json
python -m clinical_intelligence claims packet --archive $archive --split docs/general-claims/split.json --claim-id cc3eac4a-34a7-9a15-b0e6-038869c0c457 --output artifacts/new-evidence-packet.json
python -m clinical_intelligence claims batch --archive $archive --split docs/general-claims/split.json --partition development --output artifacts/new-development-run
python -m clinical_intelligence claims batch --archive $archive --split docs/general-claims/split.json --output artifacts/new-full-run
```

Outputs use exclusive creation. Existing archives, manifests, and completed runs cannot be overwritten. To reproduce the frozen identity-only split in a **new** location:

```powershell
python -m clinical_intelligence claims split --archive $archive --seed 20261010 --output artifacts/reproduced-split.json
```

The manifest's SHA-256 sidecar is required. Selection sorts original patient IDs by SHA-256 of `seed:patient_id`. It uses no services, outcomes, or balancing. At least 100 eligible claim-bearing patients yield 50 development / 50 holdout / remainder reserve; fewer yield floor(N/2) development and the remainder holdout, explicitly reported. All original claim IDs are included in their patient's entry. Clinical rows follow `PATIENT` or `PATIENTID`; provider, organization, and payer reference tables are shared.

Development commands with `--partition development` discard other patients' records while indexing. Full-archive inventory is descriptive; the holdout must not guide implementation choices. Final verification is intended once after freezing code:

```powershell
python -m clinical_intelligence claims verify --archive $archive --split docs/general-claims/split.json --batch artifacts/new-development-run --partition development --output artifacts/new-development-check.json
python -m clinical_intelligence claims verify-holdout --archive $archive --split artifacts/reproduced-split.json --batch artifacts/new-full-run --output artifacts/new-final-holdout-check.json
```

`verify-holdout` reserves an exclusive receipt next to that split and rejects a second attempt. The committed split already has its final receipt; do not repeat or tune against its holdout. Reproductions should retain the same selection and remain separate from the completed evaluation.

## General packet and source contract

`ClaimPacket` and `ServiceItem` in `claims_engine/contracts.py` use `claim-evidence/1`. They deliberately replace the native ingestion contract rather than widening the existing constructed-request schema. Existing `claims-review-prep/0.1`, `ClaimInput`, `prepare`, retrieval, Prompt B, and HbA1c criteria remain specialized and unchanged. New callers use `claims packet` instead of supplying a constructed HbA1c request.

Each packet includes original claim/patient/encounter identity, original service timestamp, individual `CHARGE` rows, diagnoses and diagnosis ordinals, claim-level financial transaction references, explicit source links, missing data, linkage status, partition, readiness, and policy status. `inspect-claim` prints unmodified original header and transactions. `packet` also expands every referenced source, including all original field strings, native IDs where printed, CSV record numbers and physical line spans, and row/member/archive hashes. Tables without native IDs use distinct CSV row identities; imaging series and instances are never collapsed into one event.

Source keys link claims, patients, encounters, and transactions. Service candidates require the same patient, a verified encounter, the **exact original code**, and an **exact start timestamp**. STOP can disambiguate multiple candidates; differing STOP/TODATE remains an issue. This is a composite candidate match, not a clinical-event foreign key. Repeated candidates or charge items sharing a candidate stay ambiguous. Encounter, procedure, medication, immunization, device, and supply tables are indexed without a service-code whitelist. Imaging category requires associated original imaging metadata. Absent clinical matches remain `UNKNOWN` / `UNRESOLVED`.

Diagnosis and service-indication context use original codes and active date intervals. Other context is bounded to the actual encounter. Co-timed observations are labelled as context with **unresolved service association**, and cannot prove the billed item or change its code. No lab-panel/result crosswalk exists. The source's service display field is not a clinical narrative. Missing notes, separate orders, provider intent, original EHR availability, or policy labels are never generated.

`COMPOSITE_MATCH_UNIQUE` identifies one source candidate, not independent proof of billing correctness. `SOURCE_LINKED` means all items are uniquely matched and no recorded linkage issue remains. `STRUCTURED_EVIDENCE_ONLY` still requires policy/document review. `NEEDS_LINKAGE_REVIEW` retains missing/ambiguous joins or date/diagnosis discrepancies. Neither readiness state implies medical necessity, approval, denial, or payment. Every native packet currently returns `POLICY_NOT_EVALUATED`; the preserved HbA1c module has no native-claim policy adapter, and an encounter's HbA1c observation alone cannot trigger it.

## Compact batch and measurement contract

Each new batch directory contains `claim-index.csv` (one row per original claim row, including failures), `packets.jsonl.gz` (compact source references), `sources.jsonl.gz` (each referenced original row once), `summary.json`, `failures.json`, and an output digest manifest. Detailed inspection regenerates a requested packet from the indexed original archive; thousands of expanded reports are unnecessary. The ZIP is indexed once per process rather than rescanned per claim. API users can reuse `ArchiveIndex`, `build_packet`, `expanded_packet`, `inventory`, and `process` across requests.

Metrics distinguish claim/line coverage, identifiable items, supporting service records, issues, source fields/bytes, failures and throughput. Category counts are per charge item; claim category counts are nonexclusive. Missing documentary information and unresolved observation associations are separate from service identity. Verification reparses original CSV bytes independently of the ingestion index, checks saved source values and provenance, accounts for claim and transaction identities, and checks patient isolation. It does not measure clinical accuracy or full clinical relevance recall.

Source interpretation follows the [Synthea CSV data dictionary](https://github.com/synthetichealth/synthea/wiki/CSV-File-Data-Dictionary) and [CSV exporter](https://github.com/synthetichealth/synthea/blob/master/src/main/java/org/mitre/synthea/export/CSVExporter.java). The archive is hash-pinned independently; its exact generator revision is unavailable. Terminology omitted from source fields is labelled as documentation-based. Transactions have no printed code-system column, so matched source systems are recorded explicitly; no CPT/HCPCS mappings are introduced.

## Offline regression

```powershell
$env:PYTHONPATH = 'src'
New-Item -ItemType Directory -Force .work/test-temp | Out-Null
$env:TEMP = (Resolve-Path .work/test-temp).Path
$env:TMP = $env:TEMP
python -m pytest -q --basetemp=.work/new-test-run
```

Setting `PYTHONPATH` before pytest is necessary for existing subprocess CLI tests in an uninstalled checkout. Use a fresh `--basetemp` to preserve earlier runs. Small fixtures test software edge cases only; measured coverage comes from the original full archive.
