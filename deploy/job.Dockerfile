FROM python:3.14-slim@sha256:cea0e6040540fb2b965b6e7fb5ffa00871e632eef63719f0ea54bca189ce14a6 AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /build
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m venv /opt/venv \
    && /opt/venv/bin/python -m pip install --upgrade pip \
    && /opt/venv/bin/python -m pip install .

FROM python:3.14-slim@sha256:cea0e6040540fb2b965b6e7fb5ffa00871e632eef63719f0ea54bca189ce14a6
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
