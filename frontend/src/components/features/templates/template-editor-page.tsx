"use client";

import {
  ArrowLeft,
  BookOpen,
  Download,
  FileCode,
  Play,
  RefreshCw,
  Save,
  Settings2,
  Sparkles,
  X,
} from "lucide-react";
import { Suspense, useCallback, useMemo } from "react";

import { AssistantPanel } from "@/components/features/ai-assistant/components/assistant-panel";
import { useAiAssistantAvailable } from "@/components/features/ai-assistant/hooks/use-ai-assistant-available";
import { useAssistantSessionOpen } from "@/components/features/ai-assistant/hooks/use-assistant-session-open";
import type { AssistantContext } from "@/components/features/ai-assistant/types/ai-assistant";
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
import { OptionsDialog } from "./components/options-dialog";
import { RenderedOutputDialog } from "./components/rendered-output-dialog";
import { ResizableSplit } from "./components/resizable-split";
import { VariablesPanel } from "./components/variables-panel";
import { useTemplateEditor } from "./hooks/use-template-editor";

const MAX_CONTEXT_VALUE_CHARS = 50000;

function TemplateEditorContent() {
  const editor = useTemplateEditor();
  const assistantAvailable = useAiAssistantAvailable();
  const assistantSessionKey = `template_editor:${editor.templateId ?? "new"}`;
  const {
    open: assistantOpen,
    setOpen: setAssistantOpen,
    toggle: toggleAssistant,
  } = useAssistantSessionOpen(assistantSessionKey);
  const {
    name,
    description,
    templateType,
    content,
    setContent,
    variableManager: { variables },
  } = editor;

  // Sent with every assistant turn. Device/run (auto-filled) variables go by name only: their
  // values are never sent (the server also drops them).
  const getAssistantContext = useCallback(
    (): AssistantContext => ({
      surface: "template_editor",
      name,
      description: description || null,
      template_type: templateType,
      content,
      variables: variables
        .filter((variable) => variable.name)
        .map((variable) => ({
          name: variable.name,
          type: variable.type,
          value: variable.isAutoFilled
            ? ""
            : variable.value.slice(0, MAX_CONTEXT_VALUE_CHARS),
          is_auto: variable.isAutoFilled,
        })),
    }),
    [name, description, templateType, content, variables],
  );
  const proposalTarget = useMemo(
    () => ({ currentContent: content, onApply: setContent }),
    [content, setContent],
  );

  if (editor.isLoading) {
    return (
      <div className="flex items-center justify-center py-24 text-muted-foreground">
        <RefreshCw className="mr-2 size-5 animate-spin" />
        Loading template…
      </div>
    );
  }

  return (
    <div className="flex h-full">
      <div className="h-full min-w-0 flex-1 overflow-y-auto p-6">
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
                  Create and edit Jinja2 templates with variable support and
                  live preview
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              {assistantAvailable && (
                <Button
                  type="button"
                  variant={assistantOpen ? "default" : "outline"}
                  onClick={toggleAssistant}
                >
                  <Sparkles className="size-4" />
                  AI Assistant
                </Button>
              )}
              <Button
                type="button"
                variant="outline"
                onClick={() => editor.router.push("/templates")}
              >
                <ArrowLeft className="size-4" />
                Back
              </Button>
            </div>
          </div>

          <GeneralPanel
            name={editor.name}
            description={editor.description}
            templateType={editor.templateType}
            onNameChange={editor.setName}
            onDescriptionChange={editor.setDescription}
            onTemplateTypeChange={editor.setTemplateType}
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
                variant="outline"
                onClick={() => editor.setOptionsDialogOpen(true)}
              >
                <Settings2 className="size-4" />
                Options
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
              <Button
                type="button"
                disabled={editor.isSaving}
                onClick={editor.handleSave}
              >
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

        <OptionsDialog
          open={editor.optionsDialogOpen}
          onOpenChange={editor.setOptionsDialogOpen}
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
          batfishTargetConfig={editor.batfishTargetConfig}
          onBatfishTargetConfigChange={editor.setBatfishTargetConfig}
          batfishQuestion={editor.batfishQuestion}
          onBatfishQuestionChange={editor.setBatfishQuestion}
          batfishGenericQuestionName={editor.batfishGenericQuestionName}
          onBatfishGenericQuestionNameChange={
            editor.setBatfishGenericQuestionName
          }
          batfishParams={editor.batfishParams}
          onBatfishParamsChange={editor.setBatfishParams}
          batfishEnabled={editor.batfishEnabled}
          onBatfishEnabledChange={editor.setBatfishEnabled}
          onRunBatfishQuery={editor.handleRunBatfishQuery}
          isRunningBatfishQuery={editor.isRunningBatfishQuery}
          canRunBatfishQuery={editor.canRunBatfishQuery}
          batfishResult={editor.batfishResult}
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
      {assistantAvailable && assistantOpen && (
        <aside
          className="flex h-full w-[420px] shrink-0 flex-col gap-3 border-l bg-card p-4"
          aria-label="AI Assistant"
        >
          <div className="flex items-center justify-between">
            <h2 className="flex items-center gap-2 text-sm font-semibold">
              <Sparkles className="size-4" />
              AI Assistant
            </h2>
            <Button
              type="button"
              size="icon"
              variant="ghost"
              onClick={() => setAssistantOpen(false)}
              aria-label="Close assistant"
            >
              <X className="size-4" />
            </Button>
          </div>
          <div className="min-h-0 flex-1">
            <AssistantPanel
              sessionKey={assistantSessionKey}
              placeholder="Describe the template you need, or what to change…"
              getContext={getAssistantContext}
              templateTarget={proposalTarget}
            />
          </div>
        </aside>
      )}
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
