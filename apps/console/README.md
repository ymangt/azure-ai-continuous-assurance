# Assurance Console

React, TypeScript, Vite, and Fluent UI implementation of the audit and risk workbench. The bundled fixtures use the public baseline and remediated assessment IDs from `data/sample-runs`.

## Local commands

```bash
npm install
npm run dev
npm test
npm run build
```

The default build reads the checked-in signed baseline/remediated packages, manifests, diff, and replay artifacts directly from the repository through a Vite virtual module. Set `VITE_DATA_SOURCE=api` to call `/api/v1`; live mode does not fill missing API fields from the public sample. Set `VITE_PUBLIC_MODE=true` for the public read-only build; mutating actions are not rendered in that mode.

Repeatable UI states are available for verification:

- `?state=loading`
- `?state=empty`
- `?state=error`
- `?state=stale`
- `?mode=public`

Navigation uses URL fragments such as `#controls` and `#runs`, so both nginx and Static Web Apps can serve the app without route rewrites beyond the SPA fallback.

## API boundary

The client uses the plan's read interfaces (`runs`, run controls, findings, risks, evaluations, and diffs) and authenticated command interfaces (`run-requests`, `retest-requests`, `review-decisions`, and `exceptions`). In API mode it requests the evaluation carried by the selected verified run; no image build argument or bundled replay ID can substitute another run's evidence. The checked-in signed samples include their runtime system record, and the System screen normalizes and renders its boundary, flows, inventory, identities, classifications, shared responsibility, and exclusions. A live response that omits that record is still shown as unavailable; the UI never substitutes fixture architecture.

In the private Container App, nginx proxies `/api/` to the FastAPI localhost sidecar and preserves the Container Apps Easy Auth principal header. The public Static Web Apps build sets `VITE_PUBLIC_MODE=true`, uses sanitized snapshot data, and renders no command controls.
