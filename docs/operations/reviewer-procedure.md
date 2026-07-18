# Reviewer decision procedure

1. Confirm the subject version and `expected_version`; reject stale UI state.
2. Open the objective definition, method, evidence requirement, subject selector, freshness, and limitation.
3. Trace result → evidence item → query/API digest → artifact SHA-256 and capture window.
4. Decide design and operating effectiveness separately. Do not extrapolate beyond assessed scope or sample.
5. For a finding, verify criteria, factual condition, cause evidence or explicit uncertainty, consequence, affected assets/controls, and severity rationale.
6. For a risk, require a cause-event-impact statement, 1–5 likelihood and impact, inherent/residual score, confidence, treatment, owner, and date.
7. For an exception, require approver, rationale, compensating controls, expiry, review cadence, and automatic expiry handling. An exception never changes a failed test.
8. For closure, require new evidence, a new result, remediation linkage, and explicit retest decision. A code diff alone is insufficient.
9. Accept or reject AI suggestions with rationale. AI may not conclude compliance, approve an exception, accept risk, or close a finding.
10. Append the review decision with prior state, reviewer identity, timestamp, rationale, and artifact hash. Do not update history in place.
