# Third-Party Service Risk Policy

- Policy ID: POL-012
- Owner: Vendor Risk
- Classification: Internal (synthetic)
- Version: 1.5
- Effective: 2026-03-05

## 1. Scope

Review cloud, source-control, model, package, container, and monitoring providers before use. Record service purpose, data processed, authentication, regions, availability dependency, exit plan, and evidence available.

## 2. Minimum conditions

Restricted data must not enter an unapproved provider. Workload authentication uses managed identity or OIDC where supported. Dependencies and images must be version-pinned and scanned.

## 3. Changes

Material provider, model, region, or data-use changes trigger risk review and a new evaluation before deployment.
