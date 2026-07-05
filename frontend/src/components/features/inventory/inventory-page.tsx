"use client";

import { List } from "lucide-react";

import { DeviceSelector } from "./components/device-selector";
import { NautobotSourceBanner } from "./components/nautobot-source-banner";
import { useInventorySource } from "./hooks/use-inventory-source";

export function InventoryPage() {
  const source = useInventorySource();

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="mx-auto max-w-6xl space-y-6">
        <div className="flex items-center gap-4">
          <div className="flex size-12 items-center justify-center rounded-xl bg-primary/10 text-primary">
            <List className="h-6 w-6" />
          </div>
          <div>
            <h1 className="text-3xl font-bold text-foreground">Inventory Builder</h1>
            <p className="mt-1 text-muted-foreground">
              Build dynamic device inventories using logical operations
            </p>
          </div>
        </div>

        <NautobotSourceBanner
          hasSources={source.hasSources}
          isLoading={source.isLoading}
          isReady={source.isReady}
          sourceId={source.sourceId}
        />

        <DeviceSelector
          nautobot_token={source.nautobot_token}
          nautobot_url={source.nautobot_url}
          showActions
          showSaveLoad
          sourceReady={source.isReady}
        />
      </div>
    </div>
  );
}
