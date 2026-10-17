"use client";

import { ArrowLeft, FileText, Play, RefreshCw, Save, Sparkles, X } from "lucide-react";
import { Suspense, useCallback, useMemo, useState } from "react";

import { AssistantPanel } from "@/components/features/ai-assistant/components/assistant-panel";
import { useAiAssistantAvailable } from "@/components/features/ai-assistant/hooks/use-ai-assistant-available";
import { useAssistantSessionOpen } from "@/components/features/ai-assistant/hooks/use-assistant-session-open";
import type {
  AssistantContext,
  ConversationScope,
} from "@/components/features/ai-assistant/types/ai-assistant";
import { LabeledSelect } from "@/components/features/reports/components/labeled-select";
import { CanvasErrorBoundary } from "@/components/features/workflows/components/canvas-error-boundary";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { MarkdownView } from "@/components/ui/markdown-view";
import { Textarea } from "@/components/ui/textarea";
import { useReportTemplatePreviewMutation } from "@/hooks/queries/use-report-template-preview-mutation";
import { useReportSnapshotsQuery } from "@/hooks/queries/use-report-snapshots-query";

import { CodeEditorPanel } from "./components/code-editor-panel";
import { ResizableSplit } from "./components/resizable-split";
import { REPORT_CATEGORY } from "./report/constants";
import { ReportVariablesPanel } from "./report/report-variables-panel";
import { useReportTemplateEditor } from "./report/use-report-template-editor";

