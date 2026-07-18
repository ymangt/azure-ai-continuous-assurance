# Release readiness

This file separates deterministic repository completion from claims that require elapsed time, a live tenant, or independent people. A checked box must be supported by an artifact or repeatable command; it is never inferred from code existing.

## Deterministic repository gates

| Gate | State | Evidence |
|---|---|---|
| 25 controls / 35 objectives | Complete | `assurance/controls/control-profile.json` and artifact validator |
| At least 16 automated and 8 manual/hybrid procedures | Complete | 19 automated, 8 hybrid, 8 manual |
| Official OSCAL v1.2.2 validation | Complete | Nine documents plus checksum-pinned complete schema |
| No false pass for missing, stale, unauthorized, failed, or malformed evidence | Complete | Rule/pipeline negative tests |
| Mutation-detecting signed package chain | Complete | Manifest and read-store tests; two signed samples |
| Immutable retest history and signed diff | Complete | Runtime retest lifecycle tests |
| Wrong-role authorization | Complete | FastAPI/UI command tests plus content-minimized live-collector 401/403 probe tests |
| Consequential-tool confirmation binding | Complete | Expiry, replay, actor/session/tool/argument, role, and concurrency tests |
| Fixed AI behavior and mapping harnesses | Complete | 50 service-executed replay cases with adapter/configuration provenance and 72 AI-assisted label candidates |
| Public-boundary validation | Complete | Signed-sample validation and CI public build scan |
| Reproducible three-plane Azure source | Complete | Bicep, Rego, What-If guards, Sentinel contracts |
| Image, corpus, and Entra deployment handoffs | Complete | Exact-commit signed-image set and active-image receipt verifiers, deterministic corpus bundle/receipt verifier, two-app role specification, callback materializer, protected workflow gate |

## Live and human-observed gates

| Gate | Current state | Required evidence before claiming completion |
|---|---|---|
| Enabled subscription, policy, quota, and cost recheck | Partial — Azure MCP rechecked 2026-07-17 America/Toronto; enabled Student subscription, allowed-region policy, existing Sentinel workspace, and East US 2 regional availability confirmed; deployable Foundry quota and usable retail-price rows remain unproven | Private timestamped MCP outputs and digests, including account-scoped deployable model quota and a reviewed cost forecast |
| Reviewed ARM What-If and foundation deployment | Pending | No unexpected delete, privilege, exposure, or out-of-bound resource |
| Corpus and Entra tenant materialization | Pending Azure MCP execution | Exact-prefix Blob readback receipt plus two app/service-principal/role/assignment readbacks |
| Deployed image/source readback | Pending Azure MCP execution | Verified active Policy Assistant API/UI images, assessment-job image, active revision/traffic, and matching source/digest tags bound to the reviewed supply-chain image set |
| Deployed authorization boundary probe | Pending live workload | Signed `application.authorization_tests` evidence showing unauthenticated 401 and collector-identity 403 from the deployed Assurance Console route |
| Foundry quota plus controlled smoke evaluation, or verified Phi fallback | Pending | Azure MCP quota/configuration evidence plus a structurally validated live result recording endpoint fingerprint, selected adapter, model/version, latency, provenance, and an exact evaluated/deployed configuration-digest match |
| Eight complete failure campaigns | Pending live execution | Per-scenario baseline, injected failure, remediation, retest, and zero-leftover proof |
| Three deploy/teardown cycles | Pending elapsed executions | Three independently timestamped What-If/deploy/verify/cleanup records |
| 14 days and 10 successful scheduled runs | Pending elapsed time | Signed manifests spanning at least 14 days |
| Human review of 72 mapping labels and 50 expected behaviors | Pending | Attributed decisions with rationale and artifact hashes |
| Practitioner/professor review | Pending external reviewer | Preserved attributed response |
| Public live site and recorded five-minute walkthrough | Pending workload release | URL, sanitized review, and recording |

Until the second table is evidenced, the honest release level is a fully tested local/replay implementation and deployment-ready Azure handoff—not an operating-effectiveness or live-model claim.

The 2026-07-17 Azure MCP recheck found no `rg-aica-*` groups or resources and performed no
mutation. Foundation What-If remains intentionally blocked until the protected budget recipient
is supplied. Workloads remain additionally blocked on the ordered corpus, Entra, immutable-image
provenance, signing-key, GitHub App, and live-model gates described in the deployment runbook.
