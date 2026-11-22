import { describe, expect, it } from "vitest";

import {
  MAX_SOCKET_TIMEOUT,
  MIN_SOCKET_TIMEOUT,
  clampSocketTimeout,
  deviceFileTransferConfig,
} from "./device-file-transfer";

describe("clampSocketTimeout", () => {
  it("keeps the value inside the backend bounds", () => {
    expect(clampSocketTimeout("30")).toBe(30);
    expect(clampSocketTimeout("1")).toBe(MIN_SOCKET_TIMEOUT);
    expect(clampSocketTimeout("9999")).toBe(MAX_SOCKET_TIMEOUT);
    expect(clampSocketTimeout("")).toBe(MIN_SOCKET_TIMEOUT);
  });
});

describe("deviceFileTransferConfig", () => {
  it("normalises the keys both upload steps share", () => {
    expect(
      deviceFileTransferConfig({
        credential_source: "run_param",
        credential_param: "ssh",
        file_system: "flash:",
        overwrite: true,
      }),
    ).toMatchObject({
      credential_source: "run_param",
      credential_param: "ssh",
      file_system: "flash:",
      overwrite: true,
      socket_timeout: 10,
    });
  });
});
