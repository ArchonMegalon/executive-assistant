FROM python:3.12-slim

ARG HOST_DOCKER_GID=112

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl docker.io && \
    groupadd -f -g "${HOST_DOCKER_GID}" docker && \
    rm -rf /var/lib/apt/lists/* && \
    adduser --system --uid 10001 --group ea && \
    usermod -aG docker ea

WORKDIR /app
COPY ea/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY ea/app ./app
RUN chown -R ea:ea /app

USER ea
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import os,sys,urllib.request; role=os.environ.get('EA_ROLE','api').strip().lower(); sys.exit(0 if role in {'worker','scheduler'} else int(urllib.request.urlopen('http://127.0.0.1:8090/health', timeout=3).status != 200))" >/dev/null || exit 1

CMD ["python", "-m", "app.runner"]
