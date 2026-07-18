# Policy Assistant UI

A deliberately minimal React/TypeScript/Fluent UI test fixture. It exposes only grounded policy Q&A, a read-only metadata lookup, and an explicit-confirmation synthetic access-exception flow.

## Local commands

```bash
npm install
npm run dev
npm test
npm run build
```

By default the UI uses deterministic replay fixtures. Set `VITE_DATA_SOURCE=api` for the live adapter. Set `VITE_REPLAY_ONLY=true` for a recruiter/CI build that cannot switch to live model inference.

Repeatable state URLs are `?state=loading`, `?state=empty`, `?state=error`, and `?state=stale`.

## API boundary

The UI uses `POST /api/v1/assistant/chat` beneath `VITE_API_BASE_URL` for grounded answers and both tools. Read-only lookup sends a non-consequential `policy_lookup` request. Access-exception preparation receives a short-lived opaque server token bound to the actor, session, tool, and canonical arguments. Only the proposal-specific checkbox and confirmation button can send that token once; a boolean confirmation flag is ignored.

Entra/Container Apps authentication and the `Assurance.Assessor` tool role remain server-enforced; the pseudonymous identity label is display-only. In the Container App, nginx proxies `/api/` to the FastAPI localhost sidecar and preserves the Easy Auth principal header. Production startup loads the 15–25 document corpus from its HTTPS Blob container and rejects missing, mutated, misclassified, traversing, duplicate, or unmanifested content before building the FTS5 index.
