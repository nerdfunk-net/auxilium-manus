"use client";

import { Search, X } from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
  useGetCatalystCenterDevicesPreviewMutation,
  type CatalystCenterDevicePreview,
} from "@/hooks/queries/use-get-catalyst-center-devices-preview-mutation";

import {
  FanOutConfigSection,
  fanOutFromConfig,
  type FanOutConfig,
} from "../shared/fan-out-config";
import {
  CATALYST_CENTER_SOURCE_ID_KEY,
  catalystCenterSourceIdFromConfig,
} from "../shared/catalyst-center-source-config";
import { CatalystCenterSourceSelectDialog } from "../shared/catalyst-center-source-select-dialog";
import {
  activeFilters,
  FILTER_KINDS,
  filtersFromConfig,
  INCLUDE_CHILD_SITES_KEY,
  presentKinds,
  type FilterKey,
  type FilterKind,
  type FilterValue,
} from "./filter-kinds";
import { GetCatalystCenterDevicesHelpPanel } from "./help-panel";
import { CatalystCenterDevicesPreviewDialog } from "./preview-dialog";
import { CatalystCenterSitesDialog } from "./sites-dialog";

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
  /** Site row only: opens the site picker (disabled until a source is chosen). */
  onSearchSites?: () => void;
  canSearchSites?: boolean;
  includeChildSites?: boolean;
  onIncludeChildSitesChange?: (checked: boolean) => void;
}

function FilterRow({
  kind,
  value,
  onChange,
  onRemove,
  onSearchSites,
  canSearchSites = false,
  includeChildSites = true,
  onIncludeChildSitesChange,
}: FilterRowProps) {
  const handleText = useCallback(
    (text: string) => {
      // Blank lines are kept while typing (stripped only when sent / counted) so the
      // cursor is not yanked away right after pressing Enter.
      onChange(kind.key, kind.single ? text : text.split("\n"));
    },
    [kind.key, kind.single, onChange],
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
      {kind.single ? (
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
          value={Array.isArray(value) ? value.join("\n") : ""}
          onChange={(e) => handleText(e.target.value)}
        />
      )}
      <p className="text-[11px] text-muted-foreground">{kind.hint}</p>
      {onSearchSites && (
        <>
          <Button
            className="h-7 w-full gap-1.5 text-xs"
            size="sm"
            type="button"
            variant="outline"
            disabled={!canSearchSites}
            title={canSearchSites ? undefined : "Configure a source first"}
            onClick={onSearchSites}
          >
            <Search className="size-3.5" aria-hidden />
            Search sites…
          </Button>
          <div className="flex items-center justify-between pt-1">
            <span className="font-mono text-xs font-medium">
              {INCLUDE_CHILD_SITES_KEY}
            </span>
            <Switch
              checked={includeChildSites}
              onCheckedChange={onIncludeChildSitesChange}
              aria-label="Include child sites"
            />
          </div>
          <p className="text-[11px] text-muted-foreground">
            Also select devices in the sub-sites of each site.
          </p>
        </>
      )}
    </div>
  );
}

