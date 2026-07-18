from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx
from azure.core.credentials import AccessToken

from aica.assistant.adapters import PhiModelAdapter
from aica.assistant.contracts import Citation
from aica.domain.models import Classification


class _Credential:
    def __init__(self) -> None:
        self.scopes: list[str] = []
        self.closed = False

    async def get_token(self, *scopes: str, **kwargs: Any) -> AccessToken:
        del kwargs
        self.scopes.extend(scopes)
        return AccessToken("managed-identity-token", 4_102_444_800)

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
@respx.mock
async def test_phi_adapter_uses_federated_identity_token_and_closes_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    credential = _Credential()
    monkeypatch.setattr(
        "aica.assistant.adapters.DefaultAzureCredential",
        lambda **_kwargs: credential,
    )
    route = respx.post("https://phi.test.invalid/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "Grounded answer [POL-001#POL-001-s01]"}}],
                "model": "Phi-4-mini-instruct@controlled",
                "usage": {"prompt_tokens": 20, "completion_tokens": 8},
            },
        )
    )
    adapter = PhiModelAdapter(
        "https://phi.test.invalid",
        bearer_token=None,
        token_scope="api://assistant-client/.default",
    )

    answer = await adapter.answer(
        "What does the synthetic policy require?",
        (
            Citation(
                document_id="POL-001",
                section_id="POL-001-s01",
                title="Synthetic policy",
                excerpt="Synthetic policy text.",
                classification=Classification.INTERNAL,
                score=1.0,
            ),
        ),
    )
    await adapter.close()

    assert answer.model == "Phi-4-mini-instruct"
    assert credential.scopes == ["api://assistant-client/.default"]
    assert credential.closed is True
    assert route.calls[0].request.headers["Authorization"] == "Bearer managed-identity-token"
