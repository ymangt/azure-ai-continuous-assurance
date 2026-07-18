# Threat model

Method: system trust-boundary review using STRIDE concepts, NIST AI RMF concerns, and the OWASP Agentic Top 10 as an adversarial taxonomy. This is a scoped engineering threat model, not a formal certification artifact.

| ID | Boundary / asset | Threat scenario | Primary controls and tests | Residual treatment |
|---|---|---|---|---|
| TM-001 | Entra/private API | A user calls a reviewer command without the required role. | AC-3.1 wrong-role 403 tests; append-only decisions | Low after deny-by-default tests |
| TM-002 | Workload identity | A collector or assistant identity receives excessive privilege. | AC-6.1 full assignment inventory; SCN-002 | Daily detection; quarterly need review |
| TM-003 | Deployment identity | A stored credential is stolen or OIDC trust is broadened. | IA-5.1 federation inspection and secret scans | Reassess federation claims on change |
| TM-004 | Azure network boundary | An Internet RDP/SSH rule exposes administrative access. | SC-7.1 complete rule/attachment query; SCN-001 | RSK-001 closed; daily regression check |
| TM-005 | Managed public endpoint | Reachable service perimeter is abused or denied service. | Entra/RBAC, TLS, rate limit, scale cap, monitoring | RSK-005 / EXC-001 through 2026-09-01 |
| TM-006 | Synthetic corpus | Poisoned or stale content changes policy answers. | AI-DP-01.1 provenance, hashes, active-version checks | Corpus changes trigger full evaluation |
| TM-007 | Retrieval-to-model boundary | Retrieved instructions hijack model behavior. | Eight injection cases, delimiters, detection, citation validity | RSK-002 Moderate; expand attack set |
| TM-008 | Model-to-tool boundary | Model output or crafted client bypasses authorization/confirmation. | AI-AC-01.1; twelve negative and two positive cases | RSK-003 Low after remediation |
| TM-009 | Tool implementation | Argument substitution or token replay changes the action. | Actor/session/tool/argument/expiry binding; single use | Re-run on tool schema change |
| TM-010 | Release pipeline | Unevaluated model, prompt, corpus, or tool change deploys. | AI-TE-01.1 exact digest binding; SCN-008 | RSK-004 Low after remediation |
| TM-011 | Software supply chain | Mutable action/image or vulnerable dependency changes build output. | RA-5.1, SA-11.1, commit/digest pinning, SBOM | Scanner freshness limitation retained |
| TM-012 | Evidence collection | API denial, staleness, or parsing failure is misreported as pass. | CA-7.1 negative semantics; explicit ERROR/NOT_RUN | Hard invariant; pipeline release blocker |
| TM-013 | Evidence store | An actor mutates or deletes historical evidence. | Separate identity, versions, soft delete, hashes, ES256 manifest | Tamper-evident only; no locked WORM |
| TM-014 | Sanitization boundary | Public artifacts disclose tenant, user, secret, prompt, or private trace. | Redaction profiles, independent public hashes, leak tests | Publish blocked on any prohibited pattern |
| TM-015 | Operational telemetry | Raw content creates privacy or prompt-leak exposure. | AU-12.1 and AI-MO-01.1 schema denylist | Controlled evaluation content stays separate |
| TM-016 | Reviewer workflow | AI suggestion is treated as authoritative or closes a finding. | Human-only command authorization and append-only decision reason | Solo-persona independence limitation |
| TM-017 | Monitoring pipeline | Diagnostic removal or KQL failure hides abuse. | AU-2.1, SI-4.1, Sentinel health rule, SCN-003 | Missing data becomes not concluded |
| TM-018 | Scenario campaign | A fixture reaches a real target or remains deployed. | Allowlisted group, expiry tags, prohibitions, cleanup verification | Campaign stops if cleanup cannot be proven |

## Abuse-case assumptions

There is no malware, credential attack, external target, real PII, anonymously accessible data, or attached Internet-exposed host. The only consequential tool creates a disposable synthetic record. A failure outside those boundaries invalidates the scenario and triggers cleanup and incident review.
