# Controlled behavioral evaluations

The fixed 50-case dataset is executed through the same `PolicyAssistantService` boundary used by the application. The runner builds a case-scoped synthetic retrieval index, invokes the selected `ModelAdapter`, exercises tool confirmation and authorization state, and records structured observations. It does not copy expected values into the result. The tool campaign includes at least twelve rejected negative paths and two separate, server-token-confirmed positive executions; each positive creates exactly one in-memory synthetic record.

## Deterministic replay gate

```bash
PYTHONPATH=src .venv/bin/python -m aica.cli evaluation generate \
  --adapter replay \
  --output /tmp/aica-replay-results.json
PYTHONPATH=src .venv/bin/python -m aica.cli evaluation behavioral \
  --results /tmp/aica-replay-results.json
```

CI runs both commands. `data/ai-evaluations/replay-results.json` is a checked-in example of the same versioned artifact. Replay proves the evaluation path, deterministic guardrails, retrieval, application controls, and evidence contract. It is not live-model quality evidence.

The result artifact records the dataset and configuration digests, adapter/deployment provenance, corpus-manifest digest, observed model versions, real correlation and interaction-evaluation IDs, measured latency, retrieved document IDs, guardrail outcomes, and tool state. The canonical configuration also binds the effective confirmation-token TTL and per-user hourly request limit. The expiry and rate-limit cases consume those exact values, and the runtime observations must match the signed configuration snapshot. Raw response prose is not retained; `response_sha256` binds separately controlled content without publishing it.

Local evaluation never recursively trusts files by extension. It enumerates the complete local snapshot, rejects links and unmanifested files, and verifies manifest membership, byte sizes, SHA-256 values, UTF-8 content, metadata, and document IDs before building any case index. The verified raw manifest digest and document count must equal the corpus binding in the evaluated configuration.

## Headless live release gate

Foundry and Phi are selectable only through configured runtime endpoints; there is no `live=true` or `live_endpoint_verified` input.

The Azure development assessment uses `AICA_AI_EVALUATION_MODE=live`. In that mode the AI
collector always executes the controlled dataset during `assure collect`; it writes the result only
under the current run's private workspace and never reads a checked-in or previous
`live-results.json`. Before model invocation, it reads
`evaluation_configuration_sha256` from the deployed Policy Assistant's HTTPS `/healthz` response.
The response is marked `Cache-Control: no-store` and contains only the digest, not an endpoint,
prompt, corpus, token, or configuration snapshot. The collector independently constructs the
evaluated configuration snapshot and records both digests. The snapshot binds the raw SHA-256,
version, ID, and document count of the deployed corpus manifest, so a checked-in corpus cannot be
mistaken for a different Blob-hosted deployment. For every live artifact it also requires a
deployment block containing the exact 40-hex source commit and the lowercase SHA-256 values of the
deployed API, Policy Assistant UI transport, and assessment-job images. Missing or malformed
deployment provenance invalidates a live artifact before inference.

The Container Apps assessment job receives the model endpoint, deployment, and deployed health
URL from Bicep. The protected `assessment` GitHub environment must define:

- `AICA_MODEL_ADAPTER` (`foundry` or `phi`)
- `AICA_MODEL_DEPLOYMENT`
- `AICA_FOUNDRY_ENDPOINT` or `AICA_PHI_ENDPOINT`
- `AICA_PHI_TOKEN_SCOPE` when Phi is selected
- `AICA_DEPLOYED_CONFIGURATION_URL` (`https://<deployed-assistant>/healthz`)
- `AICA_DEPLOYED_SOURCE_COMMIT` (the exact successful supply-chain commit)
- `AICA_ASSURANCE_API_IMAGE_SHA256`, `AICA_ASSISTANT_UI_IMAGE_SHA256`, and
  `AICA_ASSURANCE_JOB_IMAGE_SHA256` (64-hex values from verified Azure MCP deployment readback)

The Bicep source scopes Cognitive Services OpenAI User to the collector identity on only the
selected Foundry account. The Phi fallback exposes HTTPS ingress behind Container Apps Easy Auth;
only the assistant and collector managed-identity client IDs are allowed, and both request an
`api://<assistant-client-id>/.default` token. The protected workflow reuses its federated collector
identity, so no long-lived model token is stored.

Missing configuration, a replay adapter, an unreachable/redirecting digest URL, invalid digest,
model authentication failure, or model transport failure terminates live collection nonzero. A
successfully fetched digest that differs from the independently evaluated configuration is retained
in the signed package with `evaluation_gate_status=FAIL`; it cannot silently fall back to replay.

## Manual live diagnostic

Foundry:

```bash
export AICA_FOUNDRY_ENDPOINT='https://<verified-resource>.openai.azure.com'
export AICA_MODEL_DEPLOYMENT='<verified-deployment>'
export AICA_DEPLOYED_CONFIGURATION_SHA256='<digest exported by the deployed workload>'
PYTHONPATH=src .venv/bin/python -m aica.cli evaluation generate \
  --adapter foundry \
  --deployed-configuration-sha256 "$AICA_DEPLOYED_CONFIGURATION_SHA256" \
  --output artifacts/private/ai-evaluations/live-results.json
```

Phi fallback:

```bash
export AICA_PHI_ENDPOINT='https://<verified-container-app>'
export AICA_PHI_BEARER_TOKEN='<short-lived secret>'
export AICA_DEPLOYED_CONFIGURATION_SHA256='<digest exported by the deployed workload>'
PYTHONPATH=src .venv/bin/python -m aica.cli evaluation generate \
  --adapter phi \
  --deployed-configuration-sha256 "$AICA_DEPLOYED_CONFIGURATION_SHA256" \
  --output artifacts/private/ai-evaluations/live-results.json
```

Before calling either manual command, independently preserve the Azure MCP quota/configuration
check and the digest returned by the deployed health endpoint. A live artifact is accepted only
when its adapter kind is Foundry or Phi, an endpoint fingerprint is present, at least one
selected-adapter model invocation completed, and none of those selected invocations reports
replay. The AI release collector additionally requires all cases to pass and the evaluated
configuration digest to equal the independently supplied deployed digest. Missing provenance or a
mismatch produces `FAIL`; a replay artifact can never produce a live release pass.

The external smoke remains pending until an actual endpoint, quota, model version, latency, and exact deployed digest are captured. Do not commit live endpoint names, tokens, raw responses, tenant identifiers, or subscription identifiers.
