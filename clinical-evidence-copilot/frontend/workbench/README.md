# Workbench frontend

The Gemini workbench design connects to Copilot and CareFlow through the same-origin
HTTP facade. Python serves the checked-in production build at `/workbench/`.
No Gemini model or SDK is needed to run the interface.

For frontend development, use Node 22.12+ or 24:

```sh
npm ci
npm run typecheck
npm run build
```

The UI uses durable patient revisions, exact source coordinates and local CSRF protection.
Existing Apache-2.0 SPDX notices are retained; dependencies are pinned in `package-lock.json`.
