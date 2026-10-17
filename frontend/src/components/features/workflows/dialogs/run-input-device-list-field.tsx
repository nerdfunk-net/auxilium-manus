"use client";

import { Search, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useNetmikoDeviceSearchQuery } from "@/hooks/queries/use-netmiko-device-search-query";
import type { DeviceSummary } from "@/components/features/templates/types";

const EMPTY_DEVICES: DeviceSummary[] = [];

const SEARCH_INPUT_CLASS = "h-9 pr-8 font-mono text-xs focus-visible:ring-step/40";

interface DeviceChip {
  key: string;
  name: string | null;
  ip: string | null;
}

// Lightweight client-side heuristic only, used to decide whether a manually
// typed token should be added as a name or an IP chip. The backend's
// workflow_steps.common.device_list.parse_device_list_text is the
// authoritative validator — this never blocks adding an entry.
const IPV4_REGEX = /^(\d{1,3}\.){3}\d{1,3}(\/\d{1,2})?$/;
const IPV6_REGEX = /^[0-9a-fA-F:]+(\/\d{1,3})?$/;

function looksLikeIp(token: string): boolean {
  return IPV4_REGEX.test(token) || (token.includes(":") && IPV6_REGEX.test(token));
}

function textToChips(text: string): DeviceChip[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
    .map((line, index) => {
      if (line.includes(",")) {
        const [namePart, ipPart] = line.split(",", 2).map((part) => part.trim());
        return { key: `${index}-${line}`, name: namePart || null, ip: ipPart || null };
      }
      if (looksLikeIp(line)) {
        return { key: `${index}-${line}`, name: null, ip: line };
      }
      return { key: `${index}-${line}`, name: line, ip: null };
    });
}

function chipToLine(chip: DeviceChip): string {
  if (chip.name && chip.ip) {
    return `${chip.name},${chip.ip}`;
  }
  return chip.name ?? chip.ip ?? "";
}

function chipsToText(chips: DeviceChip[]): string {
  return chips.map(chipToLine).filter((line) => line.length > 0).join("\n");
}

function chipDedupeKey(chip: DeviceChip): string {
  return `${(chip.name ?? "").toLowerCase()}|${chip.ip ?? ""}`;
}

interface RunInputDeviceListFieldProps {
  value: string;
  onChange: (text: string) => void;
  sourceId: string;
}

/**
 * Multi-add device field for the Run Inputs dialog — used for a `string`
 * static attribute a `get-from-user` node has configured with
 * `lookup_mode: "nautobot_search"`. Reuses `useNetmikoDeviceSearchQuery`
 * as-is (debounced, >=3 character gate, same `/sources/nautobot/devices/search`
 * endpoint the Templates feature already uses).
 *
 * The committed value stays a plain newline-delimited string (`name` /
 * `ip_address` / `name,ip_address` per line) — the exact same shape the
 * plain manual Textarea produces — so `get-from-user`'s executor never knows
 * or cares which widget built it. Clicking a suggestion adds a chip with its
 * resolved IP already filled in; typing a raw entry and pressing Enter adds
 * it as a manual chip even when Nautobot search is otherwise available.
 */