function ReportTemplateEditorContent() {
  const editor = useReportTemplateEditor();
  const { name, description, content, setContent } = editor;

  const assistantAvailable = useAiAssistantAvailable();
  const assistantSessionKey = `template_editor:${editor.templateId ?? "new-report"}`;
  const conversationScope = useMemo<ConversationScope>(
    () => ({
      surface: "template_editor",
      subjectKey: String(editor.templateId ?? "new-report"),
    }),
    [editor.templateId],
  );
  const {
    open: assistantOpen,
    setOpen: setAssistantOpen,
    toggle: toggleAssistant,
  } = useAssistantSessionOpen(assistantSessionKey);
  const getAssistantContext = useCallback(
    (): AssistantContext => ({
      surface: "template_editor",
      category: REPORT_CATEGORY,
      name,
      description: description || null,
      template_type: "jinja2",
      content,
      variables: [],
    }),
    [name, description, content],
  );
  const proposalTarget = useMemo(
    () => ({ currentContent: content, onApply: setContent }),
    [content, setContent],
  );

  // Preview against a stored snapshot (the data a real report would be rendered with).
  const snapshots = useReportSnapshotsQuery();
  const preview = useReportTemplatePreviewMutation();
  const [snapshotChoice, setSnapshotChoice] = useState("");
  const [previewOpen, setPreviewOpen] = useState(false);
  const snapshotOptions = useMemo(
    () => (snapshots.data ?? []).map((s) => ({ value: String(s.id), label: s.name })),
    [snapshots.data],
  );
  const snapshotId = snapshotChoice || snapshotOptions[0]?.value || "";

  const handlePreview = useCallback(() => {
    if (!snapshotId) return;
    setPreviewOpen(true);
    preview.mutate({ snapshotId: Number(snapshotId), content });
  }, [content, preview, snapshotId]);

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
                <FileText className="h-6 w-6" />
              </div>
              <div>
                <h1 className="text-3xl font-bold text-foreground">
                  {editor.isEditMode ? "Edit Report Template" : "New Report Template"}
                </h1>
                <p className="mt-1 text-muted-foreground">
                  A Jinja2 template that turns a generated report into Markdown text
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              {assistantAvailable ? (
                <Button
                  type="button"
                  variant={assistantOpen ? "default" : "outline"}
                  onClick={toggleAssistant}
                >
                  <Sparkles className="size-4" />
                  AI Assistant
                </Button>
              ) : null}
              <Button type="button" variant="outline" onClick={() => editor.router.push("/templates")}>
                <ArrowLeft className="size-4" />
                Back
              </Button>
            </div>
          </div>

          {editor.loadError ? (
            <Alert variant="destructive">
              <AlertDescription>{editor.loadError}</AlertDescription>
            </Alert>
          ) : null}

          <div className="grid gap-4 rounded-lg border bg-card p-4 md:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="report-template-name">Name</Label>
              <Input
                id="report-template-name"
                value={name}
                onChange={(event) => editor.setName(event.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="report-template-description">Description</Label>
              <Textarea
                id="report-template-description"
                rows={1}
                value={description}
                onChange={(event) => editor.setDescription(event.target.value)}
              />
            </div>
          </div>

          <ResizableSplit
            storageKey="report-template-editor:variables-width"
            minHeight={480}
            left={
              <div className="h-full overflow-hidden rounded-lg border bg-card">
                <ReportVariablesPanel />
              </div>
            }
            right={
              <div className="h-full min-h-[480px] overflow-hidden rounded-lg border">
                <CanvasErrorBoundary fallbackTitle="The editor failed to render">
                  <CodeEditorPanel value={content} language="jinja2" onChange={setContent} />
                </CanvasErrorBoundary>
              </div>
            }
          />

          <div className="flex flex-wrap items-center justify-between gap-3 border-t pt-4">
            <div className="flex items-center gap-2">
              <LabeledSelect
                value={snapshotId}
                onChange={setSnapshotChoice}
                options={snapshotOptions}
                placeholder={snapshots.isLoading ? "Loading snapshots…" : "No snapshots yet"}
                ariaLabel="Snapshot to preview with"
                className="h-9 w-72 text-sm"
              />
              <Button
                type="button"
                variant="outline"
                disabled={!snapshotId || preview.isPending || !content.trim()}
                onClick={handlePreview}
              >
                {preview.isPending ? (
                  <RefreshCw className="size-4 animate-spin" />
                ) : (
                  <Play className="size-4" />
                )}
                Preview
              </Button>
            </div>
            <Button type="button" disabled={editor.isSaving} onClick={editor.save}>
              {editor.isSaving ? (
                <RefreshCw className="size-4 animate-spin" />
              ) : (
                <Save className="size-4" />
              )}
              {editor.isEditMode ? "Update Template" : "Save Template"}
            </Button>
          </div>
        </div>

        <Dialog open={previewOpen} onOpenChange={setPreviewOpen}>
          <DialogContent className="max-h-[85vh] overflow-hidden sm:max-w-4xl">
            <DialogHeader>
              <DialogTitle>Preview</DialogTitle>
              <DialogDescription>
                Rendered with the selected snapshot. Nothing is saved.
              </DialogDescription>
            </DialogHeader>
            <div className="max-h-[65vh] overflow-auto">
              {preview.isError ? (
                <Alert variant="destructive">
                  <AlertDescription>{preview.error.message}</AlertDescription>
                </Alert>
              ) : preview.data?.error ? (
                <Alert variant="destructive">
                  <AlertDescription>{preview.data.error}</AlertDescription>
                </Alert>
              ) : preview.data?.markdown !== undefined && preview.data.markdown !== null ? (
                <MarkdownView markdown={preview.data.markdown} />
              ) : (
                <RefreshCw className="size-4 animate-spin text-muted-foreground" />
              )}
            </div>
          </DialogContent>
        </Dialog>
      </div>
      {assistantAvailable && assistantOpen ? (
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
              conversationScope={conversationScope}
              placeholder="Describe the report text you need, or what to change…"
              getContext={getAssistantContext}
              templateTarget={proposalTarget}
            />
          </div>
        </aside>
      ) : null}
    </div>
  );
}

export function ReportTemplateEditorPage() {
  return (
    <Suspense
      fallback={
        <div className="flex items-center justify-center py-24 text-muted-foreground">
          <RefreshCw className="mr-2 size-5 animate-spin" />
          Loading editor…
        </div>
      }
    >
      <ReportTemplateEditorContent />
    </Suspense>
  );
}
