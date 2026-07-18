# Logging and Monitoring Standard

- Policy ID: POL-009
- Owner: Security Monitoring
- Classification: Internal (synthetic)
- Version: 2.1
- Effective: 2026-02-15

## 1. Required events

Record authentication outcome, authorization denial, administrative configuration change, assurance-run state, collection failure, evidence freshness, model/configuration version, guardrail outcome, retrieval IDs, tool authorization, confirmation state, and tool result.

## 2. Privacy

Use pseudonymous actor and session IDs. Do not place tokens, secrets, raw prompts, raw responses, or full resource identifiers in routine logs.

## 3. Review

Review failed or stale assurance runs, risky role or NSG changes, diagnostic-setting deletion, and repeated rejected tool escalation at least weekly.
