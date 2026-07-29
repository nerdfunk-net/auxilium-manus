"use client";

import dynamic from "next/dynamic";
import { loader } from "@monaco-editor/react";

import type { TemplateType } from "../types";

// @monaco-editor/react defaults to fetching Monaco from the jsdelivr CDN at
// runtime. That fails silently in air-gapped environments, leaving the editor
// stuck on the loading placeholder forever. Point it at the self-hosted copy
// in public/vs (populated by scripts/copy-monaco-editor.mjs) instead.
loader.config({ paths: { vs: "/vs" } });

const MonacoEditor = dynamic(() => import("@monaco-editor/react"), {
  ssr: false,
  loading: () => (
    <div className="flex h-full min-h-[400px] items-center justify-center bg-muted/30 text-sm text-muted-foreground">
      Loading editor…
    </div>
  ),
});

interface CodeEditorPanelProps {
  value: string;
  language: TemplateType;
  onChange: (value: string) => void;
}

function monacoLanguage(templateType: TemplateType): string {
  if (templateType === "jinja2") {
    return "jinja";
  }
  return "plaintext";
}

export function CodeEditorPanel({ value, language, onChange }: CodeEditorPanelProps) {
  return (
    <MonacoEditor
      height="100%"
      defaultLanguage={monacoLanguage(language)}
      language={monacoLanguage(language)}
      theme="vs-dark"
      value={value}
      onChange={(next) => onChange(next ?? "")}
      options={{
        minimap: { enabled: false },
        fontSize: 13,
        wordWrap: "on",
        scrollBeyondLastLine: false,
        automaticLayout: true,
      }}
    />
  );
}
