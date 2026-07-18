# Business Continuity Standard

- Policy ID: POL-010
- Owner: Service Resilience
- Classification: Internal (synthetic)
- Version: 1.2
- Effective: 2026-03-01

## 1. Service priority

The policy assistant is a low-impact demonstration service and may be unavailable without business harm. Evidence integrity and recoverability have priority over assistant availability.

## 2. Recovery approach

Redeploy applications and infrastructure from version control, restore evidence from a tested Blob version, and use the ReplayModelAdapter when live inference is unavailable. Do not weaken authentication or release gates to restore service.

## 3. Testing

Test a small evidence-object restore weekly and a full configuration redeployment quarterly or before portfolio release.
