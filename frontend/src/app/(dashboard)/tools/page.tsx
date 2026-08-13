import { ToolsPage } from "@/components/features/tools/tools-page";

export default function ToolsRoute() {
  return (
    <ToolsPage
      oidcTestEnabled={process.env.ENABLE_DEV_TOOLS === "true"}
    />
  );
}
