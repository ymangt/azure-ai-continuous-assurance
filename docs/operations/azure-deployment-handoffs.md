# Azure MCP deployment handoffs

This runbook covers the signed-image, data, and directory prerequisites for the Bicep workloads.
They are external gates, not evidence that Azure is already deployed. Only Azure MCP may perform
Azure or directory mutations. The Azure CLI examples sometimes shown in Microsoft documentation
are not an approved substitute for this project.

## 1. Bind the exact-commit signed image set

1. Select one completed, successful `supply-chain.yml` run whose `head_sha` is the exact handoff
   checkout commit. The run must contain exactly one unexpired artifact for each component:
   `sbom-api-<commit>`, `sbom-job-<commit>`, `sbom-apps-console-<commit>`, and
   `sbom-apps-policy-assistant-<commit>`.
2. Dispatch `azure-handoff.yml` with that numeric run ID as `supply_chain_run_id`. For each
   artifact the workflow verifies GitHub's archive SHA-256 before extraction, permits only the
   expected SBOM and `image-<component>.json`, and requires the record's exact source commit,
   Dockerfile, component-specific GHCR repository, signature status, provenance-attestation
   status, and internally matching image digest.
3. The workflow replaces only image/commit placeholders (or accepts already identical values),
   then emits canonical `supply-chain-image-set.json`. `preflight.sh` verifies that receipt against
   the compiled parameter file. A missing component, mixed commit, mutable tag, conflicting
   parameter, duplicate record, unsigned image, or unattested image stops the workload handoff.
   The safe normalized receipt and its SHA-256 are included in the handoff; no registry credential
   or private evidence is present.
4. Submit the exact compiled template, parameters, image-set receipt, and checksums to Azure MCP
   What-If/deployment. Bicep derives the API, Policy Assistant UI, and assessment-job digest values
   from those immutable image references. Both the Policy Assistant API and assessor receive the
   same source commit plus three digests, and both resources carry the same provenance tags. The
   `/healthz` release digest covers this deployment block but never discloses its values.
5. After deployment, use Azure MCP read-only resource and revision queries to read the active
   Policy Assistant revision, its 100%-traffic API/UI image references, the assessment-job image,
   and both resources' four provenance tags. Preserve the complete MCP output privately, create a
   canonical receipt conforming to `schemas/deployment-image-readback-receipt.schema.json`, and
   verify it against the exact handoff image set:

   ```bash
   python3 scripts/azure/prepare-image-handoff.py verify-deployment-receipt \
     /reviewed/supply-chain-image-set.json \
     /private/deployment-image-readback-receipt.json \
     --expected-subscription-id 00000000-0000-0000-0000-000000000000
   ```

   This readback is mandatory because a running container cannot independently discover its own
   Container Apps image reference. Until Azure MCP returns and verifies those actual values, the
   repository claims only an intended deployment, not a live verified one. Populate the protected
   assessment image-digest variables only from this verified receipt.

## 2. Materialize the production corpus

1. Run the protected `corpus-handoff.yml` workflow or create the same deterministic bundle locally:

   ```bash
   python3 scripts/azure/prepare-corpus-handoff.py prepare /tmp/corpus-handoff
   python3 scripts/azure/prepare-corpus-handoff.py verify /tmp/corpus-handoff
   ```

2. Verify `BUNDLE-SHA256` and retain the exact workflow/run binding. `handoff.json` contains the
   only accepted blob names, sizes, SHA-256 values, and local payload paths. The target is the
   foundation-created private `synthetic-corpus` container and the immutable
   `<corpus_id>/<version>` prefix compiled into the Policy Assistant workload.
3. For every payload entry, invoke Azure MCP Storage command `storage_blob_upload` with the exact
   local file, storage account, `synthetic-corpus` container, and manifested blob name. This MCP
   command is create-only. Do not overwrite an existing prefix; increment the checked-in corpus
   version for any changed content.
4. Invoke Azure MCP Storage command `storage_blob_get` first for the whole prefix and then for every
   individual blob. Fail if the prefix contains an extra/missing blob or if any returned byte count
   or content hash differs from the upload result.
5. Preserve the complete MCP requests/responses as private evidence. Create a private receipt that
   conforms to `schemas/corpus-materialization-receipt.schema.json` and records its evidence digest,
   exact list, ETags, last-modified values, content hashes, source SHA-256 values, subscription,
   environment, container URL, and successful statuses. Validate it:

   ```bash
   python3 scripts/azure/prepare-corpus-handoff.py verify-receipt \
     /private/aica-corpus-materialization-receipt.json \
     --expected-subscription-id 00000000-0000-0000-0000-000000000000 \
     --expected-environment dev
   ```

