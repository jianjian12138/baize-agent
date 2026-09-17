# syntax=docker/dockerfile:1
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy project definition and source code.
# docs/ is deliberately NOT copied: .dockerignore excludes it to keep the image
# lean, and nothing at runtime reads it. The previous `COPY docs/ ./docs/` could
# never succeed - Docker resolves it against the filtered build context, so the
# build died with `failed to compute cache key: "/docs": not found`.
COPY pyproject.toml .
COPY baize/ ./baize/

# assets/ is the skill library. BAIZE_ASSETS_DIR defaults to <root>/assets and
# `baize index build` scans it, so without this line the container comes up with
# an empty skill index. It is 1.9 MB / 59 files, and .dockerignore does not
# exclude it, so the COPY resolves against the build context.
COPY assets/ ./assets/

# Install python package
RUN pip install --no-cache-dir -e .

# Runtime directories that baize/doctor.py requires to physically exist
# (BAIZE_PERSISTENCE_DIR and BAIZE_PROJECTS_DIR are required checks). Without
# them `baize doctor` exits 1 inside the image, which is what the CI docker job
# was hitting.
RUN mkdir -p /app/persistence /app/projects

# Run as an unprivileged user. Without this the container ran as root, so any
# RCE inside it (see the /v30/synthesize finding) inherited root on the host
# namespace. `chown -R` must come after every COPY and mkdir, otherwise the
# non-root user cannot write to the persistence/projects directories that
# baize/doctor.py requires to be writable.
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin baize \
    && chown -R baize:baize /app
USER baize

# Bind on all interfaces, otherwise the container is unreachable from the host.
# These are the key names baize/serve.py actually reads. The previous
# `ENV BAIZE_HOST` / `ENV BAIZE_PORT` were dead names that nothing reads, so the
# server silently stayed on 127.0.0.1 and `-p 8787:8787` could not reach it.
#
# SECURITY: 0.0.0.0 is kept deliberately, NOT an oversight. A container bound to
# 127.0.0.1 is unreachable through `-p`, which re-introduces the exact bug fixed
# in commit 1824154 and makes the image useless. The exposure is instead bounded
# by authentication: since V37.1 `baize serve` is FAIL-CLOSED, so every
# state-changing route (/v30/synthesize, /v30/adversarial, /sessions, POSTs)
# returns 401 unless BAIZE_AUTH_TOKEN is set and supplied. Only /health,
# /metrics, /api/metrics/summary and the static dashboard remain anonymous, and
# none of them read a secret. Supply a token in production:
#   docker run -e BAIZE_AUTH_TOKEN=$(head -c32 /dev/urandom | base64) ...
# Startup prints an explicit warning when no token is configured.
ENV BAIZE_SERVE_HOST=0.0.0.0
ENV BAIZE_SERVE_PORT=8787

# 8787 is the only port anything actually listens on (baize/serve.py, stdlib
# http.server). The former `EXPOSE 50051` was dead: `grep -rn grpc baize/` finds
# zero hits and pyproject declares `dependencies = []`, so no gRPC server can
# exist. Declaring a port that nothing serves invites scanners and operators to
# treat 50051 as a supported interface.
EXPOSE 8787

# /health is served by baize/serve.py. stdlib only, so no curl needed at runtime.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import os,sys,urllib.request; \
port=os.environ.get('BAIZE_SERVE_PORT','8787'); \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+port+'/health', timeout=4).status==200 else 1)"

CMD ["python", "-m", "baize", "serve", "--port", "8787"]
