# Risk-control matrix

Profile: AICA-STUDENT-1.0  
As of: 2026-06-08  
Purpose: continuous internal assurance and audit-readiness simulation—not certification, attestation, or independent audit.

`A` = deterministic automated test, `H` = hybrid examine/test, `M` = manual examine/interview. An automated pass supports an objective; it does not by itself prove the whole control effective.

| Control | Tailored objectives | Method | Owner | Principal evidence | RUN-001 | RUN-002 |
|---|---|---|---|---|---|---|
| AC-2 | AC-2.1, AC-2.2 | H, M | Identity Owner | RBAC inventory; access-review workpaper | Effective | Effective |
| AC-3 | AC-3.1, AC-3.2 | A, H | API Owner | 403 negatives; command contract | Effective | Effective |
| AC-6 | AC-6.1, AC-6.2 | A, M | Cloud Owner | Effective assignments; need attestation | Effective | Effective |
| IA-2 | IA-2.1 | A | Identity Owner | Entra settings; unauthenticated negative | N/A in public mode | N/A in public mode |
| IA-5 | IA-5.1 | H | DevSecOps Owner | OIDC/managed identity; secret scan | Effective | Effective |
| AU-2 | AU-2.1, AU-2.2 | A, H | Monitoring Owner | Diagnostic settings; event taxonomy review | Effective | Effective |
| AU-6 | AU-6.1 | M | Simulated Security Reviewer | Weekly monitoring workpaper | Effective | Effective |
| AU-12 | AU-12.1 | A | Application Owner | Telemetry schema and redaction tests | Effective | Effective |
| CA-7 | CA-7.1, CA-7.2 | A, H | Assurance Owner | Run manifests; negative evidence tests; coverage review | Effective | Effective |
| CM-2 | CM-2.1 | A | Cloud Owner | Bicep digest; What-If; live inventory | Effective | Effective |
| CM-3 | CM-3.1, CM-3.2 | A, M | DevSecOps Owner | PR/commit/image/Activity provenance; change sample | Effective | Effective |
| CM-6 | CM-6.1 | A | Cloud Owner | Normalized Azure configuration and rules | Effective | Effective |
| CP-9 | CP-9.1 | A | Evidence Custodian | Blob protection export; restore digest | Effective | Effective |
| IR-4 | IR-4.1 | M | Incident Lead | Cloud/AI tabletop and playbooks | Effective with limitation | Effective with limitation |
| RA-3 | RA-3.1 | M | Risk Owner | Risk register and review decisions | Effective with limitation | Effective with limitation |
| RA-5 | RA-5.1 | A | DevSecOps Owner | SBOM; dependency/image scan; gate | Effective | Effective |
| SA-11 | SA-11.1, SA-11.2 | A, H | Application Owner | CI manifest; coverage review | Effective | Effective |
| SC-7 | SC-7.1, SC-7.2 | A, M | Cloud Owner | Network rules/attachments; endpoint exception | Ineffective | Effective with EXC-001 |
| SC-8 | SC-8.1 | A | Cloud Owner | TLS probes; secure-transfer settings | Effective | Effective |
| SI-4 | SI-4.1, SI-4.2 | A, H | Monitoring Owner | Diagnostic/KQL freshness; Sentinel rule tests | Not concluded | Effective |
| AI-GV-01 | AI-GV-01.1 | H | AI System Owner | Policy/UI assertions; owner review | Effective with limitation | Effective with limitation |
| AI-DP-01 | AI-DP-01.1 | A | Data Steward | Corpus manifest; hashes; behavioral cases | Ineffective | Effective with limitation |
| AI-AC-01 | AI-AC-01.1 | A | Application Owner | Authorization and confirmation traces | Ineffective | Effective |
| AI-TE-01 | AI-TE-01.1 | A | AI Evaluation Owner | Configuration digests; fixed gate artifact | Ineffective | Effective |
| AI-MO-01 | AI-MO-01.1, AI-MO-01.2 | A, M | Monitoring Owner | AI event schema/queries; tabletop | Partially effective | Effective with limitation |

## Coverage totals

- 25 controls: 20 NIST SP 800-53 selections and 5 project AI controls.
- 35 objectives: 19 automated, 8 hybrid, and 8 manual.
- RUN-001: 28 PASS, 4 FAIL, 1 ERROR, 1 NOT_RUN, 1 NOT_APPLICABLE.
- RUN-002: 33 PASS and 2 NOT_APPLICABLE; four findings closed only after fresh evidence.

Machine-readable definitions are in `assurance/controls/control-profile.json`; record-level evidence and rationales are in `data/sample-runs`.
