# Change Management Policy

- Policy ID: POL-007
- Owner: Engineering Enablement
- Classification: Internal (synthetic)
- Version: 3.0
- Effective: 2026-02-20

## 1. Standard changes

Material code, infrastructure, policy, evaluation, model, prompt, retrieval, guardrail, and tool changes require a tracked request, peer review, passing gates, rollback plan, and immutable artifact digest.

## 2. Azure deployment

Bicep is the source of truth. A compiled template and ARM What-If are reviewed before deployment. Unexpected deletes, broad role grants, public exposure, and out-of-scope resources block deployment.

## 3. Emergency changes

An emergency change must be documented immediately, reviewed within one business day, and followed by a clean assessment and rollback-readiness check.
