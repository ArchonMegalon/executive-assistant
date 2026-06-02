FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl docker.io ffmpeg && \
    curl -fsSL https://download.docker.com/linux/static/stable/x86_64/docker-29.3.0.tgz -o /tmp/docker.tgz && \
    tar -xzf /tmp/docker.tgz -C /tmp && \
    mv /tmp/docker/docker /usr/local/bin/docker && \
    chmod +x /usr/local/bin/docker && \
    rm -rf /var/lib/apt/lists/* && \
    rm -rf /tmp/docker /tmp/docker.tgz && \
    adduser --system --uid 10001 --group ea

WORKDIR /app

COPY . /tmp/src

RUN set -eu; \
    if [ -f /tmp/src/requirements.txt ] && [ -d /tmp/src/app ]; then \
      APP_SRC=/tmp/src; \
    elif [ -f /tmp/src/ea/requirements.txt ] && [ -d /tmp/src/ea/app ]; then \
      APP_SRC=/tmp/src/ea; \
    else \
      echo "application source not found in build context" >&2; \
      exit 1; \
    fi; \
    cp "$APP_SRC/requirements.txt" /app/requirements.txt; \
    cp -r "$APP_SRC/app" /app/; \
    cp "$APP_SRC/docker-entrypoint.sh" /usr/local/bin/docker-entrypoint.sh; \
    if [ -f "$APP_SRC/LTDs.md" ]; then \
      cp "$APP_SRC/LTDs.md" /app/LTDs.md; \
    elif [ -f /tmp/src/LTDs.md ]; then \
      cp /tmp/src/LTDs.md /app/LTDs.md; \
    fi; \
    mkdir -p /app/scripts; \
    if [ -d /tmp/src/scripts ]; then \
      for script in /tmp/src/scripts/*.py; do \
        [ -e "$script" ] || continue; \
        cp "$script" /app/scripts/; \
      done; \
    elif [ -d "$APP_SRC/scripts" ]; then \
      for script in "$APP_SRC"/scripts/*.py; do \
        [ -e "$script" ] || continue; \
        cp "$script" /app/scripts/; \
      done; \
    fi; \
    chown -R ea:ea /app /usr/local/bin/docker-entrypoint.sh; \
    rm -rf /tmp/src

RUN pip install --no-cache-dir -r requirements.txt

RUN chmod +x /usr/local/bin/docker-entrypoint.sh

USER root
HEALTHCHECK --interval=30s --timeout=15s --start-period=30s --retries=5 \
  CMD ["/bin/sh", "-ec", "role=${EA_ROLE:-api}; case \"$role\" in worker|scheduler) exit 0 ;; esac; curl -fsS --connect-timeout 2 --max-time 10 http://127.0.0.1:8090/health/live >/dev/null"]

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["python", "-m", "app.runner"]
