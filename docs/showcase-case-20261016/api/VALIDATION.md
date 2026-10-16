# Optional OpenAI API transport validation

No live OpenAI request was sent: this shell has no `OPENAI_API_KEY`. The `--check` invocation used a temporary placeholder value solely to validate local provider selection, without creating a response or model call. The API transport tests replaced `urlopen` and asserted one POST, the fixed `gpt-6-luna`/`high` request, strict schema, durable response/usage, and no persisted authorization key.

Validation on 2026-10-16:

- API transport fake-envelope tests: 7 passed. Completed, incomplete, refusal, unexpected operation, HTTP failure, disconnected transport, missing key, and invalid schema are covered.
- Copilot extraction/workbench non-HTTP tests: 29 passed, 1 HTTP test deselected. The structured task suite including cross-provider saved-success reuse: 19 passed.
- CareFlow extraction/intake non-HTTP tests: 44 passed, 2 HTTP tests deselected. The structured task suite including cross-provider saved-success reuse: 28 passed, 1 HTTP test deselected.
- Copilot and CareFlow local HTTP regressions: 1 passed each when run with local loopback access outside the network-restricted sandbox. These used fake providers and touched no running product service.
- `tools/serve_products.py --check --provider openai_api` and `start-products.ps1 -Check -Provider openai_api`: passed for both products, `model_calls: 0`.

Earlier sandboxed HTTP attempts failed at loopback connection with Windows `WinError 10013`; both exact tests passed with loopback access. An earlier CareFlow test run used an unusually long pytest base path and hit Windows path length during artifact writing; that exact test passed with a short base path. Neither failure involved the API transport or model output.

OpenAI authentication, account entitlements, actual API schema acceptance, latency, and billing remain unverified until the user supplies a server-side key and explicitly initiates a live Extract operation.
