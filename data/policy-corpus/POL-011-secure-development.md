# Secure Development Standard

- Policy ID: POL-011
- Owner: Product Security
- Classification: Internal (synthetic)
- Version: 2.8
- Effective: 2026-02-20

## 1. Required gates

Pull requests run unit, contract, negative, fault, authorization, redaction, secret, dependency, image, IaC, KQL, behavioral, and public-boundary tests appropriate to the change.

## 2. Supply chain

GitHub Actions use full commit SHAs and deployed images use immutable digests. Builds produce an SBOM and vulnerability report. Unresolved critical vulnerabilities block release.

## 3. Review

Security-sensitive changes require review of trust boundaries, failure behavior, data classification, logging, and rollback—not only code correctness.
