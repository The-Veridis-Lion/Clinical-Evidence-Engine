# Source-to-criterion verification, 2026-10-09

non-independent source review only. Registry remains `draft_ai_reviewed`;
`human_review_completed=false`, `clinical_expert_review_completed=false`.
No registry semantics or executable policy rules were changed in this phase.

| Criterion / boundary | Official section | Interpretation used | Date boundary and unresolved scope |
|---|---|---|---|
| MONITORING_CONTEXT | [NCD 190.21](https://www.cms.gov/medicare-coverage-database/view/ncd.aspx?NCDid=100), Indications and Limitations of Coverage > Indications | Diabetes management is one supported clinical context. The prototype narrows its task to monitoring established diabetes; a result alone does not establish purpose. | Narrative version 1: effective 2002-11-25, implementation 2003-01-01. Other indications, code files, eligibility and local policy are not implemented. |
| TEST_TIMELINE | Same NCD, Description frequency discussion and Limitations | Dated prior results inform frequency context; controlled and uncontrolled disease require different clinical interpretation. | Date arithmetic adds three calendar months and clamps month-end. This engineering convention is not the full CMS rule or an annual utilization adjudicator. |
| SHORT_INTERVAL_RATIONALE | Same NCD, Description paragraph on more frequent assessment; Limitations documentation discussion | An implemented regimen change or altered control can motivate closer monitoring. A prescription alone does not establish implementation. | Missing history cannot prove a false trigger. Broader medical-necessity judgments, special populations and historical code applicability remain unresolved. |
| ORDER_INTENT | [MLN909221, May 2026](https://www.cms.gov/files/document/mln909221-complying-documentation-requirements-lab-services.pdf), PDF page 2 order alternatives; page 3 documented intent | A specific signed order or applicable authenticated clinical documentation can support intent. A separate signed order is not universally required; missing paperwork is not cancellation. | Publication month is educational guidance version, not an enactment or service date. Provider qualifications and full documentation compliance are not certified. |
| Separate screening pathway | [CR 13487 / Transmittal 12694](https://www.cms.gov/files/document/r12694cp.pdf), PDF page 4, B. Policy; revised Chapter 18, section 90.1 | HbA1c screening follows a separate pathway. Screening is outside this monitoring prototype, not automatically denied. | Published 2024-06-21; effective for service dates from 2024-01-01; implementation 2024-10-07. Screening eligibility/frequency/billing rules are not executed. |

Policy references are scoped evidence pointers, not complete policy verification.
Registry locator strings are descriptive headings; the table maps them to inspectable
official sections. Generic MCD page warnings do not establish that quarterly code
files have been reviewed. Those files and complete historical applicability are
**NOT VERIFIED**. SUPPORTED applies only to the named evidence criterion. Neither
all-four support nor an insufficient packet produces approval, denial or payment.
