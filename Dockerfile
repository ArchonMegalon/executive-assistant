FROM python:3.12-slim

# Install system dependencies for Docker-in-Docker
RUN apt-get update && apt-get install -y \
    curl \
    && curl -fsSL https://get.docker.com | sh \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Ensure dependencies are installed first for caching
RUN printf '#!/bin/sh\necho "🛡️ OODA-Shield: OS Command blocked. Running inside isolated container." >&2\nexit 127\n' > /usr/local/bin/docker && chmod +x /usr/local/bin/docker
COPY ea/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application
COPY ea/app ./app

# Force unbuffered logging so we see every print statement
ENV PYTHONUNBUFFERED=1

# Use a standard uvicorn entrypoint that points to the lifespan-enabled main
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8090"]