function GetCatalystCenterDevicesConfigPanel({
  config,
  onChange,
}: PluginConfigPanelProps) {
  const sourceId = useMemo(() => catalystCenterSourceIdFromConfig(config), [config]);
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
  const [sitesOpen, setSitesOpen] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewDevices, setPreviewDevices] = useState<CatalystCenterDevicePreview[]>([]);
  const [previewTruncated, setPreviewTruncated] = useState(false);

  const {
    mutateAsync: runPreview,
    isPending: previewPending,
    isError: previewIsError,
    error: previewError,
  } = useGetCatalystCenterDevicesPreviewMutation();

  const isConfigured = Boolean(sourceId) && (hasFilters || allowAll);

  const handleSourceIdChange = useCallback(
    (newSourceId: string) => {
      onChange({ ...config, [CATALYST_CENTER_SOURCE_ID_KEY]: newSourceId });
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
        Object.entries(filters).filter(
          ([existing]) =>
            existing !== key &&
            // the child-sites option belongs to the site filter and goes with it
            !(key === "sites" && existing === INCLUDE_CHILD_SITES_KEY),
        ),
      );
      onChange({ ...config, [FILTERS_KEY]: remaining });
    },
    [config, filters, onChange],
  );

  const siteValues = useMemo(() => {
    const raw = filters.sites;
    return Array.isArray(raw) ? raw : [];
  }, [filters.sites]);

  const handleAddSites = useCallback(
    (hierarchies: string[]) => {
      const existing = siteValues.map((v) => v.trim()).filter(Boolean);
      const merged = [...existing, ...hierarchies.filter((h) => !existing.includes(h))];
      setFilter("sites", merged);
    },
    [siteValues, setFilter],
  );

  const handleIncludeChildSitesChange = useCallback(
    (checked: boolean) => {
      onChange({ ...config, [FILTERS_KEY]: { ...filters, [INCLUDE_CHILD_SITES_KEY]: checked } });
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
      {/* catalyst_center_source_id */}
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">
            {CATALYST_CENTER_SOURCE_ID_KEY}
          </span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            catalyst center
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
              server-side
            </Badge>
          </div>
          <p className="text-[11px] text-muted-foreground">
            One value per line (OR). Different filters are combined with AND.
            Matching is case-sensitive; <code className="rounded bg-muted px-1">.*</code>{" "}
            is the only wildcard.
          </p>
        </div>

        {shownKinds.map((kind) => (
          <FilterRow
            key={kind.key}
            kind={kind}
            value={filters[kind.key] ?? (kind.single ? "" : [])}
            onChange={setFilter}
            onRemove={handleRemoveFilter}
            {...(kind.key === "sites"
              ? {
                  onSearchSites: () => setSitesOpen(true),
                  canSearchSites: Boolean(sourceId),
                  includeChildSites: filters.include_child_sites ?? true,
                  onIncludeChildSitesChange: handleIncludeChildSitesChange,
                }
              : {})}
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
          <Switch checked={allowAll} onCheckedChange={handleAllowAllChange} />
        </div>
        <p className="text-[11px] text-muted-foreground">
          Without any filter the step fails, so a large inventory is never
          selected by accident. Turn on to select every device.
        </p>
        {!hasFilters && !allowAll && (
          <p className="rounded-lg border border-warning-border bg-warning px-3 py-2 text-[11px] text-warning-foreground">
            Add at least one filter, or enable allow_all.
          </p>
        )}
        {!hasFilters && allowAll && (
          <p className="rounded-lg border border-warning-border bg-warning px-3 py-2 text-[11px] text-warning-foreground">
            No filter set: every device in Catalyst Center will be selected.
          </p>
        )}

        <div className="space-y-1.5">
          <Label
            className="font-mono text-xs font-medium"
            htmlFor="catalyst-center-max-devices"
          >
            {MAX_DEVICES_KEY}
          </Label>
          <Input
            id="catalyst-center-max-devices"
            className="h-7 font-mono text-xs"
            type="number"
            min={1}
            placeholder="No cap"
            value={maxDevices ?? ""}
            onChange={handleMaxDevicesChange}
          />
          <p className="text-[11px] text-muted-foreground">
            Fails the step if more devices match — never silently truncates.
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
      <CatalystCenterSourceSelectDialog
        open={sourceOpen}
        selectedSourceId={sourceId}
        onClose={() => setSourceOpen(false)}
        onSave={handleSourceIdChange}
      />

      <CatalystCenterSitesDialog
        open={sitesOpen}
        sourceId={sourceId}
        alreadySelected={siteValues}
        onClose={() => setSitesOpen(false)}
        onAdd={handleAddSites}
      />

      <CatalystCenterDevicesPreviewDialog
        open={previewOpen}
        onClose={() => setPreviewOpen(false)}
        devices={previewDevices}
        truncated={previewTruncated}
        sourceId={sourceId}
      />
    </div>
  );
}

export const GetCatalystCenterDevicesPlugin: PluginUIComponent = {
  ConfigPanel: GetCatalystCenterDevicesConfigPanel,
  HelpPanel: GetCatalystCenterDevicesHelpPanel,
};
