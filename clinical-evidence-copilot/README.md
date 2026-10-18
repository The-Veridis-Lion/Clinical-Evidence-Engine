# Clinical Evidence Copilot

Extract clinical facts with GPT-6 Luna, generate encounter-specific SOAP key points,
and inspect the original passages behind each statement. Saved facts also power
patient-level duration queries, symptom histories, optional review and durable revisions.

Use the [workbench quick start](../README.md#run-it) to launch the compiled Gemini UI
and both products. [HTTP routes](../docs/patient-workbench/API.md) describe the same-origin API.

The `src/clinical_intelligence` package contains the shared Engine primitives and
the Copilot application. The launcher isolates each product's import path and database;
do not install both identically named development distributions into one environment.

For frontend changes, see [frontend/workbench](frontend/workbench/README.md).

## Use boundaries and licensing

Clinical content is a supporting draft or evidence summary. A qualified healthcare
professional must review original evidence and patient context before diagnosis,
treatment, medication or other substantive patient-care decisions. CareFlow
readiness means checklist completeness, not medical necessity, insurance approval
or final authorization. No clinical validation, regulatory approval or compliance
certification is claimed. These are intended-use responsibilities, not an added
software license condition or an implemented clinical sign-off gate.

See [medical-use guidance](../MEDICAL_USE.md) and
[third-party notices](THIRD_PARTY_NOTICES.md). Original project code and documentation use the standard
[Apache License 2.0](LICENSE.md). Third-party libraries and resources retain their
own licenses and applicable agreements.
