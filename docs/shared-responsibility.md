# Shared responsibility statement

| Capability | Microsoft Azure | GitHub / other provider | AICA project |
|---|---|---|---|
| Physical facilities and hardware | Operates Azure physical infrastructure | Operates provider infrastructure | Does not assess provider internals |
| Managed-service platform | Patches and operates managed Azure control planes | Operates source-control/registry SaaS | Selects supported services, versions, regions, and configurations |
| Identity platform | Operates Entra and managed-identity service | Operates OIDC issuer and repository identity | Defines federated trust, RBAC, separation, access reviews, and removal |
| Network | Provides service networking and DDoS platform capabilities | Protects SaaS edge | Configures ingress, TLS, public-endpoint treatment, rate limits, and NSG rules |
| Data | Provides encryption primitives and storage durability options | Protects provider-held repository data | Classifies, minimizes, encrypts, retains, sanitizes, and deletes project data |
| Application | Provides runtime | Provides CI runners/registry | Owns code, authorization, retrieval, tool confirmation, redaction, testing, and incident handling |
| Model service | Operates Foundry service where selected | N/A | Confirms quota, selects deployment, constrains use, evaluates behavior, and provides fallback |
| Logging | Provides Monitor/Log Analytics/Sentinel capabilities | Provides audit/security events available by plan | Selects events, configures destinations, tests freshness, reviews alerts, and protects content |
| Software supply chain | N/A | Provides branch, Actions, and registry features | Pins actions/images, scans, creates SBOM/provenance, and protects branch/deployment environments |
| Assurance | Makes service evidence/configuration APIs available | Makes repository evidence available | Defines objectives, collects evidence, evaluates deterministically, reviews manually, and reports limitations |

## Separation-of-duties limitation

The bootstrap, deploy, assistant, collector, console, and Sentinel identities are technically separate. Human roles are not independent: one author simulates assessor, control owner, and risk approver. Reports must say “simulated reviewer” and may not claim independent assurance.
