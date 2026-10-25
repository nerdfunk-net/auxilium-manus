FROM python:3.12-slim

WORKDIR /app

# Optional company root CAs (TLS-inspecting proxy / private PKI): put PEM files named *.crt (or *.pem)
# into agent/get-ip-addresses/certs/. If there are none, nothing below is set and the image behaves as before.
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

# git pulls the repository at startup; openssh-client is for git over ssh.
RUN apt-get update \
 && apt-get install -y --no-install-recommends git openssh-client \
 && rm -rf /var/lib/apt/lists/*

COPY --chmod=755 entrypoint.sh /usr/local/bin/entrypoint.sh

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY manus_agent ./manus_agent
COPY handlers ./handlers
# The example config; mount your own over /app/config.yaml (see README.md).
COPY config.example.yaml ./config.yaml

# Run unprivileged: the agent holds the shared secret and sees the data it is sent.
# The entrypoint starts as root only to hand /data (the state directory, possibly a freshly mounted
# volume) to this user, then drops privileges to it.
RUN useradd --system --create-home agent && mkdir /data && chown agent /data

ENV PYTHONUNBUFFERED=1 \
    MANUS_AGENT_HTTP_HOST=0.0.0.0 \
    MANUS_AGENT_HANDLERS_DIR=/app/handlers \
    MANUS_AGENT_DATA_CONFIG=/app/config.yaml \
    MANUS_AGENT_STATE_DIR=/data
EXPOSE 8080

# MANUS_AGENT_ID, MANUS_AGENT_SECRET and MANUS_AGENT_HTTP_PORT and/or MANUS_AGENT_REDIS_URL
# are required at run time (see .env.example). The container pulls the git repository from
# config.yaml when it starts; restart it to reload the data.
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["python", "-m", "manus_agent"]
