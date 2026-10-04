"use client";

import { useCallback, useMemo, useState } from "react";

import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";

import { StepDetailsDialog } from "./step-details-dialog";
import { StepLibraryCategories } from "../components/step-library/step-library-categories";
import { StepLibraryDescription } from "../components/step-library/step-library-description";
import { StepLibraryGrid } from "../components/step-library/step-library-grid";
import { useStepLibraryGroups } from "../hooks/use-step-library-groups";
import { useWorkflowBuilderStore } from "../hooks/use-workflow-builder-store";
import type { PluginDefinition } from "../types/plugin-registry";
import type { StepPayload } from "../types/workflow-canvas";
import type { PaletteItem } from "../utils/step-catalog";
import {
  ALL_CATEGORY_KEY,
  filterGroupsByQuery,
  stepsForCategory,
} from "../utils/step-library-filter";
import { toDropPosition } from "../utils/step-drop-offset";

interface StepLibraryDialogProps {
  errorMessage?: string;
  isLoading: boolean;
  onAddStep: (step: StepPayload) => void;
  onAddStepAtPosition: (step: StepPayload, position: { x: number; y: number }) => void;
  plugins: PluginDefinition[];
}

/** Dialog shell: unmounts the body on close so category/search/selection state resets on every open. */
export function StepLibraryDialog(props: StepLibraryDialogProps) {
  const open = useWorkflowBuilderStore((state) => state.stepLibrary.open);
  const closeStepLibrary = useWorkflowBuilderStore((state) => state.closeStepLibrary);
  const handleOpenChange = useCallback(
    (next: boolean) => {
      if (!next) closeStepLibrary();
    },
    [closeStepLibrary],
  );

  return (
    <Dialog onOpenChange={handleOpenChange} open={open}>
      <DialogContent className="flex h-[80vh] max-h-[720px] flex-col gap-0 p-0 sm:max-w-4xl">
        <div className="shrink-0 border-b px-5 py-3.5">
          <DialogTitle>Steps library</DialogTitle>
          <DialogDescription className="text-xs">
            Pick a category, select a step and press Add.
          </DialogDescription>
        </div>
        {open ? <StepLibraryBody {...props} /> : null}
      </DialogContent>
    </Dialog>
  );
}

function StepLibraryBody({
  errorMessage,
  isLoading,
  onAddStep,
  onAddStepAtPosition,
  plugins,
}: StepLibraryDialogProps) {
  const dropPosition = useWorkflowBuilderStore((state) => state.stepLibrary.dropPosition);
  const closeStepLibrary = useWorkflowBuilderStore((state) => state.closeStepLibrary);
  const [search, setSearch] = useState("");
  const [categoryKey, setCategoryKey] = useState(ALL_CATEGORY_KEY);
  const [selectedKind, setSelectedKind] = useState<string | null>(null);
  const [detailsOpen, setDetailsOpen] = useState(false);

  const groups = useStepLibraryGroups(plugins);
  const searchedGroups = useMemo(() => filterGroupsByQuery(groups, search), [groups, search]);
  const items = useMemo(
    () => stepsForCategory(searchedGroups, categoryKey),
    [searchedGroups, categoryKey],
  );
  const selectedItem = useMemo(
    () => items.find((item) => item.kind === selectedKind) ?? null,
    [items, selectedKind],
  );

  const addItem = useCallback(
    (item: PaletteItem) => {
      closeStepLibrary();
      if (dropPosition) {
        onAddStepAtPosition(item, toDropPosition(dropPosition, item.kind));
      } else {
        onAddStep(item);
      }
    },
    [closeStepLibrary, dropPosition, onAddStep, onAddStepAtPosition],
  );

  const selectedPlugin = useMemo(
    () => plugins.find((plugin) => plugin.id === selectedItem?.kind),
    [plugins, selectedItem],
  );
  const handleShowStep = useCallback(() => setDetailsOpen(true), []);

  // Changing the filter drops the selection, so a step hidden by the filter
  // can't silently reappear (and stay selected) when the filter is cleared.
  const handleSearchChange = useCallback((value: string) => {
    setSearch(value);
    setSelectedKind(null);
  }, []);
  const handleCategoryChange = useCallback((key: string) => {
    setCategoryKey(key);
    setSelectedKind(null);
  }, []);

  const handleSelect = useCallback((item: PaletteItem) => setSelectedKind(item.kind), []);
  const handleAddSelected = useCallback(() => {
    if (selectedItem) addItem(selectedItem);
  }, [addItem, selectedItem]);

  return (
    <>
      <div className="grid min-h-0 flex-1 grid-cols-[220px_1fr]">
        <StepLibraryCategories
          groups={searchedGroups}
          onSelect={handleCategoryChange}
          selectedKey={categoryKey}
        />
        <StepLibraryGrid
          emptyMessage={search.trim() ? `No steps match "${search}".` : "No steps in this category."}
          errorMessage={errorMessage}
          isLoading={isLoading}
          items={items}
          onActivate={addItem}
          onSearchChange={handleSearchChange}
          onSelect={handleSelect}
          search={search}
          selectedKind={selectedItem?.kind ?? null}
        />
      </div>
      <StepLibraryDescription
        item={selectedItem}
        onAdd={handleAddSelected}
        onShowStep={handleShowStep}
      />
      <StepDetailsDialog
        item={detailsOpen ? selectedItem : null}
        onOpenChange={setDetailsOpen}
        plugin={selectedPlugin}
      />
    </>
  );
}
