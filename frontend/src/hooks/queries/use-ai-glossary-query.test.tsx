import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { GlossaryKind } from "@/components/features/ai-assistant/types/ai-assistant";
import { createQueryWrapper } from "@/test/query-wrapper";

import { useAiGlossaryQuery } from "./use-ai-glossary-query";

const apiCall = vi.fn();
vi.mock("@/hooks/use-api", () => ({ useApi: () => ({ apiCall }) }));

const page = (term: string) => ({ items: [{ id: 1, term }], total: 1 });

interface Props {
  kind: GlossaryKind;
  query: string;
}

function setup(initial: Props) {
  const { wrapper } = createQueryWrapper();
  return renderHook(
    (props: Props) => useAiGlossaryQuery({ ...props, offset: 0, limit: 25 }),
    {
      wrapper,
      initialProps: initial,
    },
  );
}

describe("useAiGlossaryQuery", () => {
  beforeEach(() => apiCall.mockReset());

  it("sends the kind, search text and paging", async () => {
    apiCall.mockResolvedValue(page("core"));
    const { result } = setup({ kind: "workflow_step", query: "git" });

    await waitFor(() => expect(result.current.data).toBeDefined());

    expect(apiCall).toHaveBeenCalledWith(
      "ai/glossary?kind=workflow_step&limit=25&offset=0&q=git",
      {
        method: "GET",
      },
    );
  });

  it("keeps the previous page while the search text changes", async () => {
    apiCall
      .mockResolvedValueOnce(page("core"))
      .mockReturnValueOnce(new Promise(() => undefined));
    const { result, rerender } = setup({ kind: "inventory_filter", query: "" });
    await waitFor(() => expect(result.current.data).toBeDefined());

    rerender({ kind: "inventory_filter", query: "co" });

    expect(result.current.isPlaceholderData).toBe(true);
    expect(result.current.data?.items[0].term).toBe("core");
  });

  it("never shows another kind's rows while the new kind loads", async () => {
    apiCall
      .mockResolvedValueOnce(page("core"))
      .mockReturnValueOnce(new Promise(() => undefined));
    const { result, rerender } = setup({ kind: "inventory_filter", query: "" });
    await waitFor(() => expect(result.current.data).toBeDefined());

    rerender({ kind: "workflow_step", query: "" });

    expect(result.current.data).toBeUndefined();
    expect(result.current.isPlaceholderData).toBe(false);
  });
});
