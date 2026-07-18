# AI usage and verification disclosure

AI systems assisted with implementation of this repository. This disclosure is part of the assurance record, not a claim that AI output is authoritative.

## Where AI was used

- Interpreting the decision-complete build plan and scaffolding code, schemas, OSCAL documents, Bicep-related documentation, tests, and sample records.
- Drafting the fictional Northstar policy corpus, adversarial scenarios, behavioral cases, framework crosswalk rationales, workpapers, and operating procedures.
- Drafting candidate evidence-to-objective benchmark labels and candidate reviewer dispositions.
- Researching primary NIST, Microsoft, OWASP, Azure pricing, and OSCAL references.
- Finding consistency defects such as mismatched objective IDs, placeholder configuration digests, non-reproducible benchmark metrics, stale package manifests, and missing replay outcomes.

No real customer, employee, tenant, incident, ticket, prompt, response, secret, or personal data was provided to create the public sample artifacts. Organizations, users, decisions, resource identifiers, and scenario events are synthetic or sanitized.

## Where AI is not authoritative

AI may not:

- determine a production control verdict;
- decide evidence sufficiency without reviewer acceptance;
- declare compliance, certification, authorization, or audit completion;
- approve an exception or accept risk;
- close or reopen a finding;
- authorize a deployment or consequential tool action;
- replace live Azure verification, official schema validation, or practitioner judgment.

AI-generated mappings and narratives must enter the workflow as `SUGGESTED`. A reviewer records acceptance or rejection, rationale, timestamp, artifact hash, and version. A code change or AI statement never replaces fresh retest evidence.

## Verification performed on checked-in artifacts

The following deterministic checks are executable:

```bash
PYTHONPATH=src .venv/bin/python assurance/scripts/score_mapping_benchmark.py
PYTHONPATH=src .venv/bin/python assurance/scripts/validate_oscal.py
PYTHONPATH=src .venv/bin/python assurance/scripts/validate_artifacts.py
```

They verify JSON parsing, record counts, objective method counts, replay outcomes, benchmark confusion-matrix metrics, trace references, strict API package models, public-boundary patterns, and local-only ES256 sample signatures/artifact hashes. The checked-in sample manifests use a `local://` CI/sample key and do not imply Azure Key Vault provenance.

All nine OSCAL documents validate against the bundled official NIST OSCAL v1.2.2 complete JSON schema. The schema SHA-256 is pinned by the validator; a mismatch fails closed. `OSCAL_SCHEMA_DIR` or `--schema-dir` can independently cross-check another official schema bundle.

## Required human and live-environment review before a portfolio claim

1. Review every benchmark label and rationale. The current 72 labels are AI-assisted, human-review-ready gold-label candidates; they must not be described as independently human-labeled until a person records that review.
2. Review the 50 expected behavioral outcomes and execute them against the selected live Azure-hosted model. Replay results test the pipeline and public UI only.
3. Independently cross-check the bundled official OSCAL v1.2.2 schema checksum and validation result during release review.
4. Verify NIST, Microsoft, OWASP, pricing, quota, and service references at release time.
5. Use Azure MCP to verify the enabled subscription, region policy, quota, What-If, deployment, configuration, cost, and cleanup.
6. Sign live manifests with a non-exportable Key Vault P-256 key and verify the exact public key version and thumbprint offline.
7. Obtain practitioner or professor feedback where possible and preserve the response as attributed review evidence.

The project must publish lower-than-target results and unresolved limitations honestly rather than hiding or rewording them as passes.
