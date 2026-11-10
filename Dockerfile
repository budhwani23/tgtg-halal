FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    DATA_DIR=/data SCRAPER_ENABLED=false

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY static ./static
COPY run.py .
# Snapshot of the listings + halal scores, copied into /data on first start only.
# TGTG login tokens are NOT included.
COPY data/tgtg_halal.sqlite3 /seed/tgtg_halal.sqlite3
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

RUN useradd --uid 10002 --no-create-home appuser && mkdir -p /data && chown appuser /data \
    && chmod +x /usr/local/bin/docker-entrypoint.sh
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')"
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
