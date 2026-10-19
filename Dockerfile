FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    GOC_ROCKS_PATH=/data/l1

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential \
      gosu \
      libboost-dev \
      libpqxx-dev \
      librocksdb-dev \
      libssl-dev \
      nlohmann-json3-dev \
      pkg-config \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 10001 --create-home gitchain

WORKDIR /app
COPY . .
RUN python -m pip install --no-cache-dir . \
    && chmod +x /app/docker-entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["sh", "-c", "exec gitchain serve --host 0.0.0.0 --port ${PORT:-8000}"]
