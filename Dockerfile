# syntax=docker/dockerfile:1
# To pin to a specific digest (recommended for reproducibility), run:
#   docker pull python:3.12-slim && docker inspect python:3.12-slim --format '{{index .RepoDigests 0}}'
# Then replace the tag with the digest: FROM python:3.12-slim@sha256:<digest>

# --------------------------------------------------------------------------- #
# Stage 1 — builder: install Python dependencies into /install                #
# --------------------------------------------------------------------------- #
FROM python:3.12-slim AS builder

WORKDIR /build

COPY requirements.txt .

RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# --------------------------------------------------------------------------- #
# Stage 2 — runtime: lean image with only the app and its runtime deps        #
# --------------------------------------------------------------------------- #
FROM python:3.12-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 1000 appuser \
    && useradd --uid 1000 --gid appuser --shell /bin/bash --create-home appuser

# Copy installed packages from the builder stage (excludes pip, setuptools, etc.)
COPY --from=builder /install /usr/local

WORKDIR /app

COPY backend/ backend/
COPY frontend/ frontend/
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

RUN chown -R appuser:appuser /app \
    && chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
