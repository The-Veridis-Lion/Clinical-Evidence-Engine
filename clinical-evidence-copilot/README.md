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
