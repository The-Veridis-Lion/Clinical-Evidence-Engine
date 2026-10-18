# Medical use and human responsibility

Clinical Evidence Copilot and CareFlow Readiness Engine are engineering prototypes
for evidence organization, draft documentation and checklist evaluation. Outputs
may omit facts, misinterpret negation, confuse time or attribution, or repeat errors
in the original record. A matching quotation establishes a location, not medical
truth. Source-support scores and software tests are not clinical validation.

## Before a patient-care decision

AI-generated SOAP content, answers, calculations and extracted plans are supporting
drafts or evidence summaries. They do not replace a qualified professional's
independent judgment. A qualified healthcare professional must review the original
sources, relevant patient context, uncertainties and proposed action before using
any output for diagnosis, treatment, medication, triage or another substantive
patient-care decision. An extracted medication or plan is not a prescription or
an instruction to administer treatment. An AI reviewer cannot provide this human
professional review.

The responsible professional retains responsibility for the clinical decision.
The deploying organization remains responsible for its workflow, staff access,
data handling and any required validation and regulatory assessment. A recorded
review in this prototype does not authenticate professional credentials or transfer
those responsibilities.

## CareFlow's boundary

`DOCUMENTATION_READY` means that the saved evidence satisfies a particular
versioned documentation checklist at its recorded review date. It is not a
medical-necessity determination, eligibility finding, insurance approval, coverage
guarantee or final authorization decision. Missing materials and conflicting
evidence require investigation. Even a complete checklist leaves clinical
appropriateness and payer decisions to the responsible people and organizations.

## What the software does and does not enforce

| Layer | Actual behavior or responsibility |
| --- | --- |
| License and external agreements | `LICENSE.md` governs covered original material; third-party licenses, applicable provider agreements and law have their own scope. This document adds no license condition. |
| Intended-use requirement | Professional human review before substantive patient-care decisions is the project's safety requirement for clinical use. It is documented guidance, not an executable approval gate or an amendment to PolyForm or Apache. |
| Runtime notices | The workbench identifies clinical drafts and explains CareFlow's documentation-only scope. Copilot Markdown exports and CareFlow Markdown reports carry the same boundary. Notices inform; they do not prevent copying or external use. |
| Existing technical controls | Source references and packet integrity are checked; corrections retain revisions; CareFlow records reviewer opinions separately from deterministic readiness and checks revision/hash references. These checks cannot establish clinical correctness. |
| External decision boundary | The reviewed APIs organize evidence and recalculate checklists. They contain no prescription execution, treatment-order execution, payer submission or final authorization endpoint. No authenticated clinician sign-off or downstream decision lock is implemented. |

Extraction, queries, draft generation and demonstrations remain available without
mandatory sign-off. If a deployment adds an action that affects care, it must place
an authenticated professional review and explicit confirmation at that action,
bind the review to the current evidence and proposed action, and invalidate it
when either changes. That integration is future deployment work, not an existing
safeguard certified by this repository.

## Claims and data handling

This project does not claim clinical validation, regulatory approval or clearance,
HIPAA compliance, or any other compliance certification. Public demos and synthetic
tests do not establish readiness for real-patient care. Do not present the project
or its source checks as having approvals or certifications that have not actually
been obtained. A license's warranty disclaimer does not supply regulatory permission
or eliminate responsibilities imposed by applicable law.

Use synthetic or appropriately authorized data for evaluation. Local storage does
not make a deployment compliant: explicit live model operations can send clinical
text to the configured provider. Before processing real patient data, the operator
must establish authority, appropriate access controls, retention and provider
arrangements, and the assessment required for the intended jurisdiction and use.

See [the licensing review](LICENSING_REVIEW.md) and
[third-party notices](THIRD_PARTY_NOTICES.md) for separate licensing questions.
