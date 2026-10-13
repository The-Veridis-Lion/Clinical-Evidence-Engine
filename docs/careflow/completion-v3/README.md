# CareFlow completion checkpoint v3

This is an implementation checkpoint, **not final product acceptance**. PR #3's
isolated shared fix is `90adea7`; CareFlow integrated it without conflicts in
`d54fa9f`. No main merge, deployment, Copilot checkout modification or purchase.

## Clinical evidence mapping

`ClinicalBinding` is explicit request intake evidence. Its original structured
source must contain the matching binding, patient/request/service/code system,
material requirement and original context fact IDs. The mapper checks source
availability, subject, relative time, attribution, assertion and execution state.
Four reusable material roles are supported: referral reason, attached clinical
summary, investigation result and completed therapy. Clinical evidence never
creates a PA application, payer identity, provider intent or destination.

The mapping registry `careflow-clinical-mapping/1` contains eight separately
versioned rules, conditions and a content hash. Existing checklist versions and
five-state semantics remain unchanged. Canonical documented execution is required;
diagnostic procedures additionally cannot count as treatment. No patient, phrase,
document or medical-concept special case exists in product logic. Relative clinical
time is preserved; an exact event date or payer lookback is not invented.

Every selected required target must be established; one complete target cannot
hide another unknown target. Human/AI opinions stay separate. Source-supported
amendments can correct a derived fact, preserve its history and recompute rules.

56 mapping tests cover different patients, both request types, clinical categories,
positive/negative/unknown states, source scope/availability, execution versus plan,
partial targets and authorized corrections. The actual original clinical-text
Luna outputs were mapped through real HTTP case creation/evidence updates into
JSON/Markdown, persisted revisions and verified audits for both request types.
The two output examples reuse two original valid Luna calls; constructed intake
records are explicitly labelled, not physician sign-offs or insurance decisions.

## Reproduce an actual API workflow

From the CareFlow checkout, Python 3.12 and the repository environment:

```powershell
$env:PYTHONPATH = 'src'
python -m clinical_intelligence.careflow --db artifacts/new-mapped.sqlite http-workflow `
  --case artifacts/careflow-completion-v3/actual-mapped-e2e/CF-MAPPED-referral-input.json `
  --update artifacts/careflow-completion-v3/actual-mapped-e2e/CF-MAPPED-referral-update.json `
  --output artifacts/new-mapped-http
```

Use a new DB/output path. Replace `referral` with `prior_authorization` for the
second actual input. Public dataset outputs are local ignored artifacts, not a
claim that GitHub contains every downloaded dataset. The existing committed
`examples/careflow` provides the offline material-only demo in any fresh checkout.

## Frozen development extraction

The original ACI47/20 and ACN200/200 group splits remain unchanged. The fixed source
cohort is 47 ACI dialogues and 400 ACN representative full notes/dialogues. Reuse
existing valid caches; do not invoke Luna again for their semantic score.

```powershell
python -m clinical_intelligence.careflow.evaluation.batch `
  --aci artifacts/careflow-evaluation-v2/aci --acn artifacts/careflow-evaluation-v2/acn `
  --output artifacts/careflow-completion-v3/development `
  --cache artifacts/careflow-evaluation-v2/acn-product-pilot/cache `
  --ledger ../artifacts/model-scheduling/careflow-copilot-calls.sqlite `
  --legacy-root ../clinical-evidence-engine --workers 10
```

Shared scheduling caps participating Luna callers globally at50 and CareFlow at25;
the other project has not adopted it, so no guarantee about unregistered callers.
Original responses, repairs, failures, unknown usage and every attempt persist.
Two extra retries are allowed only for upstream/mechanical failure. Two consecutive
upstream document failures stop new dispatches; unattempted documents remain in the
cohort. Convenience results must match reconstructed first accepted raw output.
Each invocation saves a new summary; the first summary is never overwritten.

## Reference availability and independent reporting

The failed large reference-transcription route has stopped:45 research attempts
were reserved, including39 local setup failures,4 upstream failures and2 uncertain
dispatches. All count against100; no valid labels were produced. They are not
reclassified as product calls. Luna's two new ACI probes produced valid outputs
with3 mechanical failures/repairs preserved.

Native reference units are a lossless, source-independent view of original strict
ACN JSON leaves and original ACI note spans. The development view preserves447
documents,12,430 known units and112 malformed-label documents. Null/None placeholders
remain inspectable nonassertions; they never become clinical denials. Original raw
labels, hashes, split, historical gold and scores are not changed. These units do
not label every ClinicalFact qualifier; no complete original clinical P/R/F1 can
be honestly inferred. All extra predicted assertion dimensions need source review.

Sol source support, native-unit coverage, error classes and field mechanisms are
separate auxiliary measures. Missing reference denominators are unknown, not zero;
complete-cohort recall/F1 is unavailable for that dataset. Known-reference coverage
is separately labelled, includes unsupported original units, and cannot establish
full-cohort acceptance. Native notes/generated summaries and Sol opinions are not
independent medical gold. No structured-reference or PA approval gold is fabricated.

```powershell
python -m clinical_intelligence.careflow.evaluation.native_reference freeze `
  --aci artifacts/careflow-evaluation-v2/aci --acn artifacts/careflow-evaluation-v2/acn `
  --references artifacts/careflow-completion-v3/native-references-development
```

## Actual verification

- Shared repairs483 passed; initial integration773 passed.
- Complete mapping implementation833 passed; subsequent batch protection837 passed.
- Latest native/reference/batch checks12 passed; full new regression843 passed.
- Same frozen material development312 scenarios/2,028 checks: macro-F1=100%,
  serious false Ready0, source2076/2076, rule2340/2340.
- Public clinical semantic P/R and final holdouts remain incomplete.

JUnit reports retain intermediate failures and before/after evidence. The constructed
material holdout and public holdout have not been reserved or run. Final code SHA,
prompt/schema/model/data/rules/scorer seal is required before either. Do not claim
that development scores, successful caching or API code alone meet final acceptance.
