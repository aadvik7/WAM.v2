FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
RUN useradd --create-home --uid 1000 wam

# Dependencies first for better layer caching
COPY pyproject.toml ./
RUN mkdir wam && touch wam/__init__.py && pip install . && rm -rf wam build

COPY alembic.ini ./
COPY alembic ./alembic
COPY wam ./wam
RUN pip install --no-deps . && rm -rf build

USER wam
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=4).status == 200 else 1)"

# API by default; the worker runs `arq wam.jobs.worker.WorkerSettings`, migrations `python -m wam.cli bootstrap`
CMD ["uvicorn", "wam.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
