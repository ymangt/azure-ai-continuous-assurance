from __future__ import annotations

import pytest

from aica.evidence.redaction import assert_public_safe, public_boundary_violations, sanitize


def test_sanitization_preserves_assessment_uuid_but_removes_sensitive_ids() -> None:
    run_id = "018f6d9a-7b10-7c01-8000-000000000001"
    tenant_id = "6b45974d-e2fe-4a1e-abad-41f2e788b9e8"
    value = {
        "run_id": run_id,
        "tenantId": tenant_id,
        "scope": f"/subscriptions/{tenant_id}/resourceGroups/private-group/providers/Test/type/x",
        "email": "reviewer@example.com",
        "safe": "synthetic",
    }
    redacted = sanitize(value)
    assert redacted["run_id"] == run_id
    assert redacted["tenantId"] == "[REDACTED]"
    assert redacted["email"] == "[REDACTED]"
    assert "private-group" not in redacted["scope"]
    assert_public_safe(str(redacted))


def test_boundary_scanner_rejects_secret_assignments() -> None:
    unsafe = "client_secret=do-not-publish"
    assert "secret_assignment" in public_boundary_violations(unsafe)
    with pytest.raises(ValueError, match="public boundary"):
        assert_public_safe(unsafe)


def test_boundary_scanner_rejects_private_evidence_uris() -> None:
    unsafe = '{"private_artifact_uri":"az://private-evidence/run/raw.json"}'
    assert "private_artifact_uri" in public_boundary_violations(unsafe)
    with pytest.raises(ValueError, match="public boundary"):
        assert_public_safe(unsafe)


def test_raw_content_keys_are_redacted_and_populated_values_are_rejected() -> None:
    sanitized = sanitize(
        {
            "rawPrompt": "private controlled prompt",
            "raw_response": "private controlled response",
        }
    )
    assert sanitized == {"rawPrompt": "[REDACTED]", "raw_response": "[REDACTED]"}
    assert_public_safe(str(sanitized))

    assert "raw_content" in public_boundary_violations(
        '{"rawPrompt":"private controlled prompt"}'
    )
    assert "raw_content" not in public_boundary_violations(
        '{"redaction":{"fields":["rawPrompt","rawResponse"]}}'
    )
