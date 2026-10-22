import { describe, expect, it } from "vitest";

import { AGENT_SECRET_COMMAND, buildRedisAclCommand } from "./agent-redis-acl";

describe("buildRedisAclCommand", () => {
  it("limits the agent user to its own key prefix and the commands the transport needs", () => {
    const command = buildRedisAclCommand("agent-geo");
    expect(command).toBe(
      "ACL SETUSER agent-agent-geo reset on ><redis-password> ~manus-agent:agent-geo:* " +
        "+blpop +rpush +hset +expire +del +ping",
    );
  });

  it("resets the user first, so running it again replaces old key patterns and passwords", () => {
    const command = buildRedisAclCommand("geo");
    expect(command.indexOf(" reset ")).toBeGreaterThan(-1);
    expect(command.indexOf(" reset ")).toBeLessThan(command.indexOf("~manus-agent"));
    expect(command.indexOf(" reset ")).toBeLessThan(command.indexOf("><redis-password>"));
  });

  it("shows a placeholder until the id is valid, never a command built from raw input", () => {
    for (const typed of ["geo ~* +@all", "Geo", "geo agent", "1abc", "geo\nACL FLUSHALL", "x".repeat(65)]) {
      const command = buildRedisAclCommand(typed);
      expect(command, typed).toContain("agent-<agent_id> reset on");
      expect(command, typed).not.toContain("~*");
      expect(command, typed).not.toContain("+@all");
      expect(command, typed).not.toContain("FLUSHALL");
    }
  });

  it("never grants a broad key pattern or all commands", () => {
    const command = buildRedisAclCommand("a1");
    expect(command).not.toMatch(/~\*/);
    expect(command).not.toContain("+@all");
    expect(command).not.toContain("allkeys");
  });

  it("falls back to a placeholder when the agent id is blank", () => {
    expect(buildRedisAclCommand("  ")).toContain("<agent_id>");
  });

  it("trims surrounding whitespace of a valid id", () => {
    expect(buildRedisAclCommand("  geo  ")).toContain("~manus-agent:geo:*");
  });
});

describe("AGENT_SECRET_COMMAND", () => {
  it("produces a long random secret", () => {
    expect(AGENT_SECRET_COMMAND).toContain("openssl rand");
  });
});
