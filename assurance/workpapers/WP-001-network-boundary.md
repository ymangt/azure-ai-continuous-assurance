# WP-001 — Network boundary finding and retest

Objective: SC-7.1  
Baseline result: TR-B-025 FAIL  
Retest result: TR-R-025 PASS  
Finding/risk: FND-001 / RSK-001  
Evidence: EVD-B-008, EVD-R-005, EVD-R-008

## Procedure and evidence

The deterministic query selected every in-scope NSG rule and separately selected subnet and NIC associations. Baseline evidence contained source `*`, inbound Allow, TCP destination 3389, priority 100. The attachment query returned zero, making the demonstration safe but not making the configuration compliant.

The remediation removed the rule through sanitized commit `1111111`. Fresh evidence collected seven days later found no Internet RDP or SSH rule and no attachment. The reviewer closed FND-001 through RET-001 and retained the original failure and High severity in history. Residual risk fell from 8 Moderate to 3 Low.

Limitation: Sanitized evidence omits real Azure identifiers. A live package must preserve private raw query output and its independent hash.
