# OpenBao server config for PERSISTENT MODE (file storage backend).
#
# Not used in dev mode — in fact this directory MUST stay unmounted while the
# container runs `server -dev`, because the image entrypoint always appends
# `-config=/openbao/config` and a storage stanza collides with dev mode.
# To activate, follow "Persistent mode" in docker-compose.yaml.
#
# This is a LOCAL-LAB config: single node, no TLS on the listener. Put OpenBao
# behind a TLS-terminating reverse proxy (or set tls_cert_file/tls_key_file
# here) before exposing it beyond this machine.
#
# mlock: recent OpenBao removed mlock support, so there is no `disable_mlock`
# setting. Protect secrets from hitting disk by disabling or encrypting swap on
# the host instead — https://openbao.org/docs/install/#post-installation-hardening

storage "file" {
  path = "/openbao/data"
}

listener "tcp" {
  address     = "0.0.0.0:8200"
  tls_disable = "true"
}

api_addr     = "http://openbao:8200"
cluster_addr = "https://openbao:8201"

ui = true
