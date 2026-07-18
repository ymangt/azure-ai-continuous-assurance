# Safe scenario runbook

## Execution classes and current truth state

The eight specifications share one lifecycle contract but do not share one operator path:

- `SCN-002` and `SCN-003` are the only deployable fixture-plane handoffs accepted by
  `assure fixture run` and the protected `fixture-handoff.yml` workflow. Their checked-in
  campaign proof is a controlled ARM transcript, not a live Azure run.
- `SCN-004` and `SCN-005` execute only as inert OPA/Conftest fixtures. They must never be
  queued for Azure deployment.
- `SCN-006` and `SCN-007` execute through the controlled `PolicyAssistantService` behavioral
  runtime. Replay proves the application/evaluator path, not live model quality.
- `SCN-001` and the AI scenarios with signed lifecycle references reuse the verified sanitized
  sample packages for accepted reviewer-closure semantics. A signed sample is not evidence that
  the corresponding Azure campaign ran in this tenant.

Run the complete controlled campaign gate with the pinned Conftest executable:

```bash
PYTHONPATH=src .venv/bin/python assurance/scripts/validate_scenarios.py \
  --conftest /tmp/conftest
```

The checked-in `data/scenario-campaigns/controlled-execution.json` explicitly sets
`azure_live_evidence_checked_in=false` for every campaign. `SCN-001`, `SCN-002`, `SCN-003`,
`SCN-006`, and `SCN-007` remain Azure-live release gates and must be rerun through the approved
Azure MCP workflow before a release or demonstration claims live execution.

## Azure-live fixture procedure

1. Select one versioned `SCN-*` specification and protected environment approval.
2. Verify the scenario allowlist, synthetic classification, estimated cost, expiry, and prohibited actions.
3. Query for existing scenario-tagged resources; stop if leftovers exist.
4. Capture the clean baseline and require expected PASS before injection.
5. Inject exactly one condition through a fixture template or controlled synthetic input.
6. Run collection with the Azure campaign profile, which includes `rg-aica-fixture-eus2`, and verify the expected objective result, observation, finding, risk, and evidence links.
7. Remediate through code and record review, commit, What-If where applicable, and deployment evidence.
8. Create a separate retest run and require the declared expected outcome.
9. Clean up unconditionally, even when collection, evaluation, or retest fails.
10. Query the allowlisted group and dependent assignment inventory. The scenario is incomplete until zero scenario-tagged resources remain.

The clean baseline and post-cleanup retest use the same scoped collector path as the injected run. Do not substitute an offline fixture or remove the fixture resource group from the profile between phases.

Stop immediately if a fixture becomes attached, Internet-exposed with compute behind it, processes real data, targets an external system, creates credentials, exceeds its allowlist, or cannot be deleted. Preserve evidence and follow the incident procedure.
