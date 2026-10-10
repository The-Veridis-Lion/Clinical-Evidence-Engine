# HbA1c evidence review: RAW-HBA1C-001

**NEEDS_HUMAN_REVIEW**
Evidence review only; no approval, denial, payment, or medical-necessity adjudication.

Patient: 7af6b271-f16d-21e1-882a-7bff71005a7b; constructed request: 2026-10-05.
As of: 2026-10-09; history: 2000-01-01 to 2026-10-05; completeness: not_asserted.

## Four evidence criteria

### MONITORING_CONTEXT: INSUFFICIENT_EVIDENCE
The request/result alone cannot establish monitoring purpose or current relevant background.
- Policy: [CMS_NCD_190_21_V1](https://www.cms.gov/medicare-coverage-database/view/ncd.aspx?NCDid=100), 1; Indications and Limitations of Coverage > Indications.
- Gap: Target purpose or relevant current background is missing/ambiguous.

### TEST_TIMELINE: INSUFFICIENT_EVIDENCE
The actual target, event identity, dates or declared comparison coverage are incomplete.
- Clinical: SYNTHEA-OBSERVATIONS-8765; observations.csv data row 8765; /sources/0/event_date: "2017-02-14"
- Clinical: SYNTHEA-OBSERVATIONS-8812; observations.csv data row 8812; /sources/1/event_date: "2017-06-13"
- Clinical: SYNTHEA-OBSERVATIONS-8868; observations.csv data row 8868; /sources/2/event_date: "2018-02-20"
- Clinical: SYNTHEA-OBSERVATIONS-8924; observations.csv data row 8924; /sources/3/event_date: "2018-11-20"
- 15 additional source references retained in the full JSON.
- Policy: [CMS_NCD_190_21_V1](https://www.cms.gov/medicare-coverage-database/view/ncd.aspx?NCDid=100), 1; Description and Limitations: frequency discussion.
- Gap: Actual target event or complete, unambiguous history scope is not established.

### SHORT_INTERVAL_RATIONALE: INSUFFICIENT_EVIDENCE
Unavailable dates/history do not establish a false trigger.
- Clinical: SYNTHEA-OBSERVATIONS-8765; observations.csv data row 8765; /sources/0/event_date: "2017-02-14"
- Clinical: SYNTHEA-OBSERVATIONS-8812; observations.csv data row 8812; /sources/1/event_date: "2017-06-13"
- Clinical: SYNTHEA-OBSERVATIONS-8868; observations.csv data row 8868; /sources/2/event_date: "2018-02-20"
- Clinical: SYNTHEA-OBSERVATIONS-8924; observations.csv data row 8924; /sources/3/event_date: "2018-11-20"
- 15 additional source references retained in the full JSON.
- Policy: [CMS_NCD_190_21_V1](https://www.cms.gov/medicare-coverage-database/view/ncd.aspx?NCDid=100), 1; Description: more frequent assessment paragraph; Limitations: controlled/uncontrolled diabetes and supporting documentation.
- Gap: Interval applicability remains unknown.

### ORDER_INTENT: INSUFFICIENT_EVIDENCE
Target-specific provider intent and applicable authentication are not established.
- Policy: [CMS_MLN909221_2026_05](https://www.cms.gov/files/document/mln909221-complying-documentation-requirements-lab-services.pdf), 2026-05; PDF page 2: order documentation alternatives; page 3: documented intent.
- Gap: A result, generic request or unsupported unsigned order is insufficient.

## Actual result records (not independently proved event counts)
| Source | Date | Original value |
|---|---|---|
| SYNTHEA-OBSERVATIONS-8765 | 2017-02-14 | 5.9 |
| SYNTHEA-OBSERVATIONS-8812 | 2017-06-13 | 5.7 |
| SYNTHEA-OBSERVATIONS-8868 | 2018-02-20 | 5.3 |
| SYNTHEA-OBSERVATIONS-8924 | 2018-11-20 | 5.4 |
| SYNTHEA-OBSERVATIONS-8972 | 2019-02-26 | 5.5 |
| SYNTHEA-OBSERVATIONS-9027 | 2020-03-03 | 5.7 |
| SYNTHEA-OBSERVATIONS-9084 | 2021-03-09 | 5.9 |
| SYNTHEA-OBSERVATIONS-9151 | 2022-01-11 | 6.0 |
| SYNTHEA-OBSERVATIONS-9201 | 2022-01-18 | 6.0 |
| SYNTHEA-OBSERVATIONS-9202 | 2022-01-25 | 6.0 |
| SYNTHEA-OBSERVATIONS-9249 | 2022-02-01 | 6.0 |
| SYNTHEA-OBSERVATIONS-9251 | 2022-02-22 | 5.9 |
| SYNTHEA-OBSERVATIONS-9297 | 2022-03-01 | 5.9 |
| SYNTHEA-OBSERVATIONS-9298 | 2022-03-22 | 5.9 |
| SYNTHEA-OBSERVATIONS-9363 | 2023-03-28 | 5.3 |
| SYNTHEA-OBSERVATIONS-9452 | 2023-05-13 | 5.3 |
| SYNTHEA-OBSERVATIONS-9941 | 2024-04-02 | 5.5 |
| SYNTHEA-OBSERVATIONS-10003 | 2025-04-08 | 5.7 |
| SYNTHEA-OBSERVATIONS-10058 | 2026-04-14 | 5.9 |

## Missing information and execution
- Actual target date/performance is not established by the constructed request.
- Target monitoring purpose is missing, ambiguous or conflicted.
- History completeness is not asserted; missing retrieved history cannot prove an absence of tests.
- Note extraction: not_run; real calls: 0; application cache: disabled.
- Execution failure: False; human/clinical review: false.
- Policy: 0.1.0-draft-ai-20261008; rules: claims-review-rules/2.
- Full JSON retains raw fields, offsets, all source references, conflicts and execution provenance.
