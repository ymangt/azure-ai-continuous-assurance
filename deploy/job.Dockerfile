FROM python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /build
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m venv /opt/venv \
    && /opt/venv/bin/python -m pip install --upgrade pip \
    && /opt/venv/bin/python -m pip install .

FROM python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de
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
