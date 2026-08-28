"use client";

import dynamic from "next/dynamic";
import { loader } from "@monaco-editor/react";

// Self-hosted Monaco copy — see code-editor-panel.tsx for why this is
// required (the default jsdelivr CDN loader fails silently offline).
loader.config({ paths: { vs: "/vs" } });

const MonacoDiffEditor = dynamic(
  () => import("@monaco-editor/react").then((mod) => mod.DiffEditor),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-full min-h-[300px] items-center justify-center bg-muted/30 text-sm text-muted-foreground">
        Loading diff…
      </div>
    ),
  },
);

interface WorkflowGitDiffViewerProps {
  original: string;
  modified: string;
}

export function WorkflowGitDiffViewer({ original, modified }: WorkflowGitDiffViewerProps) {
  return (
    <MonacoDiffEditor
      height="100%"
      language="json"
      original={original}
      modified={modified}
      theme="vs-dark"
      options={{
        readOnly: true,
        renderSideBySide: true,
        minimap: { enabled: false },
        fontSize: 12,
        scrollBeyondLastLine: false,
        automaticLayout: true,
      }}
    />
  );
}
