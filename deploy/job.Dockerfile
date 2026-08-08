FROM python:3.13-slim@sha256:9662417aace5ae7b8e2609cce472b72a8958e134ba372808abe9cc1a0c0125e6 AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /build
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m venv /opt/venv \
    && /opt/venv/bin/python -m pip install --upgrade pip \
    && /opt/venv/bin/python -m pip install .

FROM python:3.13-slim@sha256:9662417aace5ae7b8e2609cce472b72a8958e134ba372808abe9cc1a0c0125e6
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AICA_ENV=production
RUN groupadd --system --gid 10001 aica \
    && useradd --system --uid 10001 --gid aica --create-home aica
COPY --from=builder /opt/venv /opt/venv
COPY assurance /app/assurance
COPY config /app/config
COPY data /app/data
WORKDIR /app
USER 10001:10001
ENTRYPOINT ["assure"]
CMD ["collect", "--profile", "azure-dev"]
