FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright Chromium browser binary and its system dependencies automatically
RUN playwright install chromium
RUN playwright install-deps chromium

COPY . .

# Create data directory for caches
RUN mkdir -p backend/data && \
    echo '{}' > backend/data/url_cache.json && \
    echo '{}' > backend/data/analysis_cache.json

EXPOSE 8000

CMD uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}
