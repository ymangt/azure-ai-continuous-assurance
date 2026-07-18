# Cost model and guardrails

Budget ceiling: CAD 25 per month. This is a hard project constraint, not a service-cost guarantee. Recalculate with the Azure pricing calculator and verify the active Student subscription, region policy, quota, and current spend through Azure MCP before every deployment.

| Envelope | Monthly planning cap (CAD) | Guardrail |
|---|---:|---|
| Foundry inference or brief Phi fallback | 8 | 400 output tokens; 10 requests/user/hour; fallback warmed only for demonstrations |
| Container Apps and jobs | 3 | Consumption; `minReplicas=0`; `maxReplicas=2`; jobs only on schedule/change |
| Blob, Table, and Key Vault operations | 3 | Small corpus/evidence; LRS; lifecycle deletion; no premium tiers |
| Monitor / Log Analytics / Sentinel increment | 4 | Sampling, content minimization, 30-day operations retention, focused queries |
| Static Web Apps public console | 0 | Free plan; sanitized static snapshots only |
| Safety buffer | 7 | Covers exchange rate, free-grant exhaustion, unexpected operations, or teardown lag |
| **Total ceiling** | **25** | Stop nonessential workloads before breach |

Azure currently documents monthly Container Apps Consumption grants of 180,000 vCPU-seconds, 360,000 GiB-seconds, and two million requests, and no usage charge while an app is at zero replicas. Static Web Apps offers a Free plan for hobby/personal projects without an SLA. Blob cost varies by stored volume, operations, transfer, tier, redundancy, offer, region, and exchange rate. See [Container Apps pricing](https://azure.microsoft.com/pricing/details/container-apps/), [Static Web Apps pricing](https://azure.microsoft.com/pricing/details/app-service/static/), [Blob pricing](https://azure.microsoft.com/en-ca/pricing/details/storage/blobs/), and [Azure OpenAI/Foundry pricing](https://azure.microsoft.com/pricing/details/cognitive-services/openai-service/). These pages are the current source; numbers above are allocations, not quoted rates.

## Controls

- Budget alerts at CAD 12.50, 18.75, 22.50, and 25.00 (50/75/90/100%).
- A daily janitor deletes expired fixture resources and reports anything it could not remove.
- Every fixture requires `expiresOn`, `scenarioId`, `owner`, and `dataClassification=synthetic` tags.
- Stop the Phi fallback immediately after a demonstration. Prefer Foundry only after quota and cost smoke evidence.
- Do not enable AI Search, private endpoints, NAT Gateway, Firewall, paid Defender plans, AKS, APIM, or premium storage under this profile.
- Record estimated model, compute, storage, and telemetry cost in every run manifest. Manifest schema `1.1.0` uses `model_estimate_cad`, `compute_estimate_cad`, `storage_estimate_cad`, `telemetry_estimate_cad`, and `total_estimate_cad`; validation rejects a total that differs from the component sum.

## Stop conditions

At 75%, pause failure campaigns. At 90%, scale all optional apps to zero and remove fixtures. At 100% or on unexplained daily growth, stop the SUT, preserve sanitized evidence, investigate, and do not redeploy until the cause and revised forecast are reviewed.
