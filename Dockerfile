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

# Install python package
RUN pip install --no-cache-dir -e .

# Expose ports for Web UI / RESTful HTTP (8787) and Prometheus metrics
EXPOSE 8787 50051

ENV BAIZE_HOST=0.0.0.0
ENV BAIZE_PORT=8787

CMD ["python", "-m", "baize", "serve", "--port", "8787"]
