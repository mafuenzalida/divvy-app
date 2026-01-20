# Dockerfile for CobroF (Divvy) - Bill Splitting App
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies for Pillow and Tesseract (fallback OCR)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-spa \
    libjpeg-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create data directory for local fallback storage
RUN mkdir -p data

# Expose port (Fly.io will set PORT env var)
EXPOSE 8080

# Start the application
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
