FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for lxml and curl_cffi
RUN apt-get update \
    && apt-get install -y --no-install-recommends libxml2-dev libxslt-dev gcc libcurl4-openssl-dev libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY src/ ./src/

# Create data directory
RUN mkdir -p /app/data

EXPOSE 5000

# Run as non-root user
RUN useradd -m -u 1000 checker && chown -R checker:checker /app
USER checker

CMD ["python", "-m", "src.main"]
