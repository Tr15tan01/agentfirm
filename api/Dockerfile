FROM python:3.13-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY pyproject.toml ./
COPY agentfirm ./agentfirm
COPY alembic ./alembic
COPY alembic.ini ./
COPY scripts ./scripts
RUN pip install ".[r2]" && useradd --system --uid 10001 agentfirm
USER agentfirm
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).status == 200 else 1)"
# Trust X-Forwarded-* only from the reverse proxy (security review F-05). One process per
# container; scale with replicas so each process's metrics are scraped on their own.
ENV FORWARDED_ALLOW_IPS=127.0.0.1
CMD ["sh", "-c", "exec uvicorn agentfirm.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips \"$FORWARDED_ALLOW_IPS\" --no-server-header --timeout-graceful-shutdown 20"]
