# Worker app container: shares its gluetun sibling's network and runs the
# scripts you send. Debian-based, so `apt-get install ...` works and you get
# bash + the full GNU userland (scripts with bashisms run fine).
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
      bash curl ca-certificates jq procps iproute2 dnsutils iputils-ping \
      coreutils grep sed tzdata \
 && rm -rf /var/lib/apt/lists/*
CMD ["sleep", "infinity"]
