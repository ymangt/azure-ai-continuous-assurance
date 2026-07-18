# WP-005 — Unauthorized collection and renewed conclusion

Objective: SI-4.1  
Baseline result: TR-B-028 ERROR  
Retest result: TR-R-028 PASS  
Evidence: EVD-B-003, EVD-R-001, EVD-R-003

The baseline collector received HTTP 403 for one required Key Vault diagnostic-setting read. The evaluator recorded ERROR, marked SI-4 not concluded, and did not infer a pass from other resources.

The collector's read scope was corrected. Fresh evidence then confirmed every required destination and a negative write test returned 403, preserving least privilege. RET-005 records a new conclusion without overwriting the original error. No finding was opened because the condition was an assessment limitation rather than evidence that monitoring configuration itself was absent.
