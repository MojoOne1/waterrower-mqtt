FROM python:3.12-slim
# tzdata so TZ resolves to a real zone - session times are shown local
RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ .
# Stamped by the GitHub workflow; local builds show dev/unknown.
ARG APP_VERSION=dev
ARG GIT_COMMIT=unknown
ENV APP_VERSION=$APP_VERSION GIT_COMMIT=$GIT_COMMIT
VOLUME /data
EXPOSE 8090
# /api/health reads the database, so a broken volume shows up as unhealthy
# instead of as a blank page nobody notices.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request as u, sys; \
sys.exit(0 if u.urlopen('http://127.0.0.1:8090/api/health', timeout=4).status == 200 else 1)"
# proxy-headers so the app sees the real scheme behind Cloudflare Tunnel;
# the tunnel is the only thing that ever talks to it, so trust it.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8090", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
