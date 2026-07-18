# Assessment runbook

## Before collection

1. Confirm the enabled subscription, allowed regions, profile, scope selectors, observation window, commit, collector/evaluator versions, freshness limits, and the reviewed `config/system-record.json` version.
2. Confirm the collector identity is read-only on assessed scopes and can write only its private evidence destination.
3. Validate time synchronization, storage protection, signing-key availability, budget state, fixture expiry, and the per-run model/compute/storage/telemetry CAD estimate. The four components must equal the declared total.
4. Confirm the deployed synthetic Blob corpus was uploaded through Azure MCP with the manifest
   last, then read it back and verify all 18 manifested names, byte lengths, and SHA-256 values.
   Record its ID, version, manifest digest, and document count; the live configuration digest binds
   these values.
5. For `azure-dev`, confirm `AICA_AI_EVALUATION_MODE=live`, the selected adapter is Foundry or
   Phi, the collector can invoke that model, and `AICA_DEPLOYED_CONFIGURATION_URL` is the deployed
   Policy Assistant HTTPS `/healthz` route. Verify the Azure MCP deployment-image readback receipt
   against the exact supply-chain image-set receipt, then confirm the collector receives that
   source commit and the API/UI/job image digests. Missing live prerequisites are a blocking
   collection error; replay is not an Azure release substitute.
6. For a retest, identify the immutable prior run, finding, remediation commit/PR, and exact objectives to rerun.

## Execute

1. Create a UUIDv7 run record with status RUNNING.
2. Collect every declared source. Wrap success and failure in evidence envelopes; retain API/query digest and capture window.
3. Normalize without inventing missing values. Hash private normalized evidence.
4. Apply redaction to a separate derivative and hash it independently.
5. Evaluate only deterministic rules. Missing, stale, unauthorized, malformed, or failed required evidence cannot pass.
6. Create factual observations, then reviewer-controlled findings and risks where criteria-condition-cause-consequence is supported.
7. Record design and operating effectiveness separately. Label AI mappings SUGGESTED until reviewed.
8. Generate OSCAL and human reports. Include the validated system record in the private package and its sanitized derivative, then validate contracts and the public-boundary denylist.
9. Sign the canonical manifest digest, including the four-part CAD cost breakdown, using the current non-exportable Key Vault P-256 key; record key version and JWK thumbprint.
10. Mark the run `COMPLETED`, `REVIEW_REQUIRED`, or `FAILED`. `ERROR` and unusable
    required evidence produce `FAILED`; a deterministic `FAIL` or pending manual procedure
    produces `REVIEW_REQUIRED`. Never conceal collection errors in an overall green status.
11. For a deployment/release assessment, invoke `assure collect --profile azure-dev
    --release-gate`. The command still writes and signs the authoritative package, then exits
    nonzero for `FAIL`, `ERROR`, or unusable automated evidence. Pending human review alone does
    not masquerade as an automated gate failure.

## Retest and closure

Create a new run and new evidence. Compare objective results and classify resolved, regressed, new, unchanged, stale, and errored. A reviewer may close only after a passing fresh retest references the remediation and new evidence. The original failure remains immutable.

## Publish

Publish only sanitized artifacts after leak tests for tenant/subscription IDs, identities, secrets, personal data, IP addresses, raw prompts/responses, private URIs, and sensitive traces. Public packages state the internal-readiness and independence limitations.
