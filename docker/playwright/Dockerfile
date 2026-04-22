FROM mcr.microsoft.com/playwright:v1.56.1-noble

ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 \
    NODE_PATH=/work/node_modules

WORKDIR /work
RUN npm init -y >/dev/null 2>&1 \
    && npm install --omit=dev playwright@1.56.1 \
    && npm cache clean --force
