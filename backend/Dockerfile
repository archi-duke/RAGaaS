FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install Python 3.11 and system dependencies
RUN apt-get update && apt-get install -y \
    software-properties-common \
    && add-apt-repository ppa:deadsnakes/ppa \
    && apt-get update && apt-get install -y \
    python3.11 \
    python3.11-venv \
    python3.11-dev \
    python3-pip \
    gcc \
    curl \
    && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1 \
    && update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1 \
    && rm -rf /var/lib/apt/lists/*

# Remove system cryptography (conflicts with pip version under Python 3.11)
RUN apt-get purge -y python3-cryptography 2>/dev/null; rm -rf /usr/lib/python3/dist-packages/cryptography*

# Upgrade pip
RUN python3.11 -m pip install --upgrade pip setuptools wheel

# Copy requirements first for better caching
COPY requirements.txt .
RUN python3.11 -m pip install --no-cache-dir -r requirements.txt
# Copy application code
COPY . .

# Create data directory for SQLite
RUN mkdir -p /app/data

# Expose port
EXPOSE 8000

# Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
