FROM python:3.12-slim

# Create a non-root user to run the bot
RUN useradd --create-home --shell /bin/bash appuser

WORKDIR /app

# Install dependencies before copying source so Docker can cache this layer
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY bot/ bot/

# Create mount-point directories with correct ownership
RUN mkdir -p /app/config /app/data && chown -R appuser:appuser /app

USER appuser

CMD ["python", "-m", "bot.main"]
