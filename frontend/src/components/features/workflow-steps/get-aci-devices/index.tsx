"use client";

import { X } from "lucide-react";
import { useCallback, useId, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";
import {
  useGetAciDevicesPreviewMutation,
  type AciDevicePreview,
} from "@/hooks/queries/use-get-aci-devices-preview-mutation";

import {
  ACI_SOURCE_ID_KEY,
  aciSourceIdFromConfig,
} from "../shared/aci-source-config";
import { AciSourceSelectDialog } from "../shared/aci-source-select-dialog";
import {
  FanOutConfigSection,
  fanOutFromConfig,
  type FanOutConfig,
} from "../shared/fan-out-config";
import {
  activeFilters,
  FILTER_KINDS,
  filtersFromConfig,
  presentKinds,
  toggleOption,
  type FilterKey,
  type FilterKind,
  type FilterValue,
} from "./filter-kinds";
import { GetAciDevicesHelpPanel } from "./help-panel";
import { AciDevicesPreviewDialog } from "./preview-dialog";

const FILTERS_KEY = "filters";
const ALLOW_ALL_KEY = "allow_all";
const MAX_DEVICES_KEY = "max_devices";

function maxDevicesFromConfig(config: Record<string, unknown>): number | null {
  const raw = config[MAX_DEVICES_KEY];
  return typeof raw === "number" && Number.isInteger(raw) && raw > 0 ? raw : null;
}

interface FilterRowProps {
  kind: FilterKind;
  value: FilterValue;
  onChange: (key: FilterKey, value: FilterValue) => void;
  onRemove: (key: FilterKey) => void;
}

function FilterRow({ kind, value, onChange, onRemove }: FilterRowProps) {
  const idPrefix = useId();
  const selected = useMemo(() => (Array.isArray(value) ? value : []), [value]);

  const handleText = useCallback(
    (text: string) => {
      // Blank lines are kept while typing (stripped only when sent / counted) so the
      // cursor is not yanked away right after pressing Enter.
      onChange(kind.key, kind.single ? text : text.split("\n"));
    },
    [kind.key, kind.single, onChange],
  );

  const handleOption = useCallback(
    (option: string) => {
      onChange(kind.key, toggleOption(selected, option, kind.options ?? []));
    },
    [kind.key, kind.options, onChange, selected],
  );

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <span className="font-mono text-xs font-medium">{kind.key}</span>
        <Button
          className="size-6"
          size="icon"
          type="button"
          variant="ghost"
          title={`Remove ${kind.label} filter`}
          aria-label={`Remove ${kind.label} filter`}
          onClick={() => onRemove(kind.key)}
        >
          <X className="size-3.5 text-muted-foreground" aria-hidden />
        </Button>
      </div>
      {kind.options ? (
        <div className="flex flex-wrap gap-x-4 gap-y-1.5">
          {kind.options.map((option) => {
            const id = `${idPrefix}-${option}`;
            return (
              <div key={option} className="flex items-center gap-1.5">
                <Checkbox
                  id={id}
                  checked={selected.includes(option)}
                  onCheckedChange={() => handleOption(option)}
                />
                <Label className="font-mono text-xs" htmlFor={id}>
                  {option}
                </Label>
              </div>
            );
          })}
        </div>
      ) : kind.single ? (
        <Input
          className="h-7 font-mono text-xs"
          placeholder={kind.placeholder}
          value={typeof value === "string" ? value : ""}
          onChange={(e) => handleText(e.target.value)}
        />
      ) : (
        <Textarea
          className="min-h-[56px] font-mono text-xs"
          placeholder={kind.placeholder}
          value={selected.join("\n")}
          onChange={(e) => handleText(e.target.value)}
        />
      )}
      <p className="text-[11px] text-muted-foreground">{kind.hint}</p>
    </div>
  );
}

