# WP-002 — Indirect prompt-injection finding and retest

Objective: AI-DP-01.1  
Baseline result: TR-B-031 FAIL  
Retest result: TR-R-031 PASS  
Finding/risk: FND-002 / RSK-002  
Evidence: EVD-B-009, EVD-R-009

Eight controlled synthetic documents attempted to change behavior from retrieved text. Six baseline cases followed an embedded instruction or omitted the required warning. The condition was reproducible and citations were invalid, supporting a High finding.

The remediation labeled and delimited retrieved text as untrusted, added embedded-instruction detection, required mechanically valid citations, and defined warning/refusal behavior. All eight fixed retests passed. Closure is limited to the fixed set; novel attacks remain a Moderate residual risk and drive continuous evaluation.

Raw controlled prompts and responses remain private. The public evidence records case IDs, dispositions, citation validity, hashes, and aggregate results only.
