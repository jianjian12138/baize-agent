# Baize Engine V33.0.0 - zero runtime dependencies means a tiny, fast image.
# No pip install step at all: the whole engine is Python stdlib.
FROM python:3.12-slim

LABEL org.opencontainers.image.title="Baize Engine" \
      org.opencontainers.image.description="White-box autonomous agent engine (stdlib-only)" \
      org.opencontainers.image.version="33.0.0" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    BAIZE_PERSISTENCE_DIR=/data \
    BAIZE_SERVE_HOST=0.0.0.0 \
    BAIZE_SERVE_PORT=8787

WORKDIR /app

# Copy only what the runtime needs - keeps the layer small and the image clean.
COPY baize/ ./baize/
COPY assets/ ./assets/
COPY AGENT.md SKILL.md README.md ./

# Run as a non-root user; /data is the only writable location.
RUN useradd --system --create-home --uid 10001 baize \
    && mkdir -p /data \
    && chown -R baize:baize /app /data
USER baize

VOLUME ["/data"]
EXPOSE 8787

# Fail the container early if the runtime is broken.
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8787/health',timeout=3).status==200 else 1)"

ENTRYPOINT ["python", "-m", "baize"]
CMD ["serve"]
