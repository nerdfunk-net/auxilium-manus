#!/bin/sh
# Start Redis with an ACL file that is generated on every start.
#
# Why generated: loading an ACL file replaces the `default` user, and a file without a `default`
# line leaves it as `nopass` - which would silently drop MANUS_REDIS_PASSWORD, the only thing
# protecting the app's Redis (cache, locks, rate limits, agent queues). So the first line is
# always the default user with that password (stored as a SHA-256 hash, as Redis would keep it),
# followed by the agent users from redis/agents.acl (see agents.acl.example).
#
# Runs as the container entrypoint (docker-compose.yml); Redis itself still drops to its own user.
set -eu

: "${MANUS_REDIS_PASSWORD:?MANUS_REDIS_PASSWORD is required}"

acl=/data/users.acl
agents=/etc/manus-redis/agents.acl

hash=$(printf %s "$MANUS_REDIS_PASSWORD" | sha256sum | cut -d' ' -f1)

{
  echo "user default on #${hash} ~* &* +@all"
  if [ -f "$agents" ]; then
    # Only `user` lines are taken over. A `user default` line is ignored: it could remove the
    # password above.
    grep -E '^[[:space:]]*user[[:space:]]+' "$agents" \
      | grep -vE '^[[:space:]]*user[[:space:]]+default([[:space:]]|$)' || true
    if grep -qE '^[[:space:]]*user[[:space:]]+default([[:space:]]|$)' "$agents"; then
      echo "redis/start.sh: ignoring a 'user default' line in agents.acl" >&2
    fi
  fi
} >"$acl"
chown redis:redis "$acl"
chmod 600 "$acl"

# An invalid line in agents.acl makes Redis refuse to start and say which one; that is intended.
exec docker-entrypoint.sh redis-server --aclfile "$acl" --appendonly yes
