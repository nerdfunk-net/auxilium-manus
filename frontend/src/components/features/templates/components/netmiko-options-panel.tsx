"use client";

import { Database, Search, Settings2, Terminal } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { useCredentialsQuery } from "@/components/features/settings/credentials/hooks/use-credentials-query";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useApi } from "@/hooks/use-api";

import type { DeviceSummary } from "../types";

interface NetmikoOptionsPanelProps {
  sources: { sourceId: string }[];
  sourceId: string;
  nautobotUrl: string;
  nautobotToken: string;
  sourceReady: boolean;
  commandCount: number;
  attributeCount: number;
  credentialId: string;
  onSourceChange: (sourceId: string) => void;
  onSelectDevice: (device: DeviceSummary | null) => void;
  onConfigureCommands: () => void;
  onConfigureAttributes: () => void;
  onCredentialChange: (value: string) => void;
}

const NO_SOURCE = "__none__";

export function NetmikoOptionsPanel({
  sources,
  sourceId,
  nautobotUrl,
  nautobotToken,
  sourceReady,
  commandCount,
  attributeCount,
  credentialId,
  onSourceChange,
  onSelectDevice,
  onConfigureCommands,
  onConfigureAttributes,
  onCredentialChange,
}: NetmikoOptionsPanelProps) {
  const { apiCall } = useApi();
  const { data: credentialsData } = useCredentialsQuery();
  const sshCredentials = (credentialsData?.credentials ?? []).filter(
    (credential) => credential.type === "ssh",
  );

  const [searchTerm, setSearchTerm] = useState("");
  const [results, setResults] = useState<DeviceSummary[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [showResults, setShowResults] = useState(false);
  const isSelectingRef = useRef(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setShowResults(false);
      }
    };
    if (showResults) {
      document.addEventListener("mousedown", handleClickOutside);
      return () => document.removeEventListener("mousedown", handleClickOutside);
    }
    return undefined;
  }, [showResults]);

  useEffect(() => {
    if (isSelectingRef.current) {
      isSelectingRef.current = false;
      return undefined;
    }

    let active = true;
    const timeoutId = setTimeout(async () => {
      if (searchTerm.trim().length < 3 || !sourceReady) {
        if (active) {
          setResults([]);
          setShowResults(false);
        }
        return;
      }
      setIsSearching(true);
      try {
        const response = await apiCall<{ devices: DeviceSummary[] }>(
          "sources/nautobot/devices/search",
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              nautobot_url: nautobotUrl,
              nautobot_token: nautobotToken,
              search: searchTerm.trim(),
              limit: 20,
            }),
          },
        );
        if (active) {
          setResults(response.devices ?? []);
          setShowResults(true);
        }
      } catch {
        if (active) {
          setResults([]);
          setShowResults(false);
        }
      } finally {
        if (active) {
          setIsSearching(false);
        }
      }
    }, 300);

    return () => {
      active = false;
      clearTimeout(timeoutId);
    };
  }, [searchTerm, sourceReady, nautobotUrl, nautobotToken, apiCall]);

  const handleSelectDevice = (device: DeviceSummary) => {
    isSelectingRef.current = true;
    setSearchTerm(device.name ?? device.id);
    setShowResults(false);
    onSelectDevice(device);
  };

  const handleSearchChange = (value: string) => {
    setSearchTerm(value);
    if (value.trim().length === 0) {
      onSelectDevice(null);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Terminal className="size-4" />
          Netmiko Options
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-12">
          <div className="space-y-1.5 md:col-span-3">
            <Label>Nautobot Source</Label>
            <Select
              value={sourceId || NO_SOURCE}
              onValueChange={(value) =>
                onSourceChange(value === NO_SOURCE ? "" : value)
              }
            >
              <SelectTrigger>
                <SelectValue placeholder="Select source…" />
              </SelectTrigger>
              <SelectContent>
                {sources.length === 0 ? (
                  <SelectItem value={NO_SOURCE} disabled>
                    No sources configured
                  </SelectItem>
                ) : (
                  sources.map((source) => (
                    <SelectItem key={source.sourceId} value={source.sourceId}>
                      {source.sourceId}
                    </SelectItem>
                  ))
                )}
              </SelectContent>
            </Select>
          </div>

          <div className="relative space-y-1.5 md:col-span-3">
            <Label htmlFor="test-device">Test Device (Optional)</Label>
            <div className="relative" ref={dropdownRef}>
              <Input
                id="test-device"
                className="pr-9"
                placeholder={
                  sourceReady
                    ? "Type device name (min 3 chars)…"
                    : "Select a Nautobot source first"
                }
                disabled={!sourceReady}
                value={searchTerm}
                onChange={(event) => handleSearchChange(event.target.value)}
                onFocus={() => {
                  if (results.length > 0) {
                    setShowResults(true);
                  }
                }}
              />
              <span className="absolute right-3 top-1/2 -translate-y-1/2">
                {isSearching ? (
                  <span className="block size-4 animate-spin rounded-full border-b-2 border-primary" />
                ) : (
                  <Search className="size-4 text-muted-foreground" />
                )}
              </span>
              {showResults && results.length > 0 ? (
                <div className="absolute z-50 mt-1 max-h-64 w-full overflow-auto rounded-md border bg-popover shadow-lg">
                  {results.map((device) => (
                    <button
                      key={device.id}
                      type="button"
                      className="block w-full border-b px-3 py-2 text-left last:border-b-0 hover:bg-muted"
                      onClick={() => handleSelectDevice(device)}
                    >
                      <span className="block text-sm font-medium text-popover-foreground">
                        {device.name ?? device.id}
                      </span>
                      <span className="block text-xs text-muted-foreground">
                        {device.primary_ip4 ?? "No IP"}
                      </span>
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
          </div>

          <div className="space-y-1.5 md:col-span-2">
            <Label>Commands (Optional)</Label>
            <Button
              type="button"
              variant="outline"
              className="w-full justify-start px-3 font-normal"
              onClick={onConfigureCommands}
            >
              <Settings2 className="size-4" />
              Commands
              {commandCount > 0 ? (
                <Badge variant="secondary" className="ml-auto">
                  {commandCount}
                </Badge>
              ) : null}
            </Button>
          </div>

          <div className="space-y-1.5 md:col-span-2">
            <Label>Attributes (Optional)</Label>
            <Button
              type="button"
              variant="outline"
              className="w-full justify-start px-3 font-normal"
              onClick={onConfigureAttributes}
            >
              <Database className="size-4" />
              Nautobot
              {attributeCount > 0 ? (
                <Badge variant="secondary" className="ml-auto">
                  {attributeCount}
                </Badge>
              ) : null}
            </Button>
          </div>

          <div className="space-y-1.5 md:col-span-2">
            <Label>Credentials</Label>
            <Select value={credentialId} onValueChange={onCredentialChange}>
              <SelectTrigger>
                <SelectValue placeholder="None" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">None</SelectItem>
                {sshCredentials.map((credential) => (
                  <SelectItem key={credential.id} value={String(credential.id)}>
                    {credential.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
