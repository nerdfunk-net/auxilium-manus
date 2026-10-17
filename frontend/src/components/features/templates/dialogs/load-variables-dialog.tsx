"use client";

import { useCallback, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { GitRepositorySelectDialog } from "@/components/features/workflow-steps/shared/git-repository-select-dialog";
import { GitRepositoryValue } from "@/components/features/workflow-steps/shared/git-repository-value";
import { useGitFileContentParsedQuery } from "@/hooks/queries/use-git-file-content-query";
import {
  useParseStructuredMutation,
  type StructuredFormat,
} from "@/hooks/queries/use-parse-structured-mutation";

import type { MergeVariablesMode } from "../hooks/use-template-variables";
import {
  flattenVariablesRecord,
  validateDestinationPath,
  type ParsedVariableEntry,
} from "../utils/parse-variables";

/** Matches `read_from_file/config.py::get_config()` and `read-from-file/config.ts`. */
const DEFAULT_DESTINATION_PATH = "data";

interface LoadVariablesDialogProps {
  open: boolean;
  existingNames: string[];
  autoNames: string[];
  onClose: () => void;
  onLoad: (entries: ParsedVariableEntry[], mode: MergeVariablesMode) => void;
}

type TabValue = "upload" | "paste" | "git";

const FORMAT_OPTIONS: { value: StructuredFormat; label: string }[] = [
  { value: "auto", label: "Auto" },
  { value: "yaml", label: "YAML" },
  { value: "json", label: "JSON" },
];

function formatFromFilename(name: string): StructuredFormat {
  const lower = name.toLowerCase();
  if (lower.endsWith(".json")) return "json";
  if (lower.endsWith(".yaml") || lower.endsWith(".yml")) return "yaml";
  return "auto";
}

function getErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Could not parse the file.";
}

