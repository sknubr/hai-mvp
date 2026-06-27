FROM python:3.13-slim

WORKDIR /app

# Install deps first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code + committed (read-only) profiles
COPY app/ ./app/
COPY profiles/ ./profiles/

# Per-user state/feed/feedback live here; mount a persistent volume at /app/data
# so it survives redeploys (the app writes to data/ relative to the repo root).
RUN mkdir -p data
VOLUME ["/app/data"]

ENV LLM_PROVIDER=google \
    GOOGLE_MODEL=gemini-3.1-flash-lite \
    GOOGLE_MODEL_FALLBACKS=gemini-3-flash-preview,gemma-4-31b-it \
    HAI_DAILY_CALL_CAP=80 \
    PORT=8000

EXPOSE 8000

# Honor the platform's $PORT (Render/Fly set it); default 8000 locally.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
