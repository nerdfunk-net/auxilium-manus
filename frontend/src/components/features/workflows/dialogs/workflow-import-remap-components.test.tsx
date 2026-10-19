import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Credential } from "@/components/features/settings/credentials/types";

import { WorkflowImportCredentialRemap } from "./workflow-import-credential-remap";
import { WorkflowImportReferenceRemap } from "./workflow-import-reference-remap";

const noop = () => undefined;

describe("WorkflowImportReferenceRemap", () => {
  const base = {
    title: "Git repository mapping",
    description: "d",
    requirements: [{ key: "7", label: "Repository #7" }],
    options: [],
    value: {},
    onChange: noop,
    emptyMessage: "No git repositories configured. Add one in Settings → Git Repositories first.",
  };

  it("tells the user to add one when the list loaded and is empty", () => {
    render(<WorkflowImportReferenceRemap {...base} />);
    expect(screen.getByText(/Add one in Settings → Git Repositories/)).toBeTruthy();
  });

  // The advice to "add one in Settings" is wrong for someone who cannot even view the list.
  it("explains a permission problem instead when the list could not be loaded", () => {
    render(<WorkflowImportReferenceRemap {...base} loadFailed />);
    expect(screen.queryByText(/Add one in Settings/)).toBeNull();
    expect(screen.getByText(/could not be loaded, probably because you don't have permission/)).toBeTruthy();
  });

  it("shows the selector when options exist, even if loadFailed was set before", () => {
    render(
      <WorkflowImportReferenceRemap
        {...base}
        options={[{ value: "1", label: "configs (device_configs)" }]}
      />,
    );
    expect(screen.getByText("Repository #7")).toBeTruthy();
    expect(screen.queryByText(/Add one in Settings/)).toBeNull();
  });

  it("shows a loading hint while loading", () => {
    render(<WorkflowImportReferenceRemap {...base} isLoading />);
    expect(screen.getByText("Loading…")).toBeTruthy();
  });
});

describe("WorkflowImportCredentialRemap", () => {
  const requirements = [
    { name: "lab-ssh", visibility: "unknown", owner_username: null, credentialType: "ssh" },
  ] as never;

  it("tells the user to add a credential when the list loaded and has none of that type", () => {
    render(
      <WorkflowImportCredentialRemap requirements={requirements} credentials={[]} value={{}} onChange={noop} />,
    );
    expect(screen.getByText(/No ssh credentials available/)).toBeTruthy();
  });

  it("explains a permission problem when the credential list could not be loaded", () => {
    render(
      <WorkflowImportCredentialRemap
        requirements={requirements}
        credentials={[]}
        value={{}}
        onChange={noop}
        loadFailed
      />,
    );
    expect(screen.queryByText(/No ssh credentials available/)).toBeNull();
    expect(screen.getByText(/could not be loaded, probably because you don't have permission/)).toBeTruthy();
  });

  it("lists matching credentials when there are some", () => {
    const credentials = [
      { id: 1, name: "mine", username: "u", type: "ssh", visibility: "global" },
    ] as unknown as Credential[];
    render(
      <WorkflowImportCredentialRemap requirements={requirements} credentials={credentials} value={{}} onChange={noop} />,
    );
    expect(screen.getByText("lab-ssh")).toBeTruthy();
    expect(screen.queryByText(/No ssh credentials available/)).toBeNull();
  });
});
