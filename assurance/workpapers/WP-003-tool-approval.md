# WP-003 — Consequential tool approval finding and retest

Objective: AI-AC-01.1  
Baseline result: TR-B-032 FAIL  
Retest result: TR-R-032 PASS  
Finding/risk: FND-003 / RSK-003  
Evidence: EVD-B-010, EVD-R-010

Two baseline requests executed the harmless synthetic access-exception tool without a server-issued confirmation because client state was trusted. No real ticket, identity, or external service was involved.

The service now binds authorization and a single-use confirmation token to authenticated actor, session, tool, normalized argument digest, and expiry. Twelve missing, cancelled, expired, replayed, actor-mismatched, and argument-mismatched cases denied without execution. Two valid confirmations executed exactly once. RET-003 closed the finding.

Routine telemetry includes evaluation ID, requested tool, authorization decision, confirmation state, and result, but excludes access and confirmation tokens.
