FROM python:3.12-slim@sha256:c2d8472b831337ab296a8ce652e1ba786e9e3034fc445dc58b50a7f5251f0003

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    espeak-ng \
    ffmpeg \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcairo2 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libglib2.0-0 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libpango-1.0-0 \
    libx11-6 \
    libx11-xcb1 \
    libxcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxkbcommon0 \
    nodejs \
    npm \
    libxrandr2 \
    libxrender1 \
    libxshmfence1 && \
    npm install -g @google/gemini-cli@0.47.0 && \
    npm cache clean --force && \
    rm -rf /var/lib/apt/lists/* && \
    adduser --system --uid 10001 --group --home /home/ea ea && \
    mkdir -p /home/ea && \
    chown -R ea:ea /home/ea

WORKDIR /app

RUN mkdir -p /app/scripts
COPY scripts/willhaben_property_packet.py /app/scripts/willhaben_property_packet.py

COPY . /tmp/src

RUN set -eu; \
    if [ -f /tmp/src/ea/requirements.txt ] && [ -d /tmp/src/ea/app ]; then \
      APP_SRC=/tmp/src/ea; \
    elif [ -f /tmp/src/requirements.txt ] && [ -d /tmp/src/app ]; then \
      APP_SRC=/tmp/src; \
    else \
      echo "application source not found in build context" >&2; \
      exit 1; \
    fi; \
    cp "$APP_SRC/requirements.txt" /app/requirements.txt; \
    if [ -f "$APP_SRC/requirements.lock" ]; then cp "$APP_SRC/requirements.lock" /app/requirements.lock; fi; \
    mkdir -p /app/ea; \
    cp "$APP_SRC/requirements.txt" /app/ea/requirements.txt; \
    if [ -f "$APP_SRC/requirements.lock" ]; then cp "$APP_SRC/requirements.lock" /app/ea/requirements.lock; fi; \
    if [ -f /tmp/src/ea/Dockerfile ]; then cp /tmp/src/ea/Dockerfile /app/ea/Dockerfile; fi; \
    if [ -f /tmp/src/ea/Dockerfile.operator ]; then cp /tmp/src/ea/Dockerfile.operator /app/ea/Dockerfile.operator; fi; \
    if [ -f /tmp/src/Dockerfile ]; then cp /tmp/src/Dockerfile /app/Dockerfile; fi; \
    verification_inputs=/tmp/src/deploy/runtime-image-verification-inputs.txt; \
    [ -f "$verification_inputs" ]; \
    while IFS= read -r verification_input || [ -n "$verification_input" ]; do \
      case "$verification_input" in ""|\#*) continue ;; esac; \
      case "$verification_input" in \
        /*|..|../*|*/..|*/../*) echo "invalid runtime verification input" >&2; exit 1 ;; \
      esac; \
      verification_source="/tmp/src/$verification_input"; \
      verification_target="/app/$verification_input"; \
      [ -f "$verification_source" ] && [ ! -L "$verification_source" ]; \
      mkdir -p "$(dirname "$verification_target")"; \
      cp "$verification_source" "$verification_target"; \
    done < "$verification_inputs"; \
    cp -r "$APP_SRC/app" /app/; \
    cp "$APP_SRC/docker-entrypoint.sh" /usr/local/bin/docker-entrypoint.sh; \
    if [ -d "$APP_SRC/_completion" ]; then \
      cp -r "$APP_SRC/_completion" /app/_completion; \
    fi; \
    if [ -f "$APP_SRC/LTDs.md" ]; then \
      cp "$APP_SRC/LTDs.md" /app/LTDs.md; \
    elif [ -f /tmp/src/LTDs.md ]; then \
      cp /tmp/src/LTDs.md /app/LTDs.md; \
    fi; \
    if [ -f /tmp/src/Makefile ]; then \
      cp /tmp/src/Makefile /app/Makefile; \
    fi; \
    if [ -d /tmp/src/.codex-design ]; then \
      cp -r /tmp/src/.codex-design /app/.codex-design; \
    fi; \
    if [ -d /tmp/src/.codex-studio ]; then \
      cp -r /tmp/src/.codex-studio /app/.codex-studio; \
    fi; \
    mkdir -p /app/scripts; \
    if [ -d /tmp/src/scripts ]; then \
      for script in /tmp/src/scripts/*; do \
        [ -f "$script" ] || continue; \
        cp "$script" /app/scripts/; \
      done; \
    fi; \
    if [ "$APP_SRC" != "/tmp/src" ] && [ -d "$APP_SRC/scripts" ]; then \
      for script in "$APP_SRC"/scripts/*; do \
        [ -f "$script" ] || continue; \
        target="/app/scripts/$(basename "$script")"; \
        if [ -f "$target" ]; then \
          continue; \
        fi; \
        cp "$script" "$target"; \
      done; \
    fi; \
    chown -R ea:ea /app /usr/local/bin/docker-entrypoint.sh; \
    rm -rf /tmp/src

RUN test -f requirements.lock && \
    pip install --no-cache-dir -r requirements.txt -c requirements.lock

RUN chmod +x /usr/local/bin/docker-entrypoint.sh && \
    find /app/scripts -maxdepth 1 -type f -name '*.sh' -exec chmod +x {} \;

# Keep the source attestation in the final cheap image layer. A new Git SHA
# must not invalidate the pinned OS/toolchain layer before application source
# and dependency changes are evaluated.
ARG EA_SOURCE_REVISION=""
RUN set -eu; \
    if [ -n "$EA_SOURCE_REVISION" ]; then \
      [ "${#EA_SOURCE_REVISION}" -eq 40 ]; \
      case "$EA_SOURCE_REVISION" in *[!0-9a-f]*) exit 1 ;; esac; \
    fi
ENV EA_SOURCE_REVISION=${EA_SOURCE_REVISION}

USER ea
HEALTHCHECK --interval=30s --timeout=15s --start-period=30s --retries=5 \
  CMD ["/bin/sh", "-ec", "role=${EA_ROLE:-api}; case \"$role\" in worker|scheduler) test -r /proc/1/cmdline; cmdline=$(tr '\\000' ' ' </proc/1/cmdline); case \"$cmdline\" in *'python -m app.runner'*) exit 0 ;; *) exit 1 ;; esac ;; *) curl -fsS --connect-timeout 2 --max-time 10 http://127.0.0.1:8090/healthz >/dev/null ;; esac"]

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["python", "-m", "app.runner"]
