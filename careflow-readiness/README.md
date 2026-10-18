# CareFlow Readiness Engine

Check Referral and Prior Authorization documentation against versioned deterministic
requirements. Reuse saved Copilot facts, attach received formal documents, inspect gaps
and supporting passages, and recalculate with persistent revisions and audit records.

Use the [workbench quick start](../README.md#run-it). CareFlow runs on port 8858 and
is integrated into the workbench on port 8857. [Shared-evidence API](../docs/patient-workbench/API.md#careflow-sharing)
documents the intake and synchronization contract. `DOCUMENTATION_READY` describes the
declared checklist, rather than a prediction of insurer approval.

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
