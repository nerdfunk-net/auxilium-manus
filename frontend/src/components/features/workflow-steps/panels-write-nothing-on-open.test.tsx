import { QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { loadPluginUI } from "@/lib/plugin-ui-registry";
import { createTestQueryClient } from "@/test/query-wrapper";

// D8 (W14-03): a panel shows the backend defaults and writes nothing into the node until the
// user edits. Opening a node must not mark the workflow dirty.
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(),
}));

const STEPS = [
  "add-nautobot-metadata",
  "add-to-nautobot",
  "background",
  "compare-pyats-snapshot",
  "deploy-rendered-template",
  "from-change-request",
  "get-from-list",
  "get-from-user",
  "git-push",
  "git-status",
  "label",
  "log-attributes",
  "log-message",
  "merge-content",
  "notify",
  "notify-on-error",
  "open-change-request",
      "run-command",
  "update-attribute",
  "upload-config",
] as const;

// These five write derived state on purpose: the upstream step they read from, the canvas
// handles (`outcomes`) or the parsed keys a node produces. The backend cannot default those.
const SEEDING_STEPS = [
  "compare-data",
  "filter-output",
  "store-artifact",
  "route-on-attribute",
  "render-jinja-template",
] as const;

afterEach(cleanup);

async function openPanel(stepId: string, onChange: () => void) {
  const plugin = await loadPluginUI(stepId);
  expect(plugin, `no panel for ${stepId}`).toBeTruthy();
  const { ConfigPanel } = plugin!;
  const client = createTestQueryClient();
  await act(async () => {
    render(
      <QueryClientProvider client={client}>
        <ConfigPanel
          nodeId="n1"
          config={{}}
          onChange={onChange}
          onPreview={() => undefined}
          workflowNodes={[]}
          workflowEdges={[]}
        />
      </QueryClientProvider>,
    );
  });
}

describe("config panels write nothing when opened", () => {
  it.each(STEPS)("%s", async (stepId) => {
    const onChange = vi.fn();
    await openPanel(stepId, onChange);
    expect(onChange).not.toHaveBeenCalled();
  });

  it.each(SEEDING_STEPS)("%s still seeds its derived state once", async (stepId) => {
    const onChange = vi.fn();
    await openPanel(stepId, onChange);
    expect(onChange).toHaveBeenCalledTimes(1);
  });
});
