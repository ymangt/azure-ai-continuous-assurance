# WP-004 — AI evaluation release-gate finding and retest

Objective: AI-TE-01.1  
Baseline result: TR-B-033 FAIL  
Retest result: TR-R-033 PASS  
Finding/risk: FND-004 / RSK-004  
Evidence: EVD-B-011, EVD-R-007, EVD-R-011

The baseline gate proved only that a passing artifact existed. It did not prove that the artifact represented the deployed prompt digest. This allowed an unevaluated configuration to proceed in the safe demonstration fixture.

The remediated gate compares model, prompt, retrieval, corpus, guardrail, and tool digests and requires a current PASS status. Exact-match evidence passed; six single-field mismatch cases failed closed. RET-004 closed the finding after the reviewer examined fresh gate traces and deployment provenance.
