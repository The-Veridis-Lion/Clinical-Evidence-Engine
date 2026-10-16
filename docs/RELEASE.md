# Workbench release

One patient evidence record powers encounter-specific SOAP, cross-file answers and
Referral/PA documentation checks. The Gemini interface opens a supporting passage
under the selected SOAP point, then opens the full original file below on request.

## Reproduce the saved case

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r clinical-evidence-copilot/requirements.lock
.\start-products.ps1 -SavedCase
```

Open http://127.0.0.1:8857/workbench/. For live extraction from uploaded text, start
without `-SavedCase`. The README includes the optional OpenAI API connection.

The [public-copy validation](showcase-case-20261016/public-validation.json) restored
the selected synthetic evidence into an empty workspace, then used ordinary HTTP
entrypoints for SOAP, visit count, duration and both material requests. It observed
five visits, 85 known PT minutes with a missing duration, Referral ready and PA waiting
for prior-course evidence. The extraction ledger stayed at six saved calls.

The [walkthrough](showcase-case-20261016/media/workbench-walkthrough.mp4) and
[GIF](showcase-case-20261016/media/workbench-walkthrough.gif) show these saved results.
The [source guide](showcase-case-20261016/README.md) connects the original files,
actual Luna responses, calculation and material evidence.

## Focused software checks

Run each product separately so its Engine imports stay isolated:

```powershell
python -m pytest -q -c clinical-evidence-copilot/pyproject.toml clinical-evidence-copilot/tests
python -m pytest -q -c careflow-readiness/pyproject.toml careflow-readiness/tests
python -m pytest -q -c packages/evidence-verifier/pyproject.toml packages/evidence-verifier/tests
```

These synthetic controls cover product behavior and transport, rather than independent
clinical accuracy. Source-audit findings remain in the [selected reports](REPORTS.md).
