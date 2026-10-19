import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createQueryWrapper } from "@/test/query-wrapper";

import type { EditorVariable } from "../types";
import { buildVariablesContext, useTemplateRender } from "./use-template-render";

const h = vi.hoisted(() => ({ apiCall: vi.fn(), toast: vi.fn() }));
vi.mock("@/hooks/use-api", () => ({ useApi: () => ({ apiCall: h.apiCall }) }));
vi.mock("@/hooks/use-toast", () => ({ useToast: () => ({ toast: h.toast }) }));

const variable = (name: string, value: string) => ({ name, value }) as unknown as EditorVariable;

beforeEach(() => {
  h.apiCall.mockReset();
  h.toast.mockReset();
});

describe("buildVariablesContext", () => {
  it("parses JSON values, keeps plain text and empty strings", () => {
    expect(
      buildVariablesContext([variable("n", "3"), variable("t", "hello"), variable("e", "")]),
    ).toEqual({ n: 3, t: "hello", e: "" });
  });

  it("nests dotted names and skips unnamed variables", () => {
    expect(
      buildVariablesContext([variable("a.b.c", "1"), variable("a.b.d", "2"), variable("", "x")]),
    ).toEqual({ a: { b: { c: 1, d: 2 } } });
  });
});

describe("useTemplateRender", () => {
  it("posts the content with the nested variables, stores the result and opens the dialog", async () => {
    h.apiCall.mockResolvedValue({ rendered: "hostname r1" });
    const { wrapper } = createQueryWrapper();
    const { result } = renderHook(() => useTemplateRender(), { wrapper });
    act(() => result.current.render("hostname {{ x }}", [variable("x", "r1")]));
    await waitFor(() => expect(result.current.showDialog).toBe(true));
    const [endpoint, init] = h.apiCall.mock.calls[0];
    expect(endpoint).toBe("templates/render");
    expect(JSON.parse(init.body)).toEqual({
      template_content: "hostname {{ x }}",
      variables: { x: "r1" },
    });
    expect(result.current.result).toEqual({ rendered: "hostname r1" });
  });

  it("toasts the error and keeps the dialog closed when rendering fails", async () => {
    h.apiCall.mockRejectedValue(new Error("undefined variable"));
    const { wrapper } = createQueryWrapper();
    const { result } = renderHook(() => useTemplateRender(), { wrapper });
    act(() => result.current.render("{{ x }}", []));
    await waitFor(() =>
      expect(h.toast).toHaveBeenCalledWith({
        title: "Render failed",
        description: "undefined variable",
        variant: "destructive",
      }),
    );
    expect(result.current.showDialog).toBe(false);
  });

  it("keeps render stable between renders", () => {
    const { wrapper } = createQueryWrapper();
    const { result, rerender } = renderHook(() => useTemplateRender(), { wrapper });
    const first = result.current.render;
    rerender();
    expect(result.current.render).toBe(first);
  });

  it("returns the same object when nothing changed", () => {
    const { wrapper } = createQueryWrapper();
    const { result, rerender } = renderHook(() => useTemplateRender(), { wrapper });
    const first = result.current;
    rerender();
    expect(result.current).toBe(first);
  });
});
