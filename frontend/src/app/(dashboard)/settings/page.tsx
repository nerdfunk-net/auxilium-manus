import { redirect } from "next/navigation";

export default function SettingsIndexRoute() {
  redirect("/settings/general");
}
