import { create } from "zustand";

interface PropertiesPanelState {
  isCollapsed: boolean;
  setCollapsed: (collapsed: boolean) => void;
}

/**
 * Module-level store so the collapsed state of the workflow properties panel
 * survives navigating to another menu and back (the page component unmounts).
 */
export const usePropertiesPanelStore = create<PropertiesPanelState>((set) => ({
  isCollapsed: false,
  setCollapsed: (collapsed) => set({ isCollapsed: collapsed }),
}));
