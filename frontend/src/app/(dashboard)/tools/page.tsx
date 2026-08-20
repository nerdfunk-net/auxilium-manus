import { ToolsPage } from "@/components/features/tools/tools-page";
import { isDevToolsEnabled } from "@/lib/dev-tools";

export default function ToolsRoute() {
  return <ToolsPage oidcTestEnabled={isDevToolsEnabled()} />;
}
