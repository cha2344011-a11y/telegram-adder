FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Set timezone to India
ENV TZ=Asia/Kolkata
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Copy requirements first (for Docker layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the full project
COPY . .

# Make sure data directory exists
RUN mkdir -p data sessions

# Expose port
EXPOSE 5000

# Start the app with gunicorn (threading mode - no eventlet)
CMD ["gunicorn", "--threads", "50", "-w", "1", "--bind", "0.0.0.0:5000", "--timeout", "120", "app:app"]
