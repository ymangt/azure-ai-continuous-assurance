FROM python:3.14-slim@sha256:cea0e6040540fb2b965b6e7fb5ffa00871e632eef63719f0ea54bca189ce14a6 AS model

ARG MODEL_REVISION=9b9010e414c555d094141b5bb8da092ebe8f79fa
RUN python -m pip install --no-cache-dir "huggingface_hub[hf_xet]==0.36.0" \
    && mkdir -p /models/phi \
    && hf download microsoft/Phi-4-mini-instruct-onnx \
      --revision "${MODEL_REVISION}" \
      --include "cpu_and_mobile/cpu-int4-rtn-block-32-acc-level-4/*" \
      --local-dir /tmp/phi \
    && cp -R /tmp/phi/cpu_and_mobile/cpu-int4-rtn-block-32-acc-level-4/. /models/phi/

FROM python:3.14-slim@sha256:cea0e6040540fb2b965b6e7fb5ffa00871e632eef63719f0ea54bca189ce14a6
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PHI_MODEL_PATH=/models/phi
WORKDIR /app
COPY pyproject.toml ./
RUN python -m pip install .
COPY server.py ./
COPY --from=model /models/phi /models/phi
RUN groupadd --system --gid 10001 phi \
    && useradd --system --uid 10001 --gid phi --create-home phi \
    && chown -R phi:phi /app /models/phi
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=4s --start-period=300s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
