# syntax=docker/dockerfile:1.7
# Odyssey Kaseya Portal — Django API / Celery worker image (non-root).
FROM python:3.12-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

FROM base AS deps
WORKDIR /build
COPY requirements.lock ./
# Hash-pinned install from the uv-exported lock file.
RUN pip install --require-hashes -r requirements.lock

FROM base AS runtime
RUN groupadd --system --gid 10001 portal \
 && useradd --system --uid 10001 --gid portal --home-dir /app --shell /usr/sbin/nologin portal
COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin
WORKDIR /app
COPY --chown=portal:portal . .
RUN mkdir -p /app/var/reports /app/var/onboarding /app/staticfiles && chown -R portal:portal /app/var /app/staticfiles \
 && chmod +x /app/docker-entrypoint.sh
USER portal
EXPOSE 8000
# Host 'backend' is in DJANGO_ALLOWED_HOSTS in production; 127.0.0.1 is not (DisallowedHost -> unhealthy).
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request as u,sys; r=u.Request('http://127.0.0.1:8000/api/v1/health/live/', headers={'Host': 'backend'}); sys.exit(0 if u.urlopen(r, timeout=4).status == 200 else 1)"
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "60", "--access-logfile", "-"]
