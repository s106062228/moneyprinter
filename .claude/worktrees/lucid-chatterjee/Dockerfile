# Multi-stage Dockerfile for MoneyPrinter
FROM python:3.12-slim as base

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    firefox-esr \
    xvfb \
    imagemagick \
    wget \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Download and install geckodriver
RUN wget -q https://github.com/mozilla/geckodriver/releases/download/v0.34.0/geckodriver-v0.34.0-linux64.tar.gz \
    && tar -xzf geckodriver-v0.34.0-linux64.tar.gz -C /usr/local/bin \
    && rm geckodriver-v0.34.0-linux64.tar.gz \
    && chmod +x /usr/local/bin/geckodriver

# Create non-root user
RUN useradd -m -u 1000 moneyprinter && \
    mkdir -p /app && \
    chown -R moneyprinter:moneyprinter /app

WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY --chown=moneyprinter:moneyprinter src ./src
COPY --chown=moneyprinter:moneyprinter scripts ./scripts
COPY --chown=moneyprinter:moneyprinter config.example.json ./config.example.json
COPY --chown=moneyprinter:moneyprinter assets ./assets
COPY --chown=moneyprinter:moneyprinter fonts ./fonts

# Switch to non-root user
USER moneyprinter

# Set environment variables for headless browser operation
ENV DISPLAY=:99 \
    PYTHONUNBUFFERED=1 \
    PATH="/home/moneyprinter/.local/bin:${PATH}"

# Health check to verify the container is running
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD pgrep -f "Xvfb|python" > /dev/null || exit 1

# Start Xvfb in background and run the main application
CMD ["sh", "-c", "Xvfb :99 -screen 0 1280x1024x24 > /dev/null 2>&1 & sleep 2 && python src/main.py"]
