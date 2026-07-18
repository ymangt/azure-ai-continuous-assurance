# Assurance Evidence Standard

- Policy ID: POL-018
- Owner: Evidence Custodian
- Classification: Internal (synthetic)
- Version: 1.0
- Effective: 2026-03-15

## 1. Evidence envelope

Every item records source, scope, capture time and window, query or API digest, collector version, private URI, media type, SHA-256, Blob version, classification, freshness, and redaction state.

## 2. Conclusions

Missing, unauthorized, stale, malformed, or failed collection never produces PASS. Evidence freshness is separate from test status. Design and operating effectiveness are separate conclusions.

## 3. History and integrity

Observations, failures, decisions, remediation, and retests are append-only. New evidence creates a new run. Signed manifests are tamper-evident, not tamper-proof, because locked WORM retention is outside the removable student-cost profile.
