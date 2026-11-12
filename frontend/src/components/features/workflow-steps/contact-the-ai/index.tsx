"use client";

import { Search } from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";

import { AttributePathPicker } from "../shared/attribute-path-picker";
import { ContactTheAiHelpPanel } from "./help-panel";

const PROMPT_KEY = "prompt";
const SYSTEM_PROMPT_KEY = "system_prompt";
const OUTPUT_ATTRIBUTE_KEY = "output_attribute";
const DEFAULT_OUTPUT_ATTRIBUTE = "ai.response";
const MAX_OUTPUT_TOKENS_KEY = "max_output_tokens";
const TIMEOUT_KEY = "timeout_seconds";

const DEFAULT_PROMPT =
  "Summarize this workflow run for a chat notification in at most five short lines.\n{run_summary}";
const EMPTY_NODES: NonNullable<PluginConfigPanelProps["workflowNodes"]> = [];
const EMPTY_EDGES: NonNullable<PluginConfigPanelProps["workflowEdges"]> = [];

function stringFromConfig(config: Record<string, unknown>, key: string): string {
  const raw = config[key];
  return typeof raw === "string" ? raw : "";
}

function numberTextFromConfig(config: Record<string, unknown>, key: string): string {
  const raw = config[key];
  return typeof raw === "number" || typeof raw === "string" ? String(raw) : "";
}

function ContactTheAiConfigPanel({
  nodeId,
  config,
  onChange,
  workflowNodes = EMPTY_NODES,
  workflowEdges = EMPTY_EDGES,
}: PluginConfigPanelProps) {
  const prompt = useMemo(() => stringFromConfig(config, PROMPT_KEY), [config]);
  const systemPrompt = useMemo(() => stringFromConfig(config, SYSTEM_PROMPT_KEY), [config]);
  const outputAttribute = useMemo(
    () => stringFromConfig(config, OUTPUT_ATTRIBUTE_KEY),
    [config],
  );
  const maxTokens = useMemo(() => numberTextFromConfig(config, MAX_OUTPUT_TOKENS_KEY), [config]);
  const timeout = useMemo(() => numberTextFromConfig(config, TIMEOUT_KEY), [config]);
  const [pickerOpen, setPickerOpen] = useState(false);

  const handlePromptChange = useCallback(
    (event: React.ChangeEvent<HTMLTextAreaElement>) => {
      onChange({ ...config, [PROMPT_KEY]: event.target.value });
    },
    [config, onChange],
  );

  const handleSystemPromptChange = useCallback(
    (event: React.ChangeEvent<HTMLTextAreaElement>) => {
      onChange({ ...config, [SYSTEM_PROMPT_KEY]: event.target.value });
    },
    [config, onChange],
  );

  const handleOutputAttributeChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      onChange({ ...config, [OUTPUT_ATTRIBUTE_KEY]: event.target.value });
    },
    [config, onChange],
  );

  const handleNumberChange = useCallback(
    (key: string) => (event: React.ChangeEvent<HTMLInputElement>) => {
      const text = event.target.value;
      onChange({ ...config, [key]: text === "" ? "" : Number(text) });
    },
    [config, onChange],
  );

  const handleSelectPath = useCallback(
    (path: string) => {
      const separator = prompt === "" || prompt.endsWith("\n") ? "" : " ";
      onChange({ ...config, [PROMPT_KEY]: `${prompt}${separator}{${path}}` });
      setPickerOpen(false);
    },
    [config, onChange, prompt],
  );

  const handleClosePicker = useCallback(() => setPickerOpen(false), []);
  const handleOpenPicker = useCallback(() => setPickerOpen(true), []);

  return (
    <div className="flex flex-col gap-4">
      {/* prompt */}
      <div className="space-y-1.5">
        <span className="font-mono text-xs font-medium">{PROMPT_KEY}</span>
        <div className="flex items-start gap-1.5">
          <Textarea
            className="min-h-24 font-mono text-xs focus-visible:ring-step/40"
            placeholder={DEFAULT_PROMPT}
            value={prompt}
            onChange={handlePromptChange}
          />
          <Button
            type="button"
            variant="outline"
            size="icon"
            className="size-8 shrink-0"
            title="Browse attributes"
            aria-label="Browse attributes for prompt"
            onClick={handleOpenPicker}
          >
            <Search className="size-3.5" aria-hidden />
          </Button>
        </div>
        <p className="text-[11px] leading-4 text-muted-foreground">
          Use <span className="font-mono">{"{run_summary}"}</span>,{" "}
          <span className="font-mono">{"{devices}"}</span>,{" "}
          <span className="font-mono">{"{device_count}"}</span> or{" "}
          <span className="font-mono">{"{path.to.value}"}</span> (first device).
          Everything is redacted before it is sent.
        </p>
        <p className="text-[11px] leading-4 text-warning-foreground">
          A dict such as <span className="font-mono">{"{nautobot}"}</span> is
          sent as JSON: risky (more data leaves, redaction is best-effort) and
          expensive (many tokens per run). Prefer single fields.
        </p>
        {!prompt && <p className="text-[11px] text-warning-foreground">Not configured</p>}
      </div>

      {/* system_prompt */}
      <div className="space-y-1.5">
        <span className="font-mono text-xs font-medium">{SYSTEM_PROMPT_KEY}</span>
        <Textarea
          className="min-h-16 font-mono text-xs focus-visible:ring-step/40"
          placeholder="Optional: tone, language, format"
          value={systemPrompt}
          onChange={handleSystemPromptChange}
        />
      </div>

      {/* output_attribute */}
      <div className="space-y-1.5">
        <span className="font-mono text-xs font-medium">{OUTPUT_ATTRIBUTE_KEY}</span>
        <Input
          className="h-8 font-mono text-xs focus-visible:ring-step/40"
          placeholder={DEFAULT_OUTPUT_ATTRIBUTE}
          value={outputAttribute}
          onChange={handleOutputAttributeChange}
        />
        <p className="text-[11px] leading-4 text-muted-foreground">
          Where the answer is stored on every device, as <span className="font-mono">bag.field</span>.
          Use it later as{" "}
          <span className="font-mono">{`{${outputAttribute.trim() || DEFAULT_OUTPUT_ATTRIBUTE}}`}</span>
          . It is also shown in the run view.
        </p>
      </div>

      {/* max_output_tokens */}
      <div className="space-y-1.5">
        <span className="font-mono text-xs font-medium">{MAX_OUTPUT_TOKENS_KEY}</span>
        <Input
          className="h-8 font-mono text-xs focus-visible:ring-step/40"
          min={1}
          max={4096}
          placeholder="1024"
          type="number"
          value={maxTokens}
          onChange={handleNumberChange(MAX_OUTPUT_TOKENS_KEY)}
        />
      </div>

      {/* timeout_seconds */}
      <div className="space-y-1.5">
        <span className="font-mono text-xs font-medium">{TIMEOUT_KEY}</span>
        <Input
          className="h-8 font-mono text-xs focus-visible:ring-step/40"
          min={1}
          max={600}
          placeholder="120"
          type="number"
          value={timeout}
          onChange={handleNumberChange(TIMEOUT_KEY)}
        />
      </div>

      <AttributePathPicker
        open={pickerOpen}
        onClose={handleClosePicker}
        onSelect={handleSelectPath}
        nodeId={nodeId}
        workflowNodes={workflowNodes}
        workflowEdges={workflowEdges}
      />
    </div>
  );
}

export const ContactTheAiPlugin: PluginUIComponent = {
  ConfigPanel: ContactTheAiConfigPanel,
  HelpPanel: ContactTheAiHelpPanel,
};
