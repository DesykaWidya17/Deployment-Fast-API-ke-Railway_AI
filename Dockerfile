FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Proper POSIX shell wrapper for uvicorn so that any custom Railway start command works cleanly
RUN printf '#!/bin/sh\nexec python /app/uvicorn_runner.py "$@"\n' > /usr/local/bin/uvicorn && chmod +x /usr/local/bin/uvicorn

EXPOSE 8000

CMD ["python", "run.py"]
