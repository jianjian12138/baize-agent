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

# Bind on all interfaces, otherwise the container is unreachable from the host.
# These are the key names baize/serve.py actually reads. The previous
# `ENV BAIZE_HOST` / `ENV BAIZE_PORT` were dead names that nothing reads, so the
# server silently stayed on 127.0.0.1 and `-p 8787:8787` could not reach it.
ENV BAIZE_SERVE_HOST=0.0.0.0
ENV BAIZE_SERVE_PORT=8787

# Expose ports for Web UI / RESTful HTTP (8787) and Prometheus metrics
EXPOSE 8787 50051

# /health is served by baize/serve.py. stdlib only, so no curl needed at runtime.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import os,sys,urllib.request; \
port=os.environ.get('BAIZE_SERVE_PORT','8787'); \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+port+'/health', timeout=4).status==200 else 1)"

CMD ["python", "-m", "baize", "serve", "--port", "8787"]
