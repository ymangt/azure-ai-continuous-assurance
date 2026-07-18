# Privileged Access Standard

- Policy ID: POL-003
- Owner: Cloud Platform
- Classification: Internal (synthetic)
- Version: 1.4
- Effective: 2026-02-10

## 1. Authentication

Privileged interactive access requires an individual Entra identity, phishing-resistant MFA where available, and an approved administrative workstation. Stored client secrets are not an approved workload authentication method.

## 2. Azure roles

Owner and User Access Administrator are restricted to bootstrap activities. Deployment identities may contribute only within approved project resource groups and may not grant roles. Collector identities are read-only on assessed scopes.

## 3. Emergency access

Emergency privilege is time-bound, logged, reviewed within one business day, and removed immediately after the approved task.
