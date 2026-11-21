# Multi-stage or single optimized build for GitChain
FROM python:3.11-slim-bookworm

# Avoid interactive prompts during apt install
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000 \
    GOC_ROCKS_PATH=/data/l1 \
    GOC_CHAIN_ID=L1 \
    GOC_CHAIN_TYPE=L1 \
    GOC_ENV=development \
    GOC_ALLOW_INSECURE_BIND=1

# Install C++20 compiler and native dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    pkg-config \
    librocksdb-dev \
    libssl-dev \
    libboost-dev \
    nlohmann-json3-dev \
    libpqxx-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Upgrade pip and install build dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir pybind11 setuptools wheel

# Copy project files
COPY pyproject.toml setup.py README.md ./
COPY include/ ./include/
COPY src/ ./src/
COPY gitchain/ ./gitchain/

# Build goc_core extension and install gitchain package
RUN pip install --no-cache-dir .

# Create persistent storage directory for RocksDB
RUN mkdir -p /data/l1 && chmod 777 /data/l1

# Expose default port
EXPOSE 8000 7860 8080

# Run FastAPI app with uvicorn listening on the dynamically assigned $PORT
CMD ["sh", "-c", "uvicorn gitchain.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
