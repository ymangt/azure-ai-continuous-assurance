# Microsoft Sentinel integration

The content in this directory targets the existing `law-sc200-sentinel-lab` workspace. The Bicep module creates two bounded custom tables and a Direct data collection rule, then deploys four scheduled analytics rules and one workbook.

| Rule | Data | Intent |
|---|---|---|
| Risky RBAC or NSG change | `AzureActivity` | Review privileged role and broad-ingress control-plane changes, including the legacy unattached RDP NSG story |
| Diagnostic setting deletion | `AzureActivity` | Detect loss of evidence-producing telemetry |
| Failed or stale assurance run | `AicaAssurance_CL` | Alert on explicit failure/error and no successful scheduled run within 26 hours |
| Repeated rejected AI tool escalation | `AicaToolSecurity_CL` | Alert after three rejected consequential-tool attempts in one pseudonymous session within five minutes |

`AicaToolSecurity_CL` retains its deployment-compatible name but stores the versioned content-minimized record defined by `schemas/operational-telemetry.schema.json` for every assistant interaction. Its DCR allowlist includes correlation/evaluation IDs, pseudonymous subject/session, model and version, retrieval document IDs/classifications, latency and token counts, status, guardrail outcomes, and explicit tool authorization/confirmation/result state. `EventName` is `assistant_interaction` or `tool_authorization`; the escalation analytic filters the latter. Prompts, responses, citation excerpts, retrieved content, evidence bodies, access/confirmation tokens, tenant IDs, direct user identities, and IP addresses are not accepted.

The Direct DCR endpoint is public by design for the student-cost profile and requires Entra authorization. The collector and assistant identities receive Monitoring Metrics Publisher only on that DCR. The content identity receives Microsoft Sentinel Contributor only on the existing Sentinel resource group. KQL fixture files contain synthetic records for deterministic schema/trigger testing; they are not ingested automatically.

After deployment through MCP, validate each query in the workspace, ingest one synthetic event set using the Logs Ingestion API, confirm the expected alerts, and run a clean-data quietness test. Store only query digests and sanitized result summaries in public assessment packages.
