#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <infra/parameters/*.bicepparam>" >&2
  exit 64
fi

parameter_file=$1
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)

if [[ ! -f "$parameter_file" ]]; then
  echo "parameter file not found: $parameter_file" >&2
  exit 66
fi

case "$(cd "$(dirname "$parameter_file")" && pwd)/$(basename "$parameter_file")" in
  "$repo_root"/infra/parameters/*.bicepparam) ;;
  *) echo "parameter file must be under infra/parameters" >&2; exit 65 ;;
esac

if rg -q 'REPLACE_ME@example\.com|REPLACE_WITH_RFC3339_UTC|SET[_-]?ME' "$parameter_file"; then
  echo "preflight rejected unresolved parameter placeholders" >&2
  exit 65
fi

if rg -q "param enableModelDeployment = true" "$parameter_file"; then
  if [[ -z "${AICA_FOUNDRY_QUOTA_EVIDENCE:-}" || ! -f "${AICA_FOUNDRY_QUOTA_EVIDENCE}" ]]; then
    echo "model deployment requires AICA_FOUNDRY_QUOTA_EVIDENCE pointing to MCP quota evidence" >&2
    exit 65
  fi
  if ! rg -q '"deployableQuota"[[:space:]]*:[[:space:]]*[1-9]' "$AICA_FOUNDRY_QUOTA_EVIDENCE"; then
    echo "quota evidence does not contain a positive deployableQuota" >&2
    exit 65
  fi
fi

if rg -q "param enableWorkloads = true" "$parameter_file"; then
  foundry_selected=false
  phi_selected=false
  rg -q "param enableModelDeployment = true" "$parameter_file" && foundry_selected=true
  rg -q "param enablePhiFallback = true" "$parameter_file" && phi_selected=true
  if [[ "$foundry_selected" == "$phi_selected" ]]; then
    echo "workload deployment requires exactly one live model path: Foundry or Phi" >&2
    exit 65
  fi
  corpus_receipt=${AICA_CORPUS_MATERIALIZATION_RECEIPT:-}
  if [[ ! -f "$corpus_receipt" ]]; then
    echo "workload deployment requires AICA_CORPUS_MATERIALIZATION_RECEIPT from the protected Azure MCP corpus upload" >&2
    exit 65
  fi
  environment_name=$(sed -n "s/^[[:space:]]*param environment = '\([^']*\)'.*/\1/p" "$parameter_file")
  corpus_receipt_args=(
    verify-receipt
    "$corpus_receipt"
    --expected-environment
    "$environment_name"
  )
  if [[ -n "${AZURE_SUBSCRIPTION_ID:-}" ]]; then
    corpus_receipt_args+=(--expected-subscription-id "$AZURE_SUBSCRIPTION_ID")
  fi
  python3 "$repo_root/scripts/azure/prepare-corpus-handoff.py" "${corpus_receipt_args[@]}"
  for image_parameter in assuranceApiImage assuranceJobImage consoleUiImage assistantUiImage; do
    if ! rg -q "param ${image_parameter} = '[^']+@sha256:[0-9a-fA-F]{64}'" "$parameter_file"; then
      echo "workload deployment requires immutable ${image_parameter} with an @sha256 digest" >&2
      exit 65
    fi
  done
  supply_chain_image_set=${AICA_SUPPLY_CHAIN_IMAGE_SET:-}
  if [[ ! -f "$supply_chain_image_set" ]]; then
    echo "workload deployment requires AICA_SUPPLY_CHAIN_IMAGE_SET from the successful exact-commit supply-chain run" >&2
    exit 65
  fi
  python3 "$repo_root/scripts/azure/prepare-image-handoff.py" \
    verify-receipt "$parameter_file" "$supply_chain_image_set"
  for client_parameter in assuranceApiClientId assistantClientId; do
    if ! rg -q "param ${client_parameter} = '[0-9a-fA-F-]{36}'" "$parameter_file"; then
      echo "workload deployment requires a UUID ${client_parameter}" >&2
      exit 65
    fi
  done
  assurance_client_id=$(sed -n "s/^[[:space:]]*param assuranceApiClientId = '\([^']*\)'.*/\1/p" "$parameter_file")
  assistant_client_id=$(sed -n "s/^[[:space:]]*param assistantClientId = '\([^']*\)'.*/\1/p" "$parameter_file")
  entra_receipt=${AICA_ENTRA_MATERIALIZATION_RECEIPT:-}
  if [[ ! -f "$entra_receipt" ]]; then
    echo "workload deployment requires AICA_ENTRA_MATERIALIZATION_RECEIPT from protected Azure MCP directory readback" >&2
    exit 65
  fi
  entra_receipt_args=(
    verify-receipt
    "$entra_receipt"
    --expected-environment
    "$environment_name"
    --expected-assurance-client-id
    "$assurance_client_id"
    --expected-assistant-client-id
    "$assistant_client_id"
  )
  if [[ -n "${AZURE_TENANT_ID:-}" ]]; then
    entra_receipt_args+=(--expected-tenant-id "$AZURE_TENANT_ID")
  fi
  python3 "$repo_root/scripts/azure/prepare-entra-handoff.py" "${entra_receipt_args[@]}"
  if ! rg -q "param githubRepository = '[^/']+/[^/']+'" "$parameter_file"; then
    echo "workload deployment requires githubRepository in owner/name form" >&2
    exit 65
  fi
  for github_id_parameter in githubAppId githubAppInstallationId; do
    if ! rg -q "param ${github_id_parameter} = '[1-9][0-9]*'" "$parameter_file"; then
      echo "workload deployment requires numeric ${github_id_parameter}" >&2
      exit 65
    fi
  done
  if ! rg -q "param assessedGitCommit = '[0-9a-fA-F]{40}'" "$parameter_file"; then
    echo "workload deployment requires assessedGitCommit as the exact 40-hex source commit" >&2
    exit 65
  fi
  if ! rg -q "param enableSentinelContent = true" "$parameter_file"; then
    echo "workloads require Sentinel content so run/tool security events have a destination" >&2
    exit 65
  fi
  if ! rg -q "param trustedSigningKeyFingerprints = '[0-9a-fA-F]{64}(,[0-9a-fA-F]{64})*'" "$parameter_file"; then
    echo "workload deployment requires the trusted Key Vault signing-key JWK fingerprint" >&2
    exit 65
  fi
  pseudonymization_secret=${AICA_PSEUDONYMIZATION_SECRET:-}
  if [[ ${#pseudonymization_secret} -lt 32 ]]; then
    echo "workload deployment requires AICA_PSEUDONYMIZATION_SECRET with at least 32 characters; it is never written to handoff artifacts" >&2
    exit 65
  fi
  github_app_private_key=${AICA_GITHUB_APP_PRIVATE_KEY:-}
  if [[ ${#github_app_private_key} -lt 512 ]] || {
    [[ "$github_app_private_key" != *"-----BEGIN PRIVATE KEY-----"* ]] &&
    [[ "$github_app_private_key" != *"-----BEGIN RSA PRIVATE KEY-----"* ]];
  } || {
    [[ "$github_app_private_key" != *"-----END PRIVATE KEY-----"* ]] &&
    [[ "$github_app_private_key" != *"-----END RSA PRIVATE KEY-----"* ]];
  }; then
    echo "workload deployment requires AICA_GITHUB_APP_PRIVATE_KEY containing a complete RSA PEM; it is never written to handoff artifacts" >&2
    exit 65
  fi
fi

if rg -q "param enablePhiFallback = true" "$parameter_file"; then
  if ! rg -q "param enableWorkloads = true" "$parameter_file"; then
    echo "Phi fallback requires enableWorkloads=true" >&2
    exit 65
  fi
  if rg -q "param enableModelDeployment = true" "$parameter_file"; then
    echo "Phi fallback and a Foundry model deployment are mutually exclusive release paths" >&2
    exit 65
  fi
  if ! rg -q "param phiImage = '[^']+@sha256:[0-9a-fA-F]{64}'" "$parameter_file"; then
    echo "Phi fallback requires an immutable phiImage with an @sha256 digest" >&2
    exit 65
  fi
  if [[ -z "${AICA_FOUNDRY_QUOTA_EVIDENCE:-}" || ! -f "${AICA_FOUNDRY_QUOTA_EVIDENCE}" ]]; then
    echo "Phi fallback requires AICA_FOUNDRY_QUOTA_EVIDENCE from an MCP quota check" >&2
    exit 65
  fi
  if ! rg -q '"deployableQuota"[[:space:]]*:[[:space:]]*0([,}[:space:]]|$)' "$AICA_FOUNDRY_QUOTA_EVIDENCE"; then
    echo "Phi fallback evidence must record deployableQuota as zero" >&2
    exit 65
  fi
fi

if rg -q "param fixtureScenarioId = '[^']+'" "$parameter_file"; then
  expires_on=$(sed -n "s/^[[:space:]]*param fixtureExpiresOn = '\([^']*\)'.*/\1/p" "$parameter_file")
  if [[ ! "$expires_on" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ ]]; then
    echo "active fixtures require an RFC3339 UTC expiresOn value" >&2
    exit 65
  fi
  python3 - "$expires_on" <<'PY'
from datetime import datetime, timezone, timedelta
import sys

expiry = datetime.fromisoformat(sys.argv[1].replace("Z", "+00:00"))
now = datetime.now(timezone.utc)
if not now < expiry <= now + timedelta(hours=24):
    raise SystemExit("fixture expiry must be in the future and no more than 24 hours away")
PY
fi

bicep_bin=${BICEP_BIN:-}
if [[ -z "$bicep_bin" ]]; then
  bicep_bin=$(command -v bicep || true)
fi

if [[ -n "$bicep_bin" ]]; then
  output=$(mktemp "${TMPDIR:-/tmp}/aica-main.XXXXXX.json")
  trap 'rm -f "$output"' EXIT
  "$bicep_bin" build "$repo_root/infra/main.bicep" --outfile "$output"
  "$bicep_bin" build-params "$parameter_file" --stdout >/dev/null
  echo "Bicep compile: PASS"
else
  echo "Bicep CLI unavailable; structural checks passed, compile deferred to CI/MCP handoff" >&2
fi

echo "Preflight: PASS"
echo "Next: run Azure MCP subscription What-If and save the complete JSON result as private evidence."
