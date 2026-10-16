# A longitudinal knee-care showcase

**Synthetic demonstration:** a newly authored patient journey from initial knee-pain consultation through imaging, therapy, medical follow-up and documentation review. Jordan Avery is fictional.

The case contains **eight original files, five registered visits and three attended PT sessions**. GPT-6 Luna/high extracted each of the six clinical files once. The two formal materials entered the same workbench through document intake. Saved facts support both products without repeated extraction.

## The story

| Record | Encounter / event | What the source establishes |
| --- | --- | --- |
| [Initial dialogue](sources/01-initial-consultation-v2.txt) | V1 · September 1 | Complete source material for CC, HPI, relevant history, actual medication use, ROS, vitals, examination, clinician assessment and plan. Stair pain 7/10; rest pain 2/10. OA is suspected. X-ray and PT are ordered, not performed. |
| [Radiology](sources/02-left-knee-radiology.txt) | September 3 event, reviewed at V4 | Mild medial degenerative findings; no acute fracture. The report date is distinct from its later review encounter. |
| [Referral order](sources/03-referral-order-v2.txt) | Issued September 1 | Explicit patient, request, service, provider and destination. This received document establishes an order; the symptom alone does not. |
| [First PT record](sources/04-pt-initial-treatment.txt) | V2 · September 8 | Session PT-S1, 40 documented minutes; stair pain 6/10. Exercise components are not extra sessions. |
| [PT follow-up dialogue](sources/05-pt-followup-dialogue.txt) | V3 · September 15 | Session PT-S2, 45 documented minutes; stair pain 5/10. Home exercise is separate from clinic attendance. |
| [Medical follow-up](sources/06-primary-care-followup.txt) | V4 · September 22 | Imaging review, stair pain 4/10 and a medication instruction change. Recounting the previous sessions does not add PT minutes. |
| [Third PT record](sources/07-pt-third-session-v2.txt) | V5 · September 29 | Stair pain 3/10. PT-S3 occurred, but its duration is missing. One completed session does not establish a completed six-week course. |
| [PA packet](sources/08-prior-authorization-packet-v2.txt) | Received September 30 | Provider request, form and payer context for an extension. The declared project checklist requires completed prior therapy, which the available evidence does not establish. |

Stair pain follows **7 → 6 → 5 → 4 → 3 / 10**, with separate resting scores and original passages at each visit.

## What actually ran

- The first visit produces all four SOAP sections with source links and all nine checked content domains: HPI, history, medications, ROS, vitals, examination, assessment, plan and follow-up advice.
- The repaired query adapter consumes Luna's complete dates and event labels to calculate **85 known PT minutes**, with the missing session duration visible. The same saved data previously yielded 0. Each included event retains its label, original date and calculation evidence.
- Referral: clinical evidence alone → `NEEDS_EVIDENCE`; received formal order → `DOCUMENTATION_READY`.
- PA: provider request, form and payer context become `SUPPORTED`; completed-course evidence remains a visible requirement to resolve.
- The demonstrated queries and readiness recalculations add **zero extraction calls**. Source audits and original responses are retained for inspection.

This is the product's central story: a lightweight model preserves a longitudinal clinical narrative, and a single saved evidence record powers readable notes, traceable calculations and request-specific checks. Clinically specialized models are a promising future improvement path.

## Run it from the original files

Download the [eight original source files](synthetic-knee-showcase-sources.zip), then start the ordinary product:

```powershell
.\start-products.ps1
```

Create the synthetic patient, upload the six clinical files and associate them with the encounters above. Luna performs the extraction. Add the two formal documents to the corresponding Referral/PA requests through material intake. The repository README also describes the OpenAI API connection.

To inspect the extraction already recorded for this case, use `.\start-products.ps1 -SavedCase` instead. This restores the actual Luna responses and databases without a new model request. It retains later saved revisions rather than resetting them.

Open **http://127.0.0.1:8857/workbench/**. Add `-CopilotPort 8875 -CareflowPort 8876` if those ports are occupied.

1. Select **Jordan Avery · synthetic knee rehabilitation**, then V1. Read the concise SOAP key points; **All facts** opens the detailed extraction. Click a key point, then **View full source**, to inspect the exact passage below.
2. Select V2–V5 to compare recorded symptoms and plans. For **Documented duration**, leave concept blank and set **Service type** to `physical therapy session`. The selected action type groups the 40- and 45-minute events while retaining their individual labels and sources.
3. Open the calculation's included and missing records. The third session and unresolved duplicate/temporal mentions remain visible; 85 is a known subtotal, not a full total.
4. Open CareFlow and inspect `showcase-referral` and `showcase-pa`. Each result links to the received material and clinical evidence. Existing material history shows the before/after stages.

Switch visits to inspect the full stair-pain story, or query a saved clinical concept to compare its recorded mentions.

## Results and implementation evidence

[Machine results](metrics-and-results.json) · [Source manifest](case-manifest.json) · [First-visit source audit](initial-v2/independent-audit.json) · [Follow-up audit](followups/source-audit.json) · [PA support trace](careflow/source-consumption-audit.json) · [Before/after query](query-after/pt-duration-response.json)

Active extraction calls took approximately **33–101 seconds each**. The six active sources plus one retained authoring-format revision used seven calls, with no retries. Exact usage is in the machine report; no billed cost is available.

Watch the [workbench walkthrough](media/workbench-walkthrough.mp4) or [animated preview](media/workbench-walkthrough.gif): the full workbench, same-module English captions and focused highlights, exact evidence, calculations, symptom records and material checks. [Playback and source records](media/playback-validation.json) accompany the recording.

Remaining extraction and binding issues are recorded in the source audits; independent clinical validation is future work.
