FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl docker.io && \
    curl -fsSL https://download.docker.com/linux/static/stable/x86_64/docker-29.3.0.tgz -o /tmp/docker.tgz && \
    tar -xzf /tmp/docker.tgz -C /tmp && \
    mv /tmp/docker/docker /usr/local/bin/docker && \
    chmod +x /usr/local/bin/docker && \
    rm -rf /var/lib/apt/lists/* && \
    rm -rf /tmp/docker /tmp/docker.tgz && \
    adduser --system --uid 10001 --group ea

WORKDIR /app
COPY ea/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY ea/app ./app
COPY ea/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chown -R ea:ea /app && chmod +x /usr/local/bin/docker-entrypoint.sh

USER root
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import os,sys,urllib.request; role=os.environ.get('EA_ROLE','api').strip().lower(); sys.exit(0 if role in {'worker','scheduler'} else int(urllib.request.urlopen('http://127.0.0.1:8090/health', timeout=3).status != 200))" >/dev/null || exit 1

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["python", "-m", "app.runner"]
