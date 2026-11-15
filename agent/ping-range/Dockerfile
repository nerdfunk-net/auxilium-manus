FROM python:3.12-slim

# Build-time proxy for apt (optional; forwarded by prepare-agent-image.sh / build-with-proxy).
ARG HTTP_PROXY
ARG HTTPS_PROXY

# fping is the only system package: the agent pings whole ranges with it.
RUN if [ -n "$HTTP_PROXY" ] || [ -n "$HTTPS_PROXY" ]; then \
      echo "Acquire::http::Proxy \"${HTTP_PROXY}\";" > /etc/apt/apt.conf.d/01proxy; \
      echo "Acquire::https::Proxy \"${HTTPS_PROXY}\";" >> /etc/apt/apt.conf.d/01proxy; \
    fi \
    && apt-get update \
    && apt-get install -y --no-install-recommends fping \
    && rm -rf /var/lib/apt/lists/* \
    && rm -f /etc/apt/apt.conf.d/01proxy

WORKDIR /app

# Optional company root CAs (TLS-inspecting proxy / private PKI): put PEM files named *.crt (or *.pem)
# into agent/ping-range/certs/. If there are none, nothing below is set and the image behaves as before.
# pip.conf makes pip trust the bundle at build time; the marker file makes entrypoint.sh export
# REQUESTS_CA_BUNDLE / SSL_CERT_FILE at run time.
COPY certs/ /tmp/certs/
RUN set -e; \
    found=0; \
    for f in /tmp/certs/*.crt /tmp/certs/*.pem; do \
      [ -f "$f" ] || continue; \
      cp "$f" "/usr/local/share/ca-certificates/$(basename "${f%.*}").crt"; \
      found=1; \
    done; \
    if [ "$found" = 1 ]; then \
      update-ca-certificates; \
      printf '[global]\ncert = /etc/ssl/certs/ca-certificates.crt\n' > /etc/pip.conf; \
      touch /etc/custom-ca-enabled; \
    fi; \
    rm -rf /tmp/certs

COPY --chmod=755 entrypoint.sh /usr/local/bin/entrypoint.sh

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY manus_agent ./manus_agent
# The ping_range handler.
COPY handlers ./handlers

# Run unprivileged: the agent holds the shared secret and sees the data it is sent. fping gets
# raw sockets from the NET_RAW capability the compose file adds (and from its file capability).
RUN useradd --system --create-home agent
USER agent

ENV PYTHONUNBUFFERED=1 \
    MANUS_AGENT_HTTP_HOST=0.0.0.0 \
    MANUS_AGENT_HANDLERS_DIR=/app/handlers
EXPOSE 6667

# MANUS_AGENT_ID, MANUS_AGENT_SECRET and MANUS_AGENT_HTTP_PORT and/or MANUS_AGENT_REDIS_URL
# are required at run time (see .env.example).
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["python", "-m", "manus_agent"]
