# Phi-4 mini CPU fallback

This image is the live Azure-hosted fallback when the Student subscription has no deployable
Azure OpenAI quota. It serves the official Microsoft `Phi-4-mini-instruct` int4 CPU ONNX artifact
through a narrow OpenAI-compatible endpoint.

- Source: `microsoft/Phi-4-mini-instruct-onnx`
- Revision: `9b9010e414c555d094141b5bb8da092ebe8f79fa`
- Variant: `cpu_and_mobile/cpu-int4-rtn-block-32-acc-level-4`
- Runtime: `onnxruntime-genai` 0.13.0
- License: MIT
- Expected weight footprint: approximately 4.9 GB

The image is intentionally not part of routine CI. A protected workflow builds it only after the
Foundry quota gate fails, publishes a signed digest, deploys it to the ephemeral 4-vCPU/8-GB
Container App, records cold-start/latency/memory/cost evidence, and scales it to zero after a demo.
Raw prompts and responses are not written to operational logs.

The model download uses the current `hf download` command, not the deprecated
`huggingface-cli`, and pins the repository revision so provenance does not float over time.
