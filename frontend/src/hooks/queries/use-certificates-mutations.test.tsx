import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { queryKeys } from "@/lib/query-keys";
import { createQueryWrapper } from "@/test/query-wrapper";

import { useCertificatesMutations } from "./use-certificates-mutations";

const apiCall = vi.fn();
const toast = vi.fn();
vi.mock("@/hooks/use-api", () => ({ useApi: () => ({ apiCall }) }));
vi.mock("@/hooks/use-toast", () => ({ useToast: () => ({ toast }) }));

beforeEach(() => {
  apiCall.mockReset();
  toast.mockReset();
});

function setup() {
  const { wrapper, client } = createQueryWrapper();
  const invalidate = vi.spyOn(client, "invalidateQueries");
  const { result } = renderHook(() => useCertificatesMutations(), { wrapper });
  return { result, invalidate };
}

const SCAN = queryKeys.certificates.scan();

describe("useCertificatesMutations", () => {
  it("uploadCertificate sends the file as multipart form data without a JSON header", async () => {
    apiCall.mockResolvedValue({});
    const { result, invalidate } = setup();
    const file = new File(["pem"], "ca.pem");

    await act(async () => {
      await result.current.uploadCertificate.mutateAsync(file);
    });

    const [endpoint, init] = apiCall.mock.calls[0];
    expect(endpoint).toBe("certificates/upload");
    expect(init.method).toBe("POST");
    expect(init.headers).toBeUndefined();
    expect(init.body).toBeInstanceOf(FormData);
    expect((init.body as FormData).get("file")).toBe(file);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: SCAN });
    expect(toast).toHaveBeenCalledWith({ title: "Uploaded", description: "Certificate uploaded." });
  });

  it("uploadCertificate toasts a failure", async () => {
    apiCall.mockRejectedValue(new Error("too big"));
    const { result, invalidate } = setup();

    await act(async () => {
      await expect(
        result.current.uploadCertificate.mutateAsync(new File(["x"], "a.pem")),
      ).rejects.toThrow("too big");
    });

    expect(invalidate).not.toHaveBeenCalled();
    expect(toast).toHaveBeenCalledWith({
      title: "Upload failed",
      description: "too big",
      variant: "destructive",
    });
  });

  describe("addCertificatesToSystem", () => {
    it("adds the files one at a time, in order, and merges each result", async () => {
      const order: string[] = [];
      apiCall.mockImplementation(async (_endpoint: string, init: { body: string }) => {
        const { filename } = JSON.parse(init.body);
        order.push(`start:${filename}`);
        await Promise.resolve();
        order.push(`end:${filename}`);
        return { success: true, message: `added ${filename}` };
      });
      const { result, invalidate } = setup();

      let results: unknown;
      await act(async () => {
        results = await result.current.addCertificatesToSystem.mutateAsync(["a.pem", "b.pem"]);
      });

      expect(order).toEqual(["start:a.pem", "end:a.pem", "start:b.pem", "end:b.pem"]);
      expect(results).toEqual([
        { filename: "a.pem", success: true, message: "added a.pem" },
        { filename: "b.pem", success: true, message: "added b.pem" },
      ]);
      expect(invalidate).toHaveBeenCalledWith({ queryKey: SCAN });
    });

    it("keeps going after a failure and reports it per file instead of rejecting", async () => {
      apiCall
        .mockRejectedValueOnce(new Error("permission denied"))
        .mockRejectedValueOnce("odd failure")
        .mockResolvedValueOnce({ success: true, message: "ok", command_output: "out" });
      const { result } = setup();

      let results: unknown;
      await act(async () => {
        results = await result.current.addCertificatesToSystem.mutateAsync([
          "a.pem",
          "b.pem",
          "c.pem",
        ]);
      });

      expect(results).toEqual([
        { filename: "a.pem", success: false, message: "permission denied" },
        { filename: "b.pem", success: false, message: "Unexpected error" },
        { filename: "c.pem", success: true, message: "ok", command_output: "out" },
      ]);
    });

    it("does nothing for an empty list but still refreshes the scan", async () => {
      const { result, invalidate } = setup();

      await act(async () => {
        await result.current.addCertificatesToSystem.mutateAsync([]);
      });

      expect(apiCall).not.toHaveBeenCalled();
      expect(invalidate).toHaveBeenCalledWith({ queryKey: SCAN });
    });
  });

  it("deleteCertificate URL-encodes the filename", async () => {
    apiCall.mockResolvedValue(undefined);
    const { result, invalidate } = setup();

    await act(async () => {
      await result.current.deleteCertificate.mutateAsync("my cert/../x.pem");
    });

    expect(apiCall).toHaveBeenCalledWith("certificates/my%20cert%2F..%2Fx.pem", {
      method: "DELETE",
    });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: SCAN });
    expect(toast).toHaveBeenCalledWith({ title: "Deleted", description: "Certificate removed." });
  });

  it("deleteCertificate toasts a failure", async () => {
    apiCall.mockRejectedValue(new Error("in use"));
    const { result } = setup();

    await act(async () => {
      await expect(result.current.deleteCertificate.mutateAsync("a.pem")).rejects.toThrow();
    });

    expect(toast).toHaveBeenCalledWith({
      title: "Delete failed",
      description: "in use",
      variant: "destructive",
    });
  });
});
