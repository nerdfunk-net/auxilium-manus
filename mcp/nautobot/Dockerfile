FROM python:3.12-slim

WORKDIR /app

# Optional company root CAs (TLS-inspecting proxy / private PKI): put PEM files named *.crt (or *.pem)
# into mcp/nautobot/certs/. If there are none, nothing below is set and the image behaves as before.
# pip.conf makes pip trust the bundle at build time; the marker file makes entrypoint.sh export
# REQUESTS_CA_BUNDLE / SSL_CERT_FILE at run time (httpx reads SSL_CERT_FILE).
COPY certs/ /tmp/certs/
RUN set -e; \
    found=0; \
    for f in /tmp/certs/*.crt /tmp/certs/*.pem; do \
      [ -f "$f" ] || continue; \
      cp "$f" "/usr/local/share/ca-certificates/$(basename "${f%.*}").crt"; \
      found=1; \
    done; \
    if [ "$found" = 1 ]; then \
      apt-get update && apt-get install -y --no-install-recommends ca-certificates \
        && rm -rf /var/lib/apt/lists/*; \
      update-ca-certificates; \
      printf '[global]\ncert = /etc/ssl/certs/ca-certificates.crt\n' > /etc/pip.conf; \
      touch /etc/custom-ca-enabled; \
    fi; \
    rm -rf /tmp/certs

COPY --chmod=755 entrypoint.sh /usr/local/bin/entrypoint.sh

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY nautobot_mcp ./nautobot_mcp

# Run unprivileged: the server holds the Nautobot token. It keeps no state, so the container
# can use a read-only root filesystem.
RUN useradd --system --create-home mcp
USER mcp

ENV PYTHONUNBUFFERED=1 \
    MCP_TRANSPORT=http \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8000
EXPOSE 8000

# Required at run time (see .env.example): NAUTOBOT_URL, NAUTOBOT_TOKEN, MCP_ALLOWED_HOSTS and
# MCP_CLIENT_TOKENS and/or MCP_CLIENT_TOKENS_FILE. GET /healthz needs no token and does not
# call Nautobot.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import os, urllib.request as u; u.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('MCP_PORT', '8000'), timeout=3)"]

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["python", "-m", "nautobot_mcp"]
