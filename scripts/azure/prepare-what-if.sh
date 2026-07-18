#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "usage: $0 <parameters.bicepparam> [compiled-template.json]" >&2
  exit 64
fi

parameter_file=$1
compiled_template=${2:-"${TMPDIR:-/tmp}/aica-main.json"}
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
bicep_bin=${BICEP_BIN:-$(command -v bicep || true)}

if [[ -z "$bicep_bin" ]]; then
  echo "Bicep CLI is required; set BICEP_BIN to the pinned executable" >&2
  exit 69
fi

BICEP_BIN="$bicep_bin" "$repo_root/scripts/azure/preflight.sh" "$parameter_file"
"$bicep_bin" build "$repo_root/infra/main.bicep" --outfile "$compiled_template"

template_sha=$(shasum -a 256 "$compiled_template" | awk '{print $1}')
parameter_sha=$(shasum -a 256 "$parameter_file" | awk '{print $1}')

python3 - "$compiled_template" "$parameter_file" "$template_sha" "$parameter_sha" <<'PY'
import json
import sys

print(json.dumps({
    "operator": "Azure MCP",
    "operation": "subscription deployment what-if",
    "template": sys.argv[1],
    "parameters": sys.argv[2],
    "templateSha256": sys.argv[3],
    "parametersSha256": sys.argv[4],
    "secureParameters": [
        "pseudonymizationSecret (required separately when enableWorkloads=true; never serialize it)",
        "githubAppPrivateKey (required separately when enableWorkloads=true; never serialize it)"
    ],
    "location": "canadacentral",
    "resultHandling": "save full result privately, then run review-what-if.py",
}, indent=2))
PY
