"use client";

import { ArrowLeft, BookOpen, Download, FileCode, Play, RefreshCw, Save } from "lucide-react";
import { Suspense } from "react";

import { CanvasErrorBoundary } from "@/components/features/workflows/components/canvas-error-boundary";
import { Button } from "@/components/ui/button";
import { MarkdownEditor } from "@/components/ui/markdown-editor";
import { cn } from "@/lib/utils";

import { AddVariableDialog } from "./components/add-variable-dialog";
import { CodeEditorPanel } from "./components/code-editor-panel";
import { AttributesDialog } from "./components/attributes-dialog";
import { ConfigureCommandsDialog } from "./components/configure-commands-dialog";
import { GeneralPanel } from "./components/general-panel";
import { JinjaHelpDialog } from "./components/jinja-help-dialog";
import { LinkWorkflowDialog } from "./components/link-workflow-dialog";
import { LoadVariablesDialog } from "./dialogs/load-variables-dialog";
import { NetmikoOptionsPanel } from "./components/netmiko-options-panel";
import { RenderedOutputDialog } from "./components/rendered-output-dialog";
import { ResizableSplit } from "./components/resizable-split";
import { VariablesPanel } from "./components/variables-panel";
import { useTemplateEditor } from "./hooks/use-template-editor";

function TemplateEditorContent() {
  const editor = useTemplateEditor();

  if (editor.isLoading) {
    return (
      <div className="flex items-center justify-center py-24 text-muted-foreground">
        <RefreshCw className="mr-2 size-5 animate-spin" />
        Loading template…
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="w-full space-y-6">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <div className="flex size-12 items-center justify-center rounded-xl bg-primary/10 text-primary">
              <FileCode className="h-6 w-6" />
            </div>
            <div>
              <h1 className="text-3xl font-bold text-foreground">
                {editor.isEditMode ? "Edit Template" : "Template Editor"}
              </h1>
              <p className="mt-1 text-muted-foreground">
                Create and edit Jinja2 templates with variable support and live preview
              </p>
            </div>
          </div>
          <Button type="button" variant="outline" onClick={() => editor.router.push("/templates")}>
            <ArrowLeft className="size-4" />
            Back
          </Button>
        </div>

        <GeneralPanel
          name={editor.name}
          description={editor.description}
          templateType={editor.templateType}
          onNameChange={editor.setName}
          onDescriptionChange={editor.setDescription}
          onTemplateTypeChange={editor.setTemplateType}
        />

        <NetmikoOptionsPanel
          sources={editor.sources}
          sourceId={editor.effectiveSourceId}
          sourceReady={editor.sourceReady}
          commandCount={editor.cleanedCommandCount}
          attributeCount={editor.attributeCount}
          credentialId={editor.credentialId}
          getConfigs={editor.getDeviceConfigs}
          isFetchingConfigs={editor.isFetchingConfigs}
          canFetchConfigs={editor.canFetchConfigs}
          onFetchConfigs={editor.handleFetchConfigs}
          onSourceChange={editor.setSourceId}
          onSelectDevice={editor.setSelectedDevice}
          onConfigureCommands={() => editor.setCommandsDialogOpen(true)}
          onConfigureAttributes={() => editor.setAttributesDialogOpen(true)}
          onCredentialChange={editor.setCredentialId}
          onGetConfigsChange={editor.setGetDeviceConfigs}
        />

        <ResizableSplit
          storageKey="template-editor:variables-width"
          minHeight={480}
          left={
            <div className="h-full overflow-hidden rounded-lg border bg-card">
              <VariablesPanel
                variables={editor.variableManager.variables}
                selectedId={editor.selectedVariableId}
                onSelect={editor.setSelectedVariableId}
                onAdd={() => editor.setAddVariableOpen(true)}
                onLoadFromFile={() => editor.setLoadVariablesOpen(true)}
                onHelp={() => editor.setVariablesHelpOpen(true)}
                onRemove={editor.variableManager.removeVariable}
                onUpdateValue={editor.variableManager.updateVariableValue}
                onLinkWorkflow={() => editor.setLinkWorkflowDialogOpen(true)}
              />
            </div>
          }
          right={
            <div className="h-full min-h-[480px] overflow-hidden rounded-lg border">
              <div className={cn("h-full", editor.wikiOpen && "hidden")}>
                <CanvasErrorBoundary fallbackTitle="The editor failed to render">
                  <CodeEditorPanel
                    value={editor.content}
                    language={editor.templateType}
                    onChange={editor.setContent}
                  />
                </CanvasErrorBoundary>
              </div>
              <div className={cn("h-full p-3", !editor.wikiOpen && "hidden")}>
                <MarkdownEditor
                  value={editor.notes}
                  onChange={editor.setNotes}
                  placeholder="Document this template in Markdown: purpose, variables, gotchas, examples…"
                  className="flex h-full min-h-0 flex-col gap-2"
                />
              </div>
            </div>
          }
        />

        <div className="flex items-center justify-between border-t pt-4">
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              disabled={editor.renderer.isRendering || !editor.content.trim()}
              onClick={editor.handleRender}
            >
              {editor.renderer.isRendering ? (
                <RefreshCw className="size-4 animate-spin" />
              ) : (
                <Play className="size-4" />
              )}
              Show Rendered Template
            </Button>
            <Button
              type="button"
              variant={editor.wikiOpen ? "default" : "outline"}
              onClick={() => editor.setWikiOpen((open) => !open)}
            >
              <BookOpen className="size-4" />
              Wiki
            </Button>
          </div>

          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              disabled={!editor.name.trim()}
              onClick={editor.handleExport}
            >
              <Download className="size-4" />
              Export
            </Button>
            <Button type="button" disabled={editor.isSaving} onClick={editor.handleSave}>
              {editor.isSaving ? (
                <RefreshCw className="size-4 animate-spin" />
              ) : (
                <Save className="size-4" />
              )}
              {editor.isEditMode ? "Update Template" : "Save Template"}
            </Button>
          </div>
        </div>
      </div>

      <RenderedOutputDialog
        open={editor.renderer.showDialog}
        result={editor.renderer.result}
        onOpenChange={editor.renderer.setShowDialog}
      />

      <AddVariableDialog
        open={editor.addVariableOpen}
        existingNames={editor.existingVariableNames}
        onClose={() => editor.setAddVariableOpen(false)}
        onAdd={editor.handleAddVariable}
      />

      <LoadVariablesDialog
        open={editor.loadVariablesOpen}
        existingNames={editor.existingVariableNames}
        autoNames={editor.autoVariableNames}
        onClose={() => editor.setLoadVariablesOpen(false)}
        onLoad={editor.handleLoadVariables}
      />

      <JinjaHelpDialog
        open={editor.variablesHelpOpen}
        onClose={() => editor.setVariablesHelpOpen(false)}
      />

      <ConfigureCommandsDialog
        open={editor.commandsDialogOpen}
        commands={editor.commands}
        useTextfsm={editor.useTextfsm}
        canExecute={editor.canExecuteCommands}
        isExecuting={editor.isExecutingCommands}
        executeHint={editor.executeHint}
        onOpenChange={editor.setCommandsDialogOpen}
        onCommandsChange={editor.setCommands}
        onUseTextfsmChange={editor.setUseTextfsm}
        onExecute={editor.handleExecuteCommands}
      />

      <AttributesDialog
        open={editor.attributesDialogOpen}
        value={editor.attributes}
        onOpenChange={editor.setAttributesDialogOpen}
        onChange={editor.setAttributes}
      />

      <LinkWorkflowDialog
        open={editor.linkWorkflowDialogOpen}
        workflows={editor.workflows}
        selectedId={editor.referenceWorkflowId}
        onSelect={editor.setReferenceWorkflowId}
        onClose={() => editor.setLinkWorkflowDialogOpen(false)}
      />
    </div>
  );
}

export function TemplateEditorPage() {
  return (
    <Suspense
      fallback={
        <div className="flex items-center justify-center py-24 text-muted-foreground">
          <RefreshCw className="mr-2 size-5 animate-spin" />
          Loading editor…
        </div>
      }
    >
      <TemplateEditorContent />
    </Suspense>
  );
}
