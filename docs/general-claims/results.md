# Original-claim evidence engine: measured results

Implemented and measured on October 10, 2026. The frozen implementation is commit `32c0c5b`, on `feature/general-claim-evidence`, based on `8fcb665` (the structural-only note validator fix). No model calls or new Luna experiments were run. Prompt B, the structural validator, and the specialized HbA1c module are byte-identical to the baseline; historical artifacts and completed evaluations were not edited. [Protection hashes and measurements](results.json).

## Coverage and review readiness

| Question | Measured answer |
|---|---:|
| Original claim records found and accounted for exactly once | **9,421** |
| Distinct claim-bearing patients | **108** |
| Claims linked to original patients | **9,421** |
| Claims linked to same-patient original encounters | **9,421** |
| Claims containing original charge items | **9,421** |
| Claims with uniquely identifiable service items | **9,420** |
| Claims with supporting uniquely matched clinical service records | **9,420** |
| Original charge items | **26,854** |
| Uniquely matched charge items | **26,853** |
| Ambiguous charge items / affected claims | **1 / 1** |
| Unresolved charge items | **0** |
| Claims with diagnosis, date, or service-linkage issues | **3,130** |
| Claims without those recorded linkage issues | **6,291** |
| Claims with missing or ambiguous information, including absent documents | **9,421** |
| Claim processing failures | **0** |
| Native claims with policy evaluation | **0** |
| Native claims marked `POLICY_NOT_EVALUATED` | **9,421** |
| Offline regressions passed / failed | **465 / 0** |

Unique service linkage is a composite source match, **not** an original clinical-event foreign key or independently verified billing decision. “Supporting” here means the matching structured service row, not medical necessity. Every packet still lacks standalone clinical notes, separate orders, established provider intent, original EHR availability times, and independent coverage labels. The engine does not approve, deny, or recommend payment.

The ambiguous claim is [`35f80d0e-eaad-ef68-be2b-007c53365eb2`](packets/ambiguous_medication.json), original `claims.csv:6148`. Its charge transaction `6df464ea-f2d7-ca1d-8dc6-99ad6a9afd45`, `claims_transactions.csv:56990`, contains RxNorm `314076` (lisinopril 10 MG Oral Tablet). Two medication rows, `medications.csv:2136` and `medications.csv:2137`, share its patient, encounter, code and start timestamp. The transaction's printed TODATE is `1970-01-01T00:00:00Z`; neither medication STOP resolves the match. Both candidates remain separate and ambiguous. This is not a processing failure.

Diagnosis context could not be confirmed under the declared original-code/active-interval join for **2,957 claims** (3,137 diagnosis-field occurrences). **267 claims** have medication STOP/TODATE discrepancies. These sets overlap; together with the ambiguous item they affect 3,130 claims. Co-timed observations are included for 1,904 claims as explicitly unresolved service association, never as proof of a billed service. These are retrieval boundaries and source discrepancies, not invented clinical requirements.

## Actual service categories and patient partitions

Categories follow original clinical tables, with imaging identified through associated original imaging metadata. Procedure includes the archive's procedures, assessments, tests and therapies; no unsupported laboratory subtype or billing crosswalk is invented.

| Charge-item category | Full archive | Development | Holdout | Reserve |
|---|---:|---:|---:|---:|
| Encounter | 5,571 | 2,342 | 2,496 | 733 |
| Procedure | 15,482 | 6,499 | 6,758 | 2,225 |
| Imaging | 402 | 177 | 172 | 53 |
| Medication | 3,850 | 1,243 | 1,359 | 1,248 |
| Immunization | 1,549 | 684 | 726 | 139 |
| **Total charge items** | **26,854** | **10,945** | **11,511** | **4,398** |
| **Distinct patients** | **108** | **50** | **50** | **8** |
| **Original claims** | **9,421** | **3,585** | **3,855** | **1,981** |

The 50/50 split succeeded. Seed `20261010` selected patients using original identity alone; no service balancing or outcomes were used. The [immutable split](split.json) and [digest](split.sha256) were frozen before development/debugging. Clinical records follow their patient's partition; there is no development/holdout patient overlap. Holdout verification ran **once** after the implementation was committed, passed for all 3,855 claims, and did not drive tuning. [Final verification](holdout-verification.json), [attempt receipt](split.holdout-receipt.json).

Devices (524 rows), supplies (2,225), careplans (349), allergies (105), and other tables exist, but no original charge items are identifiable as device or supply services in this archive. Those categories were not fabricated. Claim category counts are nonexclusive: 5,571 encounter-bearing claims, 3,955 procedure-bearing claims, 368 imaging-bearing claims, 3,850 medication-bearing claims, and 1,072 immunization-bearing claims. Full development/holdout distributions are retained in [batch summary](batch-summary.json).

## Inventory and source limitations

