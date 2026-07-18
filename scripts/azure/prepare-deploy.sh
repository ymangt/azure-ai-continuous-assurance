#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 3 || $# -gt 4 ]]; then
  echo "usage: $0 <compiled-template.json> <parameters.json|bicepparam> <approved-what-if.json> [--allow-model-after-quota|--allow-phi-after-zero-quota]" >&2
  exit 64
fi

template=$1
parameters=$2
what_if=$3
gate_flag=${4:-}
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)

for file in "$template" "$parameters" "$what_if"; do
  [[ -f "$file" ]] || { echo "missing input: $file" >&2; exit 66; }
done

review_args=("$what_if")
quota_evidence=''
if [[ -n "$gate_flag" ]]; then
  case "$gate_flag" in
    --allow-model-after-quota|--allow-phi-after-zero-quota) ;;
    *) echo "unknown option: $gate_flag" >&2; exit 64 ;;
  esac
  quota_evidence=${AICA_FOUNDRY_QUOTA_EVIDENCE:-}
  [[ -f "$quota_evidence" ]] || { echo "AICA_FOUNDRY_QUOTA_EVIDENCE is required" >&2; exit 65; }
  if [[ "$gate_flag" == '--allow-model-after-quota' ]]; then
    rg -q '"deployableQuota"[[:space:]]*:[[:space:]]*[1-9]' "$quota_evidence" || { echo "quota evidence is not positive" >&2; exit 65; }
    review_args+=(--allow-model-deployment)
  else
    rg -q '"deployableQuota"[[:space:]]*:[[:space:]]*0([,}[:space:]]|$)' "$quota_evidence" || { echo "quota evidence does not record zero" >&2; exit 65; }
    review_args+=(--allow-phi-fallback)
  fi
fi

python3 "$repo_root/scripts/azure/review-what-if.py" "${review_args[@]}"

template_sha=$(shasum -a 256 "$template" | awk '{print $1}')
parameter_sha=$(shasum -a 256 "$parameters" | awk '{print $1}')
what_if_sha=$(shasum -a 256 "$what_if" | awk '{print $1}')
quota_sha=''
if [[ -n "$quota_evidence" ]]; then
  quota_sha=$(shasum -a 256 "$quota_evidence" | awk '{print $1}')
fi

python3 - "$template" "$parameters" "$what_if" "$template_sha" "$parameter_sha" "$what_if_sha" "$quota_evidence" "$quota_sha" "$gate_flag" <<'PY'
import json
import sys

print(json.dumps({
    "operator": "Azure MCP only",
    "operation": "subscription deployment create/update",
    "template": sys.argv[1],
    "parameters": sys.argv[2],
    "approvedWhatIf": sys.argv[3],
    "templateSha256": sys.argv[4],
    "parametersSha256": sys.argv[5],
    "whatIfSha256": sys.argv[6],
    "quotaEvidence": sys.argv[7] or None,
    "quotaEvidenceSha256": sys.argv[8] or None,
    "quotaGate": sys.argv[9] or None,
    "secureParameters": [
        "pseudonymizationSecret (required separately when enableWorkloads=true; never serialize it)",
        "githubAppPrivateKey (required separately when enableWorkloads=true; never serialize it)"
    ],
    "postDeploy": [
        "monitor deployment through MCP",
        "verify Resource Graph, RBAC, Policy, Monitor, service configuration",
        "store query digests and sanitized summaries as assessment evidence",
    ],
    "note": "This wrapper intentionally performs no Azure mutation.",
}, indent=2))
PY
