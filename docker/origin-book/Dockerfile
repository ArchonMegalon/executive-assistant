# Local software-only contexts: installed BrowserAct environment and Chrome
# program directory. Never pass a browser data directory or credentials here.
FROM python:3.12-slim@sha256:c2d8472b831337ab296a8ce652e1ba786e9e3034fc445dc58b50a7f5251f0003
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates libasound2 libatk-bridge2.0-0 libatk1.0-0 libcups2 \
    libdbus-1-3 libdrm2 libgbm1 libglib2.0-0 libgtk-3-0 libnspr4 libnss3 \
    libx11-6 libx11-xcb1 libxcb1 libxcomposite1 libxdamage1 libxext6 \
    libxfixes3 libxkbcommon0 libxrandr2 fonts-liberation xvfb && \
    rm -rf /var/lib/apt/lists/*
COPY --chmod=0755 --from=browseract /lib/python3.12/site-packages/ /opt/browseract/
COPY --from=chrome / /opt/google/chrome/
COPY --chmod=0755 docker/origin-book/browser-act docker/origin-book/google-chrome docker/origin-book/entrypoint /usr/local/bin/
ENV PYTHONPATH=/opt/browseract:/app PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    BROWSERACT_DATA_DIR=/browseract DISPLAY=:97 \
    XDG_CONFIG_HOME=/tmp/config XDG_CACHE_HOME=/tmp/cache
WORKDIR /app
COPY scripts/origin_book_pool.py scripts/origin_chapter_runtime.py \
    scripts/origin_chapter_intake.py scripts/origin_chapter_cycle.py \
    scripts/origin_chapter_worker.py scripts/origin_browser_container.py \
    scripts/firstbook_chapter_capture.py scripts/firstbook_chapter_write.py \
    scripts/firstbook_chapter_review.py scripts/firstbook_chapter_advance.py \
    scripts/firstbook_book_binding.py scripts/firstbook_project_prepare.py \
    scripts/firstbook_outline_prepare.py scripts/firstbook_next_chapter_prepare.py ./scripts/
RUN chmod -R a+rX /app/scripts
USER 1000:1000
RUN python -c 'import importlib.metadata; assert importlib.metadata.version("browser-act-cli") == "1.1.0"; from browser_act_cli.registry import Registry; from scripts import origin_book_pool'
RUN python -c 'from browser_act_cli.session.drivers.real_chrome import find_chrome_executable; assert find_chrome_executable() == "/usr/local/bin/google-chrome"' && google-chrome --version
ENTRYPOINT ["/usr/local/bin/entrypoint"]
