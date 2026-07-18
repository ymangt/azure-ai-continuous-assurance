# GitHub App authentication for assurance collection

The live GitHub collector does not use the workflow `GITHUB_TOKEN`, a classic personal access token, or anonymous requests. It authenticates as a dedicated GitHub App installation and requests a short-lived token scoped to one repository.

## External setup gate

Before enabling either the `assessment` GitHub environment or Azure assessment workloads:

1. Create a private GitHub App owned by the repository owner. Disable webhooks because this collector polls read-only REST endpoints.
2. Grant only these repository permissions:
   - **Administration: Read-only** for branch protection, repository Actions policy, and the attached code-security configuration.
   - **Actions: Read-only** for successful workflow runs and retained artifacts.
   - **Code scanning alerts: Read-only** for the aggregate unresolved-critical count. Alert bodies are discarded before evidence is created.
3. Install the App on only the assessed repository. Do not grant account-wide repository access.
4. Record the numeric App ID and installation ID, then generate an RSA private key. Treat the downloaded PEM as a credential and never commit it.
5. For the GitHub `assessment` environment, configure variables `AICA_GITHUB_APP_ID` and `AICA_GITHUB_APP_INSTALLATION_ID`, plus secret `AICA_GITHUB_APP_PRIVATE_KEY`. The digest-pinned official `actions/create-github-app-token` step discovers the installation, verifies it matches the expected installation ID, narrows the token to the current repository and the two read permissions, masks it, and revokes it after the job.
6. For Azure workloads, set Bicep parameters `githubAppId` and `githubAppInstallationId`, and provide `githubAppPrivateKey` only as the protected Azure MCP secure parameter sourced from `AICA_GITHUB_APP_PRIVATE_KEY`. Preflight refuses a workload handoff without all three values.

GitHub App creation, installation, and environment-secret configuration are external GitHub actions; Azure MCP cannot perform them. Until this gate is complete, keep `enableWorkloads=false` and do not expect the assessment workflow to succeed.

## Runtime paths

- In GitHub Actions, the official action supplies `AICA_GITHUB_INSTALLATION_TOKEN`. The collector accepts this short-lived token and never persists it in an evidence envelope.
- In the Azure Container Apps assessment job, the collector identity reads only the versioned `aica-github-app-private-key` Key Vault secret. The Python collector creates an RS256 JWT, exchanges it at `POST /app/installations/{installation_id}/access_tokens`, and requests `repositories: [target-repository]` plus `administration: read`, `actions: read`, and `security_events: read`.
- The collector queries successful `supply-chain.yml` runs using the exact assessed commit, locally revalidates the returned `head_sha`, and requests artifacts only through that selected workflow-run ID. Each retained digest must repeat the same run ID and commit. A successful run or artifact from any other commit cannot satisfy SA-11.
- Code-scanning pagination is fail-closed. Only `unresolved_critical_alerts` and completed-page count enter the evidence envelope; alert paths, messages, authors, and other response content are never retained.
- An authentication failure creates unauthorized, unknown-freshness evidence for every declared GitHub source. It never falls back to anonymous collection and never copies GitHub's authentication response body into evidence.

Installation access tokens expire after one hour. The collector mints once immediately before collection and does not assume a fixed token length or format.

## Rotation and validation

1. Generate a second private key in the GitHub App settings.
2. Update the GitHub environment secret and redeploy the Azure workload secure parameter through Azure MCP.
3. Run a live assessment and confirm all six GitHub sources are authorized.
4. Delete the old GitHub App private key, then verify another assessment.

On every permission change, inspect the App installation and confirm it still targets only the assessed repository. GitHub requires an account administrator to approve newly requested App permissions; a run must remain fail-closed until approval is complete.

## Official references

- [Generating a JSON Web Token for a GitHub App](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-json-web-token-jwt-for-a-github-app)
- [Generating an installation access token](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-an-installation-access-token-for-a-github-app)
- [Get branch protection](https://docs.github.com/en/rest/branches/branch-protection#get-branch-protection)
- [Get GitHub Actions permissions for a repository](https://docs.github.com/en/rest/actions/permissions#get-github-actions-permissions-for-a-repository)
- [Get the code security configuration associated with a repository](https://docs.github.com/en/rest/code-security/configurations#get-the-code-security-configuration-associated-with-a-repository)
- [List workflow runs for a workflow](https://docs.github.com/en/rest/actions/workflow-runs#list-workflow-runs-for-a-workflow)
- [List workflow-run artifacts](https://docs.github.com/en/rest/actions/artifacts#list-workflow-run-artifacts)
- [List code-scanning alerts for a repository](https://docs.github.com/en/rest/code-scanning/code-scanning#list-code-scanning-alerts-for-a-repository)
- [Official create-github-app-token action](https://github.com/actions/create-github-app-token/tree/bcd2ba49218906704ab6c1aa796996da409d3eb1)