export function RunInputDeviceListField({ value, onChange, sourceId }: RunInputDeviceListFieldProps) {
  const chips = useMemo(() => textToChips(value), [value]);
  const [searchTerm, setSearchTerm] = useState("");
  // Dismissed by the user (outside click or adding a chip); reopened as soon
  // as they type again or refocus with existing results — mirrors
  // NetmikoOptionsPanel's dropdown dismissal behavior.
  const [dismissed, setDismissed] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const searchQuery = useNetmikoDeviceSearchQuery({
    sourceId,
    searchTerm,
    enabled: sourceId.trim().length > 0,
  });
  const results = searchQuery.data?.devices ?? EMPTY_DEVICES;
  const isSearching = searchQuery.isFetching;
  const showResults =
    !dismissed && searchTerm.trim().length >= 3 && sourceId.trim().length > 0 && results.length > 0;

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setDismissed(true);
      }
    };
    if (showResults) {
      document.addEventListener("mousedown", handleClickOutside);
      return () => document.removeEventListener("mousedown", handleClickOutside);
    }
    return undefined;
  }, [showResults]);

  const addChip = (chip: DeviceChip) => {
    if (!chip.name && !chip.ip) {
      return;
    }
    const existingKeys = new Set(chips.map(chipDedupeKey));
    if (!existingKeys.has(chipDedupeKey(chip))) {
      onChange(chipsToText([...chips, chip]));
    }
    setSearchTerm("");
    setDismissed(true);
  };

  const removeChip = (index: number) => {
    onChange(chipsToText(chips.filter((_, itemIndex) => itemIndex !== index)));
  };

  const handleSelectSuggestion = (device: DeviceSummary) => {
    addChip({ key: device.id, name: device.name ?? device.id, ip: device.primary_ip4 ?? null });
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key !== "Enter") {
      return;
    }
    event.preventDefault();
    const raw = searchTerm.trim();
    if (!raw) {
      return;
    }
    if (raw.includes(",")) {
      const [namePart, ipPart] = raw.split(",", 2).map((part) => part.trim());
      addChip({ key: raw, name: namePart || null, ip: ipPart || null });
    } else if (looksLikeIp(raw)) {
      addChip({ key: raw, name: null, ip: raw });
    } else {
      addChip({ key: raw, name: raw, ip: null });
    }
  };

  return (
    <div className="space-y-2">
      <div className="relative" ref={containerRef}>
        <Input
          className={SEARCH_INPUT_CLASS}
          placeholder="Type a name or IP (3+ chars for suggestions), Enter to add…"
          value={searchTerm}
          onChange={(event) => {
            setSearchTerm(event.target.value);
            setDismissed(false);
          }}
          onKeyDown={handleKeyDown}
          onFocus={() => {
            if (results.length > 0) {
              setDismissed(false);
            }
          }}
        />
        <span className="absolute right-2.5 top-1/2 -translate-y-1/2">
          {isSearching ? (
            <span
              className="block size-3.5 animate-spin rounded-full border-b-2 border-step"
              aria-hidden
            />
          ) : (
            <Search className="size-3.5 text-muted-foreground" aria-hidden />
          )}
        </span>
        {showResults ? (
          <div className="absolute z-50 mt-1 max-h-48 w-full overflow-auto rounded-md border border-border bg-popover shadow-lg">
            {results.map((device) => (
              <Button
                key={device.id}
                type="button"
                variant="ghost"
                className="h-auto w-full justify-start rounded-none border-b px-3 py-1.5 text-left last:border-b-0"
                onClick={() => handleSelectSuggestion(device)}
              >
                <span className="block w-full">
                  <span className="block text-xs font-medium text-popover-foreground">
                    {device.name ?? device.id}
                  </span>
                  <span className="block text-[11px] text-muted-foreground">
                    {device.primary_ip4 ?? "No IP"}
                  </span>
                </span>
              </Button>
            ))}
          </div>
        ) : null}
      </div>

      {chips.length > 0 ? (
        <div className="flex flex-wrap gap-1.5">
          {chips.map((chip, index) => (
            <span
              key={`${chip.key}-${index}`}
              className="inline-flex items-center gap-1 rounded-full border border-step-border bg-step-surface px-2 py-0.5 text-[11px] text-step-surface-foreground"
            >
              <span className="font-mono">{chip.name ?? chip.ip}</span>
              {chip.name && chip.ip ? (
                <span className="text-step-muted-foreground">({chip.ip})</span>
              ) : null}
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="size-5 text-step-muted-foreground hover:text-destructive"
                onClick={() => removeChip(index)}
                aria-label={`Remove ${chip.name ?? chip.ip}`}
              >
                <X className="size-3" aria-hidden />
              </Button>
            </span>
          ))}
        </div>
      ) : (
        <p className="text-[11px] text-muted-foreground">No devices added yet.</p>
      )}
    </div>
  );
}
