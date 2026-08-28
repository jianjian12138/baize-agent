# syntax=docker/dockerfile:1
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy project definition and source code
COPY pyproject.toml .
COPY baize/ ./baize/
COPY docs/ ./docs/

# Install python package
RUN pip install --no-cache-dir -e .

# Expose ports for Web UI / RESTful HTTP (8787) and Prometheus metrics
EXPOSE 8787 50051

ENV BAIZE_HOST=0.0.0.0
ENV BAIZE_PORT=8787

CMD ["python", "-m", "baize", "serve", "--port", "8787"]
