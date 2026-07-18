# Data Handling Standard

- Policy ID: POL-005
- Owner: Data Governance
- Classification: Internal (synthetic)
- Version: 1.7
- Effective: 2026-01-20

## 1. Storage and transfer

Restricted and Controlled Evaluation data must use approved encrypted storage, TLS 1.2 or later in transit, role-based access, and versioning when used as audit evidence. Anonymous storage access is prohibited.

## 2. Minimization

Routine AI telemetry records pseudonymous identifiers, configuration version, retrieved document IDs, outcomes, latency, tokens, guardrail state, and tool decisions. Routine logs must not contain raw prompts or responses.

## 3. Disposal

Data is deleted under POL-008 retention schedules. Scenario fixtures are deleted immediately after evidence capture and cleanup verification.
