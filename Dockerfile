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
HEALTHCHECK --interval=30s --timeout=15s --start-period=30s --retries=5 \
  CMD ["/bin/sh", "-ec", "role=${EA_ROLE:-api}; case \"$role\" in worker|scheduler) exit 0 ;; esac; curl -fsS --connect-timeout 2 --max-time 10 http://127.0.0.1:8090/health/live >/dev/null"]

CMD ["python", "-m", "app.runner"]
