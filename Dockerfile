FROM python:3.12-slim@sha256:c2d8472b831337ab296a8ce652e1ba786e9e3034fc445dc58b50a7f5251f0003

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
COPY ea/requirements.lock .
RUN pip install --no-cache-dir -r requirements.txt -c requirements.lock
COPY ea/app ./app
RUN chown -R ea:ea /app

USER ea
HEALTHCHECK --interval=30s --timeout=15s --start-period=30s --retries=5 \
  CMD ["/bin/sh", "-ec", "role=${EA_ROLE:-api}; case \"$role\" in worker|scheduler) exit 0 ;; esac; curl -fsS --connect-timeout 2 --max-time 10 http://127.0.0.1:8090/healthz >/dev/null"]

CMD ["python", "-m", "app.runner"]
