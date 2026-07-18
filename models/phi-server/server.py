"""Small OpenAI-compatible CPU server for the quota-gated Phi fallback."""

from __future__ import annotations

import asyncio
import hmac
import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import onnxruntime_genai as og
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

LOGGER = logging.getLogger("aica.phi_server")
MODEL_REPOSITORY = "microsoft/Phi-4-mini-instruct-onnx"
MODEL_REVISION = "9b9010e414c555d094141b5bb8da092ebe8f79fa"
MODEL_VARIANT = "cpu_and_mobile/cpu-int4-rtn-block-32-acc-level-4"


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=32_000)


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = "Phi-4-mini-instruct"
    messages: list[ChatMessage] = Field(min_length=1, max_length=16)
    max_tokens: int = Field(default=400, ge=1, le=400)
    temperature: float = Field(default=0, ge=0, le=1)


class PhiRuntime:
    def __init__(self, model_path: Path):
        started = time.monotonic()
        self.model = og.Model(str(model_path))
        self.tokenizer = og.Tokenizer(self.model)
        self.lock = threading.Lock()
        self.loaded_ms = round((time.monotonic() - started) * 1000)

    @staticmethod
    def _prompt(messages: list[ChatMessage]) -> str:
        parts = [f"<|{message.role}|>\n{message.content}<|end|>" for message in messages]
        parts.append("<|assistant|>\n")
        return "\n".join(parts)

    def generate(self, request: ChatCompletionRequest) -> tuple[str, int, int, int]:
        started = time.monotonic()
        prompt = self._prompt(request.messages)
        with self.lock:
            input_tokens = self.tokenizer.encode(prompt)
            stream = self.tokenizer.create_stream()
            params = og.GeneratorParams(self.model)
            params.set_search_options(
                max_length=len(input_tokens) + request.max_tokens,
                batch_size=1,
                do_sample=request.temperature > 0,
                temperature=max(request.temperature, 0.01),
            )
            generator = og.Generator(self.model, params)
            generator.append_tokens(input_tokens)
            pieces: list[str] = []
            while not generator.is_done() and len(pieces) < request.max_tokens:
                generator.generate_next_token()
                pieces.append(stream.decode(generator.get_next_tokens()[0]))
            del generator
        text = "".join(pieces).strip()
        return text, len(input_tokens), len(pieces), round((time.monotonic() - started) * 1000)


@asynccontextmanager
async def lifespan(app: FastAPI):
    model_root = Path(os.environ.get("PHI_MODEL_PATH", "/models/phi"))
    app.state.runtime = await asyncio.to_thread(PhiRuntime, model_root)
    LOGGER.info(
        "phi_model_loaded",
        extra={
            "repository": MODEL_REPOSITORY,
            "revision": MODEL_REVISION,
            "variant": MODEL_VARIANT,
            "load_ms": app.state.runtime.loaded_ms,
        },
    )
    yield


app = FastAPI(title="AICA Phi fallback", version="0.1.0", lifespan=lifespan)


def _authorize(authorization: str | None) -> None:
    expected = os.environ.get("PHI_BEARER_TOKEN")
    if not expected:
        return
    supplied = authorization.removeprefix("Bearer ") if authorization else ""
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="invalid bearer token")


@app.get("/healthz")
def health() -> dict[str, str | int]:
    return {
        "status": "healthy",
        "model": "Phi-4-mini-instruct",
        "revision": MODEL_REVISION,
        "load_ms": app.state.runtime.loaded_ms,
    }


@app.get("/provenance")
def provenance() -> dict[str, str]:
    return {
        "repository": MODEL_REPOSITORY,
        "revision": MODEL_REVISION,
        "variant": MODEL_VARIANT,
        "license": "MIT",
        "runtime": f"onnxruntime-genai/{og.__version__}",
    }


@app.post("/v1/chat/completions")
async def chat_completions(
    request: ChatCompletionRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    _authorize(authorization)
    created = int(time.time())
    text, input_tokens, output_tokens, latency_ms = await asyncio.to_thread(
        app.state.runtime.generate, request
    )
    completion_id = f"phi-{created}-{output_tokens}"
    LOGGER.info(
        "phi_completion",
        extra={
            "completion_id": completion_id,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "latency_ms": latency_ms,
        },
    )
    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": created,
        "model": f"Phi-4-mini-instruct@{MODEL_REVISION[:12]}",
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}
        ],
        "usage": {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
        "system_fingerprint": MODEL_REVISION,
        "aica_metrics": {"latency_ms": latency_ms},
    }
