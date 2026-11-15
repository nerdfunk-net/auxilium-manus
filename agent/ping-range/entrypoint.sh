#!/bin/sh
# Marker written by the Dockerfile only when company root certificates were baked into the image.
# Without it the environment stays untouched and the default CA bundle is used.
if [ -f /etc/custom-ca-enabled ]; then
  export REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
  export SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
fi
exec "$@"
