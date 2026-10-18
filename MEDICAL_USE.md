# Medical use

Clinical Evidence Copilot organizes clinical evidence and produces source-linked
SOAP drafts and answers. CareFlow Readiness Engine checks documentation against
versioned requirements. Both are prototypes for demonstration and evaluation.
Neither product is clinically validated or represented as having regulatory
approval or compliance certification.

## Professional oversight

AI-generated clinical content is a supporting draft or evidence summary. It may
omit information, misinterpret context or repeat errors in the source record.
An exact quotation identifies supporting text; it does not establish medical truth.

A qualified healthcare professional must independently review the original
sources, relevant patient context, uncertainties and proposed action before using
an output for diagnosis, treatment, medication, triage or another substantive
patient-care decision. Extracted medications and plans are records of documented
information, not prescriptions or instructions to administer treatment. An AI
review cannot substitute for professional human judgment.

The responsible professional retains responsibility for the clinical decision.
The deploying organization is responsible for its workflow, data handling and any
validation or regulatory assessment required for the intended use.

## Documentation readiness

`DOCUMENTATION_READY` means that saved evidence satisfies a particular versioned
checklist at the recorded assessment date. It is not a medical-necessity finding,
insurance approval, coverage guarantee or final authorization decision. Clinical
appropriateness and payer decisions remain with the responsible professionals and
organizations. Missing materials, conflicting evidence and outdated information
require investigation even when other checklist items are complete.

## Product safeguards and limits

The products preserve source references and revision history. CareFlow keeps
reviewer opinions separate from deterministic checklist results. These safeguards
support evidence inspection; they do not establish clinical accuracy or authenticate
a reviewer's professional credentials.

Extraction, queries, draft generation and demonstrations do not require clinical
sign-off. The products do not execute prescriptions, treatment orders, payer
submissions or final authorization decisions. Professional review before clinical
use is an intended-use requirement; the software does not enforce a clinical
sign-off gate or prevent external use of copied outputs. A deployment that connects
outputs to patient-care actions needs an appropriate professional approval workflow.

## Data and deployment

Use synthetic or appropriately authorized data for evaluation. Live model operations
can send clinical text to the configured provider. Before processing patient data,
the operator must establish the necessary authority, access controls, retention
policy and provider arrangements. Local storage and source checks alone do not
establish HIPAA compliance or suitability for real-patient care.

Do not describe the products as clinically validated, regulator-approved or
compliance-certified without evidence supporting the specific claim.

## License

Original project code and documentation are licensed under [Apache 2.0](LICENSE.md).
This medical-use guidance adds no condition to that license. Third-party licenses,
provider agreements and applicable law have their own scope; see
[third-party notices](THIRD_PARTY_NOTICES.md).
