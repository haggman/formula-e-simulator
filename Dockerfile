FROM python:3.12-slim

WORKDIR /app

# Install deps first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY src/ ./src/

ENV PYTHONUNBUFFERED=1 \
    PORT=8080

# Cloud Run will set PORT; uvicorn binds to it
CMD exec uvicorn src.main:app --host 0.0.0.0 --port ${PORT}