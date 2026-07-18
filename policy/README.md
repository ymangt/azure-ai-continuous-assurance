# IaC policy fixtures

`azure_iac.rego` evaluates compiled ARM-shaped JSON with Conftest/OPA. It blocks anonymous or shared-key storage, missing Blob recoverability, weak Key Vault/Foundry authentication, non-scale-to-zero Container Apps, floating app/job images, jobs above the 900-second cost ceiling, inline Container Apps secrets, prohibited fixture types/tags, privileged control-plane role assignments, and any expansion of the command worker's exact two-action job-starter role.

The public endpoint checks are warnings because the student-cost architecture deliberately accepts Entra/RBAC-protected public Azure service endpoints. `public-storage.json` is an IaC-only negative fixture and must never be deployed. The expected result is zero denials for `compliant.json` and one or more denials for every other fixture.

`scripts/azure/validate-dockerfiles.py` is the source-image companion gate. CI runs it over every `Dockerfile` and `*.Dockerfile`, rejecting any `FROM` stage whose registry reference does not include a full `@sha256:<64-hex>` digest.