The original ZIP is **5,960,866 bytes**, SHA-256 `d61417b551e5b0997c33851b339c157421751f0ea68c18ea686ceb1850907c35`, matching the existing pinned archive. Verified source counts: 108 patients, 9,421 claims, 85,047 transactions, 5,571 encounters, 68,648 observations, 15,884 procedures, 3,517 conditions, and 3,850 medications. [Compact inventory with every table's actual columns, populated fields, systems and relationships](inventory.json); [one-row-per-original-claim ledger](claim-index.csv).

There are **474 distinct original charge service codes**. Charge systems established from corresponding clinical tables are SNOMED CT (21,455 items), RxNorm (3,850), and CVX (1,549). Conditions and procedures print SNOMED CT URIs. Observation terminology is documented as LOINC, separate from charge codes. No CPT/HCPCS crosswalk is available. Imaging records separately preserve procedure, anatomy, modality, SOP and series/instance identifiers.

Available explicit relationships include `claims.PATIENTID → patients.Id`, `claims.APPOINTMENTID → encounters.Id`, `transactions.CLAIMID → claims.Id`, and clinical `PATIENT`/`ENCOUNTER` keys, with patient checks. Diagnosis reference fields select the header's original DIAGNOSIS1–8 ordinal. Transaction systems and clinical-event IDs are absent. Exact code and timestamps narrow service candidates without combining events. [CSV documentation](https://github.com/synthetichealth/synthea/wiki/CSV-File-Data-Dictionary).

Financial fields and payment/transfer rows are preserved as simulated source data. There are 26,854 CHARGE, 32,327 PAYMENT, 12,933 TRANSFEROUT and 12,933 TRANSFERIN rows, with zero orphan claim references. CHARGEID does not consistently repeat across the financial lifecycle; the engine does not guess payment-to-charge links. Printed transfer references are checked explicitly. Transaction NOTES contains service display labels; LINENOTE is empty throughout. [Exporter reference](https://github.com/synthetichealth/synthea/blob/master/src/main/java/org/mitre/synthea/export/CSVExporter.java). The archive's exact generator revision is unavailable, and these current references do not authenticate its generator version.

The existing HbA1c monitoring policy module remains implemented for its specialized request contract. There is no native-claim policy adapter or verified monitoring-purpose mapping. No original charge or procedure uses its HbA1c procedure code `43396009`; encountering an HbA1c LOINC observation cannot activate that policy. All native service categories therefore return `POLICY_NOT_EVALUATED`.

## Verification and throughput

The independent verifier reparsed original CSV bytes, checking **190,051 distinct referenced source rows** and **4,008,071 original field values** across development, holdout and reserve. All 9,421 packet identities and 26,854 charge items were accounted for. Cross-patient evidence contamination and unsupported billing mappings were both zero. [Development](development-verification.json), [holdout](holdout-verification.json), [reserve](reserve-verification.json).

All **465 offline regressions** passed in 4.54 seconds, including 17 new edge regressions and the unchanged HbA1c/structural-validator tests. Tests cover duplicate identities/candidates, separate items/transactions/events, missing codes/dates, patient isolation, diagnosis ordinals, provenance, immutable splits/output, original-byte verification, and the one-attempt holdout receipt. No fixture is used as the main coverage benchmark.

Indexing the full original archive took **2.91 seconds**. Claim packet construction and ledger generation took **2.34 seconds**, approximately **4,026 claims/second** on this local run. That timer excludes index construction, compressed source-store writing, and final verification; it is not end-to-end or production throughput. Compressed packets occupy 3.74 MB and the deduplicated source store 20.05 MB. [Original batch output digests](batch-output-manifest.json). Full local output: `artifacts/general-claims/full-frozen`; regenerate it with the [documented CLI](workflow.md).

## Inspected original claim examples

These six expanded packets were inspected after final processing. All examples use development patients and preserve complete original field/row provenance. They are descriptive examples, not additional evaluation scenarios.

| Example | Original claim ID | Traceable service source |
|---|---|---|
| [Encounter](packets/encounter.json) | `9a3814bb-f5b0-05f3-7b7b-f299158d98d5` | `encounters.csv:73`, SNOMED `185347001` |
| [Procedure](packets/procedure.json) | `9a3814bb-f5b0-05f3-a052-d2bb87b391e1` | `procedures.csv:256`, SNOMED `430193006` |
| [Imaging](packets/imaging.json) | `9a3814bb-f5b0-05f3-1499-6d6acc6dae3c` | `procedures.csv:296` + `imaging_studies.csv:5`, SNOMED `241046008` |
| [Medication/date discrepancy](packets/medication.json) | `9a3814bb-f5b0-05f3-0f10-810b30a6c86e` | `medications.csv:11`, RxNorm `1014676` |
| [Immunization](packets/immunization.json) | `9a3814bb-f5b0-05f3-db8e-11e83efa1402` | `immunizations.csv:23`, CVX `49` |
| [Ambiguous medication](packets/ambiguous_medication.json) | `35f80d0e-eaad-ef68-be2b-007c53365eb2` | `medications.csv:2136` and `:2137`, RxNorm `314076` |

There are no failed claim IDs to list: the processing failure list is empty. No medical accuracy, approval accuracy, or policy compliance score is reported because independent reference labels are absent.