6. Keep the receipt private. Configure `AICA_CORPUS_MATERIALIZATION_RECEIPT_B64` in the protected
   `azure-deploy` environment and dispatch `azure-handoff.yml` with the SHA-256 of the original
   receipt bytes. The workflow materializes the receipt only on its ephemeral runner, and
   `preflight.sh` rejects any workload handoff without it. Only the receipt digest is uploaded.

The application is independently fail-closed: on every production start it lists the configured
prefix, downloads the complete snapshot, and verifies exact membership, classification, UTF-8,
manifest byte counts, and SHA-256 before building the FTS5 index. The materialization receipt is a
deployment gate; it does not replace that runtime verification.

## 3. Create the Entra registrations and roles

1. Deploy only the safe foundation through Azure MCP. Export the exact deployment result that
   contains `assuranceAuthRedirectUri` and `assistantAuthRedirectUri`, and preserve its SHA-256.
2. Validate the checked-in directory specification and bind the two callbacks into a deterministic
   handoff:

   ```bash
   python3 scripts/azure/prepare-entra-handoff.py validate-spec
   python3 scripts/azure/prepare-entra-handoff.py prepare \
     /private/foundation-deployment-output.json \
     --environment dev \
     /tmp/entra-mcp-handoff.json
   python3 scripts/azure/prepare-entra-handoff.py verify \
     /private/foundation-deployment-output.json \
     --environment dev \
     /tmp/entra-mcp-handoff.json
   ```

3. Through an Azure MCP directory capability, create exactly the two single-tenant
   (`AzureADMyOrg`) applications and service principals described by the handoff. Substitute each
   returned application client ID for that app's `{clientId}` placeholder, then set its identifier
   URI and authorized audience to `api://<client-id>`. Do not add a client secret. The checked-in
   Easy Auth design uses ID-token issuance, disables access-token issuance in the browser flow, and
   stores no app-registration credential in application configuration.
4. Set `appRoleAssignmentRequired=true` on both service principals. Read back all properties and
   compare the three exact, enabled, human-only role values and stable UUIDs:

   - `Assurance.Assessor`
   - `Assurance.Reviewer`
   - `Assurance.RiskApprover`

   Each app also has one exact `Application` role. Assign `Assurance.AuthorizationProbe` to the
   collector managed identity on the Console resource app so Entra will issue the probe token; the
   Console Easy Auth client allowlist then deliberately rejects it with 403. Assign
   `Assurance.WorkloadInvoker` to both assistant and collector managed identities on the assistant
   resource app so they can obtain tokens for the identity-restricted Phi endpoint. These workload
   roles are not accepted by any human command handler.
5. Assign users or groups according to `assignmentExpectations`. The assurance registration needs
   at least one assignment for every role. The assistant needs at least one Assessor; Reviewer and
   RiskApprover access there is optional and lookup-only. In this solo demonstration one human may
   operate all three explicitly labeled simulated personas; those assignments do not establish
   independent assurance. Do not assign collector, GitHub deployment, or anonymous principals.
6. Preserve private readback of application IDs, service-principal IDs, callbacks, audiences,
   assignment-required flags, roles, and assignments in an
   `entra-materialization-receipt.schema.json` receipt. Validate it with
   `prepare-entra-handoff.py verify-receipt`, base64-encode the exact bytes into protected secret
   `AICA_ENTRA_MATERIALIZATION_RECEIPT_B64`, and dispatch `azure-handoff.yml` with its SHA-256 as
   `entra_receipt_sha256`. The workload preflight binds the receipt to the exact client IDs, tenant,
   environment, roles, and assignments but uploads only its digest. Run no-role and wrong-role
   negative probes after workload deployment.

If the connected Azure MCP server has no Microsoft Entra directory mutation capability, stop with
this gate **blocked**. Do not silently use a portal, Azure CLI, or an invented client ID. Actual
tenant creation/readback remains external evidence and is intentionally absent from this repository.

Microsoft's Container Apps guidance documents the `/.auth/login/aad/callback` redirect and the ID
token setting required for Easy Auth, plus application permissions for daemon callers:
<https://learn.microsoft.com/azure/container-apps/authentication-entra>. Entra's protected-web-API
guidance explains why an assignment-required resource app must grant an application role before a
managed identity can obtain the API token:
<https://learn.microsoft.com/entra/identity-platform/scenario-protected-web-api-expose-scopes>.

## Required ordering

```text
foundation MCP deploy
  -> foundation output digest
  -> corpus MCP upload/readback + protected receipt
  -> Entra MCP create/readback + human and managed-identity app-role assignments + protected receipt
  -> successful exact-checkout supply-chain run + verified four-image handoff receipt
  -> signing/quota gates
  -> reviewed workload What-If
  -> workload MCP deployment
  -> active-revision/job image and provenance-tag MCP readback + verified private receipt
  -> deployed 401/403 and role-matrix probes
```

An empty foundation container is expected and costs almost nothing. A workload handoff is not
eligible while that container lacks the exact immutable prefix or while either Entra registration
is unverified.
