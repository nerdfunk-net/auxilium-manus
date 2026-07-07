"use client";

import dynamic from "next/dynamic";

import type { TemplateType } from "../types";

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
