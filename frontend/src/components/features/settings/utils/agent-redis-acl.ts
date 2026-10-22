/** Command that creates a high-entropy agent secret (the backend requires >= 32 characters). */
export const AGENT_SECRET_COMMAND = "openssl rand -base64 32";

// Same rule the backend and the form use for an agent id.
const AGENT_ID_PATTERN = /^[a-z][a-z0-9_-]{0,63}$/;
const ID_PLACEHOLDER = "<agent_id>";

/**
 * Redis ACL for the user a remote agent connects as: only its own keys under
 * `manus-agent:<agent_id>:` and only the commands the Redis transport uses. See
 * backend/services/agents/redis_transport.py for the key layout.
 *
 * `ACL SETUSER` on an existing user only *adds* rules, so a key pattern or password granted
 * earlier would survive. `reset` first clears the user's passwords, key patterns, channels
 * and commands, which makes the command safe to run again. A name that is not a valid id
 * (the field is still being typed) shows a placeholder: the preview must never be a command
 * that could grant more than intended.
 */
export function buildRedisAclCommand(agentId: string): string {
  const candidate = agentId.trim();
  const id = AGENT_ID_PATTERN.test(candidate) ? candidate : ID_PLACEHOLDER;
  return (
    `ACL SETUSER agent-${id} reset on ><redis-password> ~manus-agent:${id}:* ` +
    "+blpop +rpush +hset +expire +del +ping"
  );
}
