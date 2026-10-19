import { describe, expect, it, vi } from "vitest";

import { buildApiErrorMessage, formatValidationDetail } from "./use-api";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status });
}

describe("buildApiErrorMessage", () => {
  it("flips password-change-required on a 403 with that code and returns its message", async () => {
    const onPasswordChangeRequired = vi.fn();
    const response = jsonResponse(403, {
      detail: {
        code: "password_change_required",
        message: "You must change your password before continuing",
      },
    });

    const message = await buildApiErrorMessage(response, onPasswordChangeRequired);

    expect(message).toBe("You must change your password before continuing");
    expect(onPasswordChangeRequired).toHaveBeenCalledOnce();
  });

  it("does not flip the flag for a plain-string 403 detail", async () => {
    const onPasswordChangeRequired = vi.fn();
    const response = jsonResponse(403, { detail: "Permission denied: workflows:read required" });

    const message = await buildApiErrorMessage(response, onPasswordChangeRequired);

    expect(message).toBe("Permission denied: workflows:read required");
    expect(onPasswordChangeRequired).not.toHaveBeenCalled();
  });

  it("does not flip the flag for a 403 with an unrelated object code", async () => {
    const onPasswordChangeRequired = vi.fn();
    const response = jsonResponse(403, {
      detail: { code: "some_other_code", message: "Nope" },
    });

    const message = await buildApiErrorMessage(response, onPasswordChangeRequired);

    expect(message).toBe("Nope");
    expect(onPasswordChangeRequired).not.toHaveBeenCalled();
  });

  it("falls back to 'Permission denied' for a 403 with no parseable detail", async () => {
    const onPasswordChangeRequired = vi.fn();
    const response = new Response("not json", { status: 403 });

    const message = await buildApiErrorMessage(response, onPasswordChangeRequired);

    expect(message).toBe("Permission denied");
    expect(onPasswordChangeRequired).not.toHaveBeenCalled();
  });

  it("uses a string detail for a non-403 error", async () => {
    const response = jsonResponse(400, { detail: "Username already exists" });

    const message = await buildApiErrorMessage(response, vi.fn());

    expect(message).toBe("Username already exists");
  });

  it("caps a long 5xx message rather than leaking it", async () => {
    const response = jsonResponse(500, { detail: "x".repeat(500) });

    const message = await buildApiErrorMessage(response, vi.fn());

    expect(message).toBe("Server error (status 500). Check the logs for details.");
  });

  it("falls back to a generic message when the body is not JSON", async () => {
    const response = new Response("<html>gateway timeout</html>", { status: 502 });

    const message = await buildApiErrorMessage(response, vi.fn());

    expect(message).toBe("API request failed with status 502");
  });
});

describe("validation errors (422 with a list of issues)", () => {
  it("shows the field and message of the first issue", async () => {
    const response = jsonResponse(422, {
      detail: [
        {
          type: "string_pattern_mismatch",
          loc: ["body", "metrics", 0, "alias"],
          msg: "String should match pattern '^[a-z][a-z0-9_]{0,63}$'",
        },
      ],
    });

    const message = await buildApiErrorMessage(response, vi.fn());

    expect(message).toBe("alias: String should match pattern '^[a-z][a-z0-9_]{0,63}$'");
  });

  it("strips 'Value error, ' and counts further issues", () => {
    const message = formatValidationDetail([
      { loc: ["body", "limit"], msg: "Value error, too big" },
      { loc: ["body", "x"], msg: "other" },
    ]);

    expect(message).toBe("limit: too big (and 1 more)");
  });

  it("falls back to the generic message for an unreadable list", async () => {
    const message = await buildApiErrorMessage(jsonResponse(422, { detail: [] }), vi.fn());

    expect(message).toBe("API request failed with status 422");
  });
});

describe("buildApiErrorMessage for a 429", () => {
  const tooMany = (retryAfter?: string, body: unknown = { detail: "Too many requests; slow down and retry shortly" }) =>
    new Response(JSON.stringify(body), {
      status: 429,
      headers: retryAfter === undefined ? {} : { "Retry-After": retryAfter },
    });

  it("tells the user how many seconds to wait", async () => {
    expect(await buildApiErrorMessage(tooMany("30"), vi.fn())).toBe(
      "Too many requests. Please wait 30 seconds and try again.",
    );
  });

  it("uses the singular for one second", async () => {
    expect(await buildApiErrorMessage(tooMany("1"), vi.fn())).toBe(
      "Too many requests. Please wait 1 second and try again.",
    );
  });

  it("switches to minutes, rounded up, from two minutes on", async () => {
    expect(await buildApiErrorMessage(tooMany("119"), vi.fn())).toBe(
      "Too many requests. Please wait 119 seconds and try again.",
    );
    expect(await buildApiErrorMessage(tooMany("120"), vi.fn())).toBe(
      "Too many requests. Please wait 2 minutes and try again.",
    );
    expect(await buildApiErrorMessage(tooMany("901"), vi.fn())).toBe(
      "Too many requests. Please wait 16 minutes and try again.",
    );
  });

  it.each([undefined, "", "abc", "0", "-5", "1.5", "Wed, 21 Oct 2026 07:28:00 GMT"])(
    "falls back to a generic message for Retry-After %j",
    async (value) => {
      expect(await buildApiErrorMessage(tooMany(value), vi.fn())).toBe(
        "Too many requests. Please wait a moment and try again.",
      );
    },
  );

  it("does not depend on the body", async () => {
    const response = new Response("not json", { status: 429, headers: { "Retry-After": "10" } });
    expect(await buildApiErrorMessage(response, vi.fn())).toBe(
      "Too many requests. Please wait 10 seconds and try again.",
    );
  });

  it("leaves other statuses alone", async () => {
    const response = new Response(JSON.stringify({ detail: "Conflict" }), {
      status: 409,
      headers: { "Retry-After": "10" },
    });
    expect(await buildApiErrorMessage(response, vi.fn())).toBe("Conflict");
  });
});
