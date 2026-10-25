#!/bin/sh
# Marker written by the Dockerfile only when company root certificates were baked into the image.
# Without it the environment stays untouched and the default CA bundle is used.
if [ -f /etc/custom-ca-enabled ]; then
  export REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
  export SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
fi
# Started as root (the default): make the state directory writable for the agent user, which a
# newly mounted volume is not, then run as that user. With `docker run --user ...` this is skipped.
if [ "$(id -u)" = "0" ]; then
  state="${MANUS_AGENT_STATE_DIR:-/data}"
  mkdir -p "$state" && chown agent "$state"
  exec setpriv --reuid=agent --regid=agent --init-groups "$@"
fi
exec "$@"
