FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY src/ ./src/

# Create data directory
RUN mkdir -p /app/data

# Run as non-root user
RUN useradd -m -u 1000 checker && chown -R checker:checker /app
USER checker

CMD ["python", "-m", "src.main"]
