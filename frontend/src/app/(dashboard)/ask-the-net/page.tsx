import type { Metadata } from "next";

import { AskTheNetPage } from "@/components/features/ask-the-net/ask-the-net-page";

export const metadata: Metadata = { title: "Ask the Net" };

export default function AskTheNetRoute() {
  return <AskTheNetPage />;
}
