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

# Smart uvicorn CLI wrapper that safely handles unexpanded ${PORT:-8000} strings
RUN cp uvicorn_runner.py /usr/local/bin/uvicorn && chmod +x /usr/local/bin/uvicorn

EXPOSE 8000

CMD ["python", "run.py"]
