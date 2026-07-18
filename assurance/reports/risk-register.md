# Risk register

As of 2026-06-08. All data, resources, users, and events are synthetic or sanitized. Owner and approver personas are simulated by one project author.

## Scoring rubric

Likelihood and impact are each 1–5. Score = likelihood × impact. Low = 1–4, Moderate = 5–9, High = 10–16, Critical = 17–25. Inherent score precedes scenario-specific controls; residual score reflects verified controls and current treatment. Confidence is recorded separately from severity.

| ID | Cause-event-impact statement | Inherent | RUN-002 residual | Treatment | Owner | Status / next review |
|---|---|---:|---:|---|---|---|
| RSK-001 | Because a broad administrative rule existed, it could be attached or copied, causing avoidable Internet management exposure. | 12 High | 3 Low | Mitigated | Cloud Owner | Closed after RET-001; 2026-09-01 |
| RSK-002 | Because retrieved documents can contain adversarial instructions, the assistant may follow them, reducing grounded-answer integrity. | 16 High | 6 Moderate | Mitigated; monitor novel attacks | AI System Owner | Finding closed after RET-002; 2026-07-01 |
| RSK-003 | Because confirmation was trusted from client state, a crafted request could execute the synthetic tool without approval, undermining authorization integrity. | 15 High | 4 Low | Mitigated | Application Owner | Closed after RET-003; 2026-09-01 |
| RSK-004 | Because the gate accepted an artifact for a different configuration, an untested AI change could deploy and introduce regression. | 12 High | 3 Low | Mitigated | DevSecOps Owner | Closed after RET-004; 2026-09-01 |
| RSK-005 | Because managed services expose authenticated public endpoints, an attacker can reach the perimeter and attempt abuse, increasing denial-of-service or exploit exposure. | 10 High | 6 Moderate | Accept with EXC-001 | Risk Owner | Approved through 2026-09-01; monthly |

## Exception EXC-001

Private networking is excluded under the CAD 25 monthly ceiling while all data is synthetic. Compensating controls are Entra/RBAC, TLS 1.2+, rate limits, `maxReplicas=2`, no anonymous data, monitoring, and daily assessment. Expiry reopens treatment automatically. The exception does not change an observation or turn a failed test into a pass.
