# Contract Obligation Extraction (Rgc12) serving image.
#
# Supply-chain hardening (practices checks D1/D2/D4): the base image is DIGEST-pinned so a
# re-pushed tag cannot change what ships, dependencies come from the committed lockfile rather
# than a fresh resolve, the runtime stage runs as a non-root user, and a HEALTHCHECK proves the
# process actually serves rather than merely existing.

# --------------------------------------------------------------------------- #
# Builder: resolve nothing, install the lockfile into a venv we copy forward.
# --------------------------------------------------------------------------- #
# Resolved from library/python tag 3.12-slim; dependabot's docker ecosystem proposes digest bumps.
FROM python:3.14-slim@sha256:ce40764625a4ff50df3548277632e7f96c4e77fe75fa848aae9885476e7df5a4 AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# git: needed only while pip fetches the commons git+https pins. The runtime stage copies the
# finished venv and never carries git or a compiler.
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential git \
 && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY pyproject.toml README.md requirements-gcp.lock ./
COPY src ./src
COPY config ./config

# Locked, reproducible install: every version comes from the committed lockfile, then the project
# itself with --no-deps so the lock stays authoritative and nothing is re-resolved at build time.
RUN pip install --upgrade pip \
 && pip install -r requirements-gcp.lock \
 && pip install --no-deps .

# --------------------------------------------------------------------------- #
# Runtime: slim, non-root, no build tools, venv copied from the builder.
# --------------------------------------------------------------------------- #
FROM python:3.14-slim@sha256:ce40764625a4ff50df3548277632e7f96c4e77fe75fa848aae9885476e7df5a4 AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    CONTRACT_PROFILE=gcp \
    CONTRACT_SETTINGS=/app/config/settings.yaml \
    PORT=8080

WORKDIR /app

RUN useradd --create-home --uid 10001 appuser

COPY --from=builder /opt/venv /opt/venv
COPY src ./src
COPY config ./config

USER appuser
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8080')+'/healthz')" || exit 1

# Serve the real FastAPI app object, honouring the platform-provided $PORT (Cloud Run sets it).
# The loopback exposure guard is bound to THIS object, so it holds on this path too.
CMD ["sh", "-c", "python -m contract_obligation_extraction.managed_readiness && exec uvicorn contract_obligation_extraction.api.app:app --host 0.0.0.0 --port ${PORT:-8080}"]
