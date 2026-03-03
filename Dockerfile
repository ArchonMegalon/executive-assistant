FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl docker.io && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY ea/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY ea/app ./app
CMD ["python", "-m", "app.runner"]
