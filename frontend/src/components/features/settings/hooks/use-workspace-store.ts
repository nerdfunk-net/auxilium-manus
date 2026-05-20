import { create } from "zustand";

import type { SettingsSection, Workspace } from "../types/settings-section";

interface WorkspaceState {
  workspace: Workspace;
  settingsSection: SettingsSection;
  setWorkspace: (workspace: Workspace) => void;
  setSettingsSection: (section: SettingsSection) => void;
  openSettings: (section?: SettingsSection) => void;
  openWorkflow: () => void;
}

export const useWorkspaceStore = create<WorkspaceState>((set) => ({
  workspace: "workflow",
  settingsSection: "general",
  setWorkspace: (workspace) => set({ workspace }),
  setSettingsSection: (settingsSection) => set({ settingsSection }),
  openSettings: (section = "general") =>
    set({ workspace: "settings", settingsSection: section }),
  openWorkflow: () => set({ workspace: "workflow" }),
}));
