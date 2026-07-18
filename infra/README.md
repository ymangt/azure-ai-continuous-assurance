# Azure infrastructure

This directory is the reproducible source of truth for the three AICA lifecycle groups and the version-controlled content added to the existing Microsoft Sentinel workspace. Azure creation is performed through the Azure MCP protocol; the local scripts only compile, validate, inspect exported What-If data, and produce a deployment handoff.

## Deployment gates

1. Copy a Student parameter file and replace the budget email and repository metadata.
2. Run `scripts/azure/preflight.sh <parameters.bicepparam>` and compile with Bicep 0.45.15 or newer.
3. Through Azure MCP, recheck the enabled subscription, allowed regions, current cost/currency, provider registration, the existing Sentinel workspace, and Foundry quota.
4. Run subscription-scope What-If through MCP. Save its JSON as private evidence and pass it to `scripts/azure/review-what-if.py`.
5. Reject deletes, unexpected role assignments, public/anonymous storage, resources outside the four approved groups, or a model deployment without recorded quota.
6. Deploy the exact compiled template and parameter artifact through MCP, monitor completion, then verify with Resource Graph/service queries.

The safe foundation creates both empty Consumption environments but no apps/jobs. Read the `assuranceAuthRedirectUri` and `assistantAuthRedirectUri` deployment outputs, then use [`infra/entra/app-registration-handoff.json`](entra/app-registration-handoff.json) and `scripts/azure/prepare-entra-handoff.py` to prepare the exact two-app MCP request. It fixes the single-tenant audience, callback sources, three human roles plus the narrowly scoped application roles required for collector/Phi token issuance, stable role UUIDs, assignment-required policy, and assignment expectations. Workload preflight accepts the two client IDs only with a protected, tenant-bound Azure MCP readback receipt. This avoids guessing the environment-specific domain and keeps every replica at zero until images and identity configuration are ready.

The foundation intentionally creates an empty private `synthetic-corpus` container. Before enabling
the Policy Assistant workload, build the deterministic `corpus-handoff.yml` artifact and use only
Azure MCP Storage `storage_blob_upload` to create its 19 payload blobs under the immutable
`northstar-synthetic-policy-corpus/1.0.0` prefix. MCP `storage_blob_get` readback becomes a protected
materialization receipt; workload preflight checks the receipt's bundle/manifest digest, exact blob
set, properties, environment, and subscription. The compiled workload uses that same manifest-derived
prefix, and the production API independently verifies the complete 15–25-document snapshot before
indexing. See [`docs/operations/azure-deployment-handoffs.md`](../docs/operations/azure-deployment-handoffs.md).

The workload deployment wires the scheduled assessment job to run the behavioral collector in
live-only mode against the selected Foundry deployment and to bind the result to the deployed
Policy Assistant configuration digest exposed on `/healthz`. When Foundry is enabled, the template
declaratively grants the collector identity Cognitive Services OpenAI User at only that Foundry
account. When the zero-quota Phi fallback is enabled, its external HTTPS ingress is protected by
Easy Auth and admits only the assistant and collector managed identities; no static model bearer
secret is deployed. The health and evaluation digests include the same deployed 300-second
confirmation TTL and ten-request per-user hourly ceiling that the assistant enforces; changing
either value requires a new passing behavioral artifact.

The What-If guard fails closed for resources without an approved resource-group scope. Its only subscription-level exceptions are the CAD 25-or-lower AICA budget, the exact two-action command-worker custom role, and a service-principal Security Reader assignment; all other group-less changes are rejected.

`student.dev.bicepparam` is the safe foundation baseline. `student.foundry-preflight.bicepparam` creates only the Foundry account/project gate. `student.model-after-quota.bicepparam` must not be used until MCP quota evidence is attached to the change. `student.workloads-example.bicepparam` documents the four routine digest-pinned images, their exact 40-hex assessed source commit, two Entra client IDs, trusted Key Vault JWK thumbprint, and numeric GitHub App/installation IDs, but is intentionally undeployable until every placeholder is replaced. `student.phi-after-quota-failure.bicepparam` adds the separately protected Phi digest and requires evidence that deployable Foundry quota is zero. Both workload examples deliberately omit `pseudonymizationSecret` and `githubAppPrivateKey`; provide those values only as secure MCP parameters. The fixture example is intentionally undeployable until its expiry placeholder is replaced. Complete the external GitHub gate in [`docs/operations/github-app-authentication.md`](../docs/operations/github-app-authentication.md) before enabling workloads.

Workloads are a second-stage deployment. Deploy the foundation first, retrieve the non-exportable signing key's public JWK through Azure MCP, calculate its RFC 7638-style SHA-256 thumbprint using the repository's canonical verifier, and supply it as `trustedSigningKeyFingerprints`. The APIs and retest pipeline reject self-signed packages whose signer is not on that allowlist or whose versioned key ID is outside the expected Key Vault prefix.

Workload deployment follows foundation → Sentinel DCR/RBAC → apps/jobs. The private Assurance Console and Policy Assistant each use a same-app UI container on port 8080 with the Python API as a localhost port-8000 sidecar behind one Easy Auth ingress. The separate Free Static Web App is the sanitized public build. A dedicated command-worker job polls every five minutes, ETag-claims queued commands, and starts the assessment job without granting the browser-facing console Azure job-execution rights. Supply-chain image names map to `deploy/api.Dockerfile`, `deploy/job.Dockerfile`, `apps/console/Dockerfile`, and `apps/policy-assistant/Dockerfile`; never substitute a floating tag for their recorded digests.

## Lifecycle and identity boundaries

