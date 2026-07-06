import { notFound } from "next/navigation";

import { SettingsPage } from "@/components/features/settings/settings-page";
import { parseSettingsSection } from "@/components/features/settings/utils/settings-section-params";

type Props = { params: Promise<{ section: string }> };

export function generateStaticParams() {
  return [
    { section: "general" },
    { section: "sources" },
    { section: "credentials" },
    { section: "users" },
    { section: "hatchet" },
    { section: "redis" },
  ];
}

export default async function SettingsSectionRoute({ params }: Props) {
  const { section } = await params;
  const parsed = parseSettingsSection(section);
  if (!parsed) notFound();
  return <SettingsPage section={parsed} />;
}
