FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create shared volume directory
RUN mkdir -p /shared

# Set environment variables
ENV PYTHONUNBUFFERED=1

# If desired to be invoked via docker exec or as a script
# without the service running
CMD ["tail", "-f", "/dev/null"]

