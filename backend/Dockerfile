FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

# RUN mkdir -p /app/logs /app/test-results && \
#     useradd --create-home --shell /bin/bash appuser && \
#     chown -R appuser:appuser /app
RUN mkdir -p /app/logs /app/test-results /app/uploads && \
    useradd --create-home --shell /bin/bash appuser && \
    chown -R appuser:appuser /app && \
    chmod -R 755 /app/uploads

USER appuser

ENV APP_PORT=8652

EXPOSE 8652

HEALTHCHECK CMD sh -c 'curl -f "http://localhost:${APP_PORT}/health" || exit 1'

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port $APP_PORT"]