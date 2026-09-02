import { describe, expect, it, vi } from "vitest";

import { buildApiErrorMessage } from "./use-api";

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