function GetAciDevicesConfigPanel({ config, onChange }: PluginConfigPanelProps) {
  const sourceId = useMemo(() => aciSourceIdFromConfig(config), [config]);
  const filters = useMemo(() => filtersFromConfig(config), [config]);
  const shownKinds = useMemo(() => presentKinds(filters), [filters]);
  const unusedKinds = useMemo(
    () => FILTER_KINDS.filter((kind) => filters[kind.key] === undefined),
    [filters],
  );
  const active = useMemo(() => activeFilters(filters), [filters]);
  const hasFilters = Object.keys(active).length > 0;
  const allowAll = Boolean(config[ALLOW_ALL_KEY]);
  const maxDevices = useMemo(() => maxDevicesFromConfig(config), [config]);
  const fanOut = useMemo(() => fanOutFromConfig(config), [config]);

  const [sourceOpen, setSourceOpen] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewDevices, setPreviewDevices] = useState<AciDevicePreview[]>([]);
  const [previewTruncated, setPreviewTruncated] = useState(false);

  const {
    mutateAsync: runPreview,
    isPending: previewPending,
    isError: previewIsError,
    error: previewError,
  } = useGetAciDevicesPreviewMutation();

  const isConfigured = Boolean(sourceId) && (hasFilters || allowAll);

  const handleSourceIdChange = useCallback(
    (newSourceId: string) => {
      onChange({ ...config, [ACI_SOURCE_ID_KEY]: newSourceId });
    },
    [config, onChange],
  );

  const setFilter = useCallback(
    (key: FilterKey, value: FilterValue) => {
      onChange({ ...config, [FILTERS_KEY]: { ...filters, [key]: value } });
    },
    [config, filters, onChange],
  );

  const handleAddFilter = useCallback(
    (key: string) => {
      const kind = FILTER_KINDS.find((candidate) => candidate.key === key);
      if (kind) {
        setFilter(kind.key, kind.single ? "" : []);
      }
    },
    [setFilter],
  );

  const handleRemoveFilter = useCallback(
    (key: FilterKey) => {
      const remaining = Object.fromEntries(
        Object.entries(filters).filter(([existing]) => existing !== key),
      );
      onChange({ ...config, [FILTERS_KEY]: remaining });
    },
    [config, filters, onChange],
  );

  const handleAllowAllChange = useCallback(
    (checked: boolean) => {
      onChange({ ...config, [ALLOW_ALL_KEY]: checked });
    },
    [config, onChange],
  );

  const handleMaxDevicesChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const parsed = Number.parseInt(e.target.value, 10);
      onChange({
        ...config,
        [MAX_DEVICES_KEY]: Number.isFinite(parsed) && parsed > 0 ? parsed : null,
      });
    },
    [config, onChange],
  );

  const handleFanOutChange = useCallback(
    (patch: Partial<FanOutConfig>) => {
      onChange({ ...config, fan_out: { ...fanOut, ...patch } });
    },
    [config, fanOut, onChange],
  );

  const handleShowPreview = useCallback(async () => {
    try {
      const result = await runPreview({ source_id: sourceId, filters: active });
      setPreviewDevices(result.devices);
      setPreviewTruncated(result.truncated);
      setPreviewOpen(true);
    } catch {
      // error state is surfaced via previewIsError / previewError below
    }
  }, [runPreview, sourceId, active]);

  return (
    <div className="flex flex-col gap-4">
      {/* aci_source_id */}
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">{ACI_SOURCE_ID_KEY}</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            aci
          </Badge>
        </div>

        {sourceId ? (
          <p className="font-mono text-[11px] text-muted-foreground">{sourceId}</p>
        ) : (
          <p className="text-[11px] text-warning-foreground">Not configured</p>
        )}

        <Button
          className="h-7 w-full text-xs"
          size="sm"
          type="button"
          variant="outline"
          onClick={() => setSourceOpen(true)}
        >
          {sourceId ? "Edit Source" : "Configure Source"}
        </Button>
      </div>

      {/* filters */}
      <div className="space-y-3">
        <div className="space-y-1.5">
          <div className="flex items-center gap-1.5">
            <span className="font-mono text-xs font-medium">{FILTERS_KEY}</span>
            <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
              leaf &amp; spine
            </Badge>
          </div>
          <p className="text-[11px] text-muted-foreground">
            One value per line (OR). Different filters are combined with AND.
            Matching is case-sensitive; <code className="rounded bg-muted px-1">*</code>{" "}
            and <code className="rounded bg-muted px-1">?</code> are the only
            wildcards.
          </p>
        </div>

        {shownKinds.map((kind) => (
          <FilterRow
            key={kind.key}
            kind={kind}
            value={filters[kind.key] ?? (kind.single ? "" : [])}
            onChange={setFilter}
            onRemove={handleRemoveFilter}
          />
        ))}

        {unusedKinds.length > 0 && (
          <Select value="" onValueChange={handleAddFilter}>
            <SelectTrigger className="h-7 text-xs" aria-label="Add filter">
              <SelectValue placeholder="Add filter…" />
            </SelectTrigger>
            <SelectContent>
              {unusedKinds.map((kind) => (
                <SelectItem key={kind.key} value={kind.key}>
                  {kind.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
      </div>

      {/* allow_all + max_devices safety guard */}
      <div className="space-y-2 border-t pt-3">
        <div className="flex items-center justify-between">
          <span className="font-mono text-xs font-medium">{ALLOW_ALL_KEY}</span>
          <Switch
            checked={allowAll}
            onCheckedChange={handleAllowAllChange}
            aria-label="Allow selecting every switch"
          />
        </div>
        <p className="text-[11px] text-muted-foreground">
          Without any filter the step fails, so the whole fabric is never
          selected by accident. Turn on to select every leaf and spine.
        </p>
        {!hasFilters && !allowAll && (
          <p className="rounded-lg border border-warning-border bg-warning px-3 py-2 text-[11px] text-warning-foreground">
            Add at least one filter, or enable allow_all.
          </p>
        )}
        {!hasFilters && allowAll && (
          <p className="rounded-lg border border-warning-border bg-warning px-3 py-2 text-[11px] text-warning-foreground">
            No filter set: every leaf and spine of the fabric will be selected.
          </p>
        )}

        <div className="space-y-1.5">
          <Label className="font-mono text-xs font-medium" htmlFor="aci-max-devices">
            {MAX_DEVICES_KEY}
          </Label>
          <Input
            id="aci-max-devices"
            className="h-7 font-mono text-xs"
            type="number"
            min={1}
            placeholder="No cap"
            value={maxDevices ?? ""}
            onChange={handleMaxDevicesChange}
          />
          <p className="text-[11px] text-muted-foreground">
            Fails the step if more switches match — never silently truncates.
          </p>
        </div>
      </div>

      {/* Show Preview */}
      <Button
        className="h-7 w-full text-xs"
        size="sm"
        type="button"
        variant="secondary"
        disabled={!isConfigured || previewPending}
        onClick={handleShowPreview}
      >
        {previewPending ? "Loading…" : "Show Preview"}
      </Button>

      {previewIsError && (
        <p className="text-[11px] text-destructive">
          Preview failed:{" "}
          {previewError instanceof Error ? previewError.message : "Unknown error"}
        </p>
      )}

      <FanOutConfigSection value={fanOut} onChange={handleFanOutChange} />

      {/* Dialogs */}
      <AciSourceSelectDialog
        open={sourceOpen}
        selectedSourceId={sourceId}
        onClose={() => setSourceOpen(false)}
        onSave={handleSourceIdChange}
      />

      <AciDevicesPreviewDialog
        open={previewOpen}
        onClose={() => setPreviewOpen(false)}
        devices={previewDevices}
        truncated={previewTruncated}
        sourceId={sourceId}
      />
    </div>
  );
}

export const GetAciDevicesPlugin: PluginUIComponent = {
  ConfigPanel: GetAciDevicesConfigPanel,
  HelpPanel: GetAciDevicesHelpPanel,
};