export function LoadVariablesDialog({
  open,
  existingNames,
  autoNames,
  onClose,
  onLoad,
}: LoadVariablesDialogProps) {
  const [tab, setTab] = useState<TabValue>("upload");
  const [manualEntries, setManualEntries] = useState<ParsedVariableEntry[] | null>(null);
  const [manualError, setManualError] = useState<string | null>(null);
  const [mode, setMode] = useState<MergeVariablesMode>("skip");
  const [destinationPath, setDestinationPath] = useState(DEFAULT_DESTINATION_PATH);

  const [pasteText, setPasteText] = useState("");
  const [pasteFormat, setPasteFormat] = useState<StructuredFormat>("auto");

  const [gitRepositoryId, setGitRepositoryId] = useState<number | null>(null);
  const [gitPath, setGitPath] = useState("");
  const [gitPickerOpen, setGitPickerOpen] = useState(false);
  const [gitRequested, setGitRequested] = useState(false);

  const parseMutation = useParseStructuredMutation();
  const gitQuery = useGitFileContentParsedQuery(
    gitRepositoryId,
    gitPath,
    open && tab === "git" && gitRequested,
  );

  // Validate the destination path once; the same message gates every tab's
  // action button and is surfaced inline.
  const destinationPathError = useMemo(() => {
    try {
      validateDestinationPath(destinationPath);
      return null;
    } catch (err) {
      return getErrorMessage(err);
    }
  }, [destinationPath]);

  // Derive the git tab's parsed entries straight from the query result — no
  // effect / setState needed.
  const gitResult = useMemo<
    { entries: ParsedVariableEntry[] } | { error: string } | null
  >(() => {
    if (tab !== "git" || !gitRequested) return null;
    if (gitQuery.error) return { error: getErrorMessage(gitQuery.error) };
    if (!gitQuery.data) return null;
    try {
      return {
        entries: flattenVariablesRecord(gitQuery.data.parsed, destinationPath),
      };
    } catch (err) {
      return { error: getErrorMessage(err) };
    }
  }, [tab, gitRequested, gitQuery.data, gitQuery.error, destinationPath]);

  const entries = tab === "git" ? (gitResult && "entries" in gitResult ? gitResult.entries : null) : manualEntries;
  const error = tab === "git" ? (gitResult && "error" in gitResult ? gitResult.error : null) : manualError;

  const reset = useCallback(() => {
    setTab("upload");
    setManualEntries(null);
    setManualError(null);
    setMode("skip");
    setDestinationPath(DEFAULT_DESTINATION_PATH);
    setPasteText("");
    setPasteFormat("auto");
    setGitRepositoryId(null);
    setGitPath("");
    setGitRequested(false);
  }, []);

  const handleClose = useCallback(() => {
    reset();
    onClose();
  }, [reset, onClose]);

  const applyManual = useCallback(
    (parsed: unknown) => {
      try {
        setManualEntries(flattenVariablesRecord(parsed, destinationPath));
        setManualError(null);
      } catch (err) {
        setManualEntries(null);
        setManualError(getErrorMessage(err));
      }
    },
    [destinationPath],
  );

  const handleChooseFile = useCallback(() => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".yaml,.yml,.json,application/json,text/yaml";
    input.onchange = async (event) => {
      const file = (event.target as HTMLInputElement).files?.[0];
      if (!file) return;
      setManualError(null);
      setManualEntries(null);
      try {
        const text = await file.text();
        const result = await parseMutation.mutateAsync({
          content: text,
          format: formatFromFilename(file.name),
        });
        applyManual(result.parsed);
      } catch (err) {
        setManualError(getErrorMessage(err));
      }
    };
    input.click();
  }, [parseMutation, applyManual]);

  const handleParsePaste = useCallback(async () => {
    setManualError(null);
    setManualEntries(null);
    try {
      const result = await parseMutation.mutateAsync({
        content: pasteText,
        format: pasteFormat,
      });
      applyManual(result.parsed);
    } catch (err) {
      setManualError(getErrorMessage(err));
    }
  }, [parseMutation, pasteText, pasteFormat, applyManual]);

  const handleTabChange = useCallback((value: string) => {
    setTab(value as TabValue);
    setManualEntries(null);
    setManualError(null);
    setGitRequested(false);
  }, []);

  const preview = useMemo(() => {
    if (!entries) return [];
    const autoSet = new Set(autoNames);
    const existingSet = new Set(existingNames);
    return entries.map((entry) => ({
      ...entry,
      status: autoSet.has(entry.name)
        ? ("reserved" as const)
        : existingSet.has(entry.name)
          ? ("exists" as const)
          : ("new" as const),
    }));
  }, [entries, autoNames, existingNames]);

  const loadableCount = preview.filter(
    (item) => item.status === "new" || (item.status === "exists" && mode === "overwrite"),
  ).length;

  const handleConfirm = useCallback(() => {
    if (!entries) return;
    onLoad(entries, mode);
    handleClose();
  }, [entries, mode, onLoad, handleClose]);

  const gitLoading = gitRequested && gitQuery.isFetching;

  return (
    <Dialog open={open} onOpenChange={(next) => !next && handleClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Load Variables from File</DialogTitle>
          <DialogDescription>
            Populate template variables from a YAML or JSON file. Only top-level keys are
            read; each is loaded as{" "}
            <span className="font-mono">{"<destination path>"}</span>.
            <span className="font-mono">{"<key>"}</span> so the template renders the same
            way here as it will in a workflow. Nested values are stored as JSON.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-1.5">
          <Label htmlFor="load-variables-destination-path" className="text-xs">
            Destination path
          </Label>
          <Input
            id="load-variables-destination-path"
            className="h-8 font-mono text-xs"
            placeholder={DEFAULT_DESTINATION_PATH}
            value={destinationPath}
            onChange={(event) => setDestinationPath(event.target.value)}
          />
          <p className="text-[11px] text-muted-foreground">
            Match the <span className="font-medium">Read from File</span> step&apos;s
            destination path. Example: with{" "}
            <span className="font-mono">{DEFAULT_DESTINATION_PATH}</span>, a top-level{" "}
            <span className="font-mono">snmp1</span> key is used as{" "}
            <span className="font-mono">
              {"{{ "}
              {DEFAULT_DESTINATION_PATH}.snmp1{" }}"}
            </span>
            .
          </p>
          {destinationPathError ? (
            <p className="text-xs text-destructive">{destinationPathError}</p>
          ) : null}
        </div>

        <Tabs value={tab} onValueChange={handleTabChange} className="space-y-3">
          <TabsList className="grid w-full grid-cols-3">
            <TabsTrigger value="upload">Upload</TabsTrigger>
            <TabsTrigger value="paste">Paste</TabsTrigger>
            <TabsTrigger value="git">Git repo</TabsTrigger>
          </TabsList>

          <TabsContent value="upload" className="space-y-2">
            <Button
              type="button"
              variant="outline"
              className="w-full"
              disabled={parseMutation.isPending || destinationPathError !== null}
              onClick={handleChooseFile}
            >
              {parseMutation.isPending ? "Parsing…" : "Choose file…"}
            </Button>
            <p className="text-[11px] text-muted-foreground">
              Accepts <span className="font-mono">.yaml</span>,{" "}
              <span className="font-mono">.yml</span>, <span className="font-mono">.json</span>.
            </p>
          </TabsContent>

          <TabsContent value="paste" className="space-y-2">
            <Textarea
              rows={10}
              className="font-mono text-xs"
              placeholder={'region: emea\ndns:\n  - 1.1.1.1'}
              value={pasteText}
              onChange={(event) => setPasteText(event.target.value)}
            />
            <div className="flex items-center gap-2">
              <Select
                value={pasteFormat}
                onValueChange={(value) => setPasteFormat(value as StructuredFormat)}
              >
                <SelectTrigger className="h-8 w-28 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {FORMAT_OPTIONS.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="h-8 text-xs"
                disabled={
                  !pasteText.trim() ||
                  parseMutation.isPending ||
                  destinationPathError !== null
                }
                onClick={handleParsePaste}
              >
                {parseMutation.isPending ? "Parsing…" : "Parse"}
              </Button>
            </div>
          </TabsContent>

          <TabsContent value="git" className="space-y-2">
            <GitRepositoryValue repositoryId={gitRepositoryId} />
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="h-7 w-full text-xs"
              onClick={() => setGitPickerOpen(true)}
            >
              {gitRepositoryId !== null ? "Change repository" : "Choose repository"}
            </Button>
            <Input
              className="h-8 font-mono text-xs"
              placeholder="data/site-defaults.yaml"
              value={gitPath}
              onChange={(event) => setGitPath(event.target.value)}
            />
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="h-8 w-full text-xs"
              disabled={
                gitRepositoryId === null ||
                !gitPath.trim() ||
                gitLoading ||
                destinationPathError !== null
              }
              onClick={() => setGitRequested(true)}
            >
              {gitLoading ? "Loading…" : "Load file"}
            </Button>
            <GitRepositorySelectDialog
              open={gitPickerOpen}
              selectedRepositoryId={gitRepositoryId}
              idPrefix="load-variables-git-repository"
              onClose={() => setGitPickerOpen(false)}
              onSave={(value) => setGitRepositoryId(value)}
            />
          </TabsContent>
        </Tabs>

        {error ? <p className="text-xs text-destructive">{error}</p> : null}

        {preview.length > 0 ? (
          <div className="space-y-2">
            <div className="max-h-48 space-y-1 overflow-auto rounded-md border p-2">
              {preview.map((item) => (
                <div
                  key={item.name}
                  className="flex items-center justify-between gap-2 text-xs"
                >
                  <span className="truncate font-mono">{item.name}</span>
                  <Badge
                    variant={item.status === "reserved" ? "outline" : "secondary"}
                    className="h-4 rounded px-1 text-[10px]"
                  >
                    {item.status}
                  </Badge>
                </div>
              ))}
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground">On name collision:</span>
              <Button
                type="button"
                size="sm"
                variant={mode === "skip" ? "secondary" : "ghost"}
                className="h-7 text-xs"
                onClick={() => setMode("skip")}
              >
                Skip existing
              </Button>
              <Button
                type="button"
                size="sm"
                variant={mode === "overwrite" ? "secondary" : "ghost"}
                className="h-7 text-xs"
                onClick={() => setMode("overwrite")}
              >
                Overwrite existing
              </Button>
            </div>
            <p className="text-[11px] text-muted-foreground">
              {loadableCount} variable{loadableCount === 1 ? "" : "s"} will be applied.
              Reserved names are always skipped.
            </p>
          </div>
        ) : null}

        <DialogFooter>
          <Button type="button" variant="outline" onClick={handleClose}>
            Cancel
          </Button>
          <Button
            type="button"
            disabled={!entries || entries.length === 0 || destinationPathError !== null}
            onClick={handleConfirm}
          >
            Load Variables
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