| Scope | Lifecycle | Contents |
|---|---|---|
| `rg-aica-control-cc` | persistent | evidence/corpus storage, Table Storage, P-256 signing key, identities, operations telemetry, Free Static Web App, optional scale-to-zero API/jobs |
| `rg-aica-sut-eus2` | demonstration | optional scale-to-zero Policy Assistant, Foundry account/project, separately quota-gated model deployment |
| `rg-aica-fixture-eus2` | ephemeral | only tagged synthetic fixtures; no VMs, credentials, public data, or attached Internet targets |
| `rg-sc200-sentinel-lab` | existing | two minimal custom security tables, Direct DCR, four scheduled analytics rules, focused workbook |

The bootstrap identity receives only Role Based Access Control Administrator on the three project groups. The GitHub deploy identity receives Contributor on those groups and cannot grant roles. Workload identities are split across assistant, collector, console, command worker, Sentinel content, and fixture janitor functions. The collector receives Secrets User on only the versioned GitHub App private-key secret, Crypto User on the signing key, and Table Data Reader on only `reviewdecisions`; the table read lets a retest preserve artifact-bound lifecycle events in its new signed package but cannot create a reviewer event. Other workloads cannot read the GitHub credential. The assistant receives Table Data Contributor only on `assistantratelimits`, where an ETag-protected pseudonymous sliding window enforces the per-user ceiling across restarts and replicas. The command worker receives Table Data Contributor on only `commandrequests` and `reviewdecisions`, plus a custom role containing only `Microsoft.App/jobs/read`, `Microsoft.App/jobs/execution/read`, and `Microsoft.App/jobs/start/action` assigned on the single assessment job. It receives no evidence, Key Vault, Sentinel, or deployment permissions. Initial assignment of authority to the bootstrap identity still requires an existing subscription owner through MCP; a principal cannot safely bootstrap its own authority.

The two deployable fixture scenarios share a private, recoverable storage baseline. `excessive-managed-identity-privilege` keeps operations diagnostics enabled and adds only an over-broad data-plane assignment to an unattached identity. `missing-diagnostic-settings` creates no identity or role and omits only that diagnostic setting. The public-storage condition remains an offline IaC/What-If fixture and is never deployable.

## Explicit residual risks and costs

- Storage, Key Vault, Foundry, Log Analytics ingestion/query, Direct DCR ingestion, Static Web Apps, and Container Apps ingress use public Azure service endpoints. Anonymous blob access and shared-key storage authentication are disabled; workload access uses Entra ID/RBAC. Private endpoints, NAT Gateway, and Firewall are a documented enterprise target state and are excluded from the CAD 25/month student baseline.
- Container Apps use Consumption with `minReplicas=0` and `maxReplicas=2`. Scheduled jobs run one replica. Images must be public GHCR references pinned by digest and signed before workloads are enabled.
- The command worker runs up to once every five minutes (288 short polling executions per day). Its 0.25-vCPU/0.5-GiB, 180-second timeout limits blast radius but does not guarantee zero cost; MCP verification must inspect actual execution duration and budget impact after deployment.
- A high-entropy pseudonymization value is supplied only through the protected MCP deployment. Bicep stores a versioned Key Vault secret, and the console/assistant identities receive Secrets User only on that secret. The secret value is never an output, committed parameter, or handoff artifact.
- Operations logs are sampled and capped at 1 GB/day with 30-day retention. Sentinel receives only assurance-run status and pseudonymous rejected-tool events, not prompts, responses, evidence bodies, or routine traces.
- Blob versioning and 14-day soft delete provide recoverability. Lifecycle rules remove private evidence after 90 days, versions sooner, and sanitized evidence after 365 days. This is tamper-evident storage, not locked WORM.
- The budget amount is interpreted in the subscription billing currency. MCP preflight must confirm that currency is CAD; budgets alert but do not stop spend. The daily janitor and scale-to-zero settings are the enforcement mechanisms.
- Key Vault purge protection creates an unavoidable residual retention period after deletion. Soft-deleted vault names/keys may remain unavailable for reuse for up to 90 days.

## Foundry gate

The Foundry account uses managed identity, disables local authentication, and intentionally permits a public endpoint for the student-cost profile. The model deployment is disabled independently. After account creation, query East US 2 model quota through MCP, confirm non-zero `gpt-4o-mini` Global Standard capacity, deploy the smallest permitted capacity, run a 400-token-capped smoke test, and capture model/version/region/quota/deployment type as evidence. If quota remains zero, leave the deployment disabled and use the documented Azure-hosted Phi fallback path in the application runbook.

The Phi path is mutually exclusive with a Foundry model deployment. It uses the revision-pinned int4 ONNX image, HTTPS ingress restricted by Easy Auth to the assistant and collector managed identities, 4 vCPU/8 GiB, `minReplicas=0`, and `maxReplicas=1`. The protected fallback workflow is the only routine that downloads/builds the model. Both preflight and `review-what-if.py` fail closed unless zero-quota evidence and the explicit Phi approval flag are present. MCP must record cold-start, latency, memory, provenance/license, and estimated cost, then confirm the app returns to zero replicas after the demonstration.

As of the July 2026 implementation check, Microsoft lists `gpt-4o-mini` version `2024-07-18` as GA for Global Standard but scheduled to retire on 2026-10-01, with `gpt-4.1-mini` as the replacement. The plan keeps `gpt-4o-mini` because Student quota is the binding constraint; every preflight must also record lifecycle status and test the replacement before the retirement date. See <https://learn.microsoft.com/azure/foundry/openai/concepts/model-retirement-schedule>.
