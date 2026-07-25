"use client";

import { Boxes, Clock3 } from "lucide-react";
import Link from "next/link";
import { Suspense } from "react";
import { useSearchParams } from "next/navigation";

import { Button } from "@/components/ui/button";

function ApprovalPendingContent() {
  const searchParams = useSearchParams();
  const username = searchParams.get("username");
  const email = searchParams.get("email");
  const provider = searchParams.get("provider");

  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-4 py-10 text-foreground">
      <section className="w-full max-w-md rounded-2xl border bg-card p-8 shadow-sm">
        <div className="mb-8 flex items-center gap-3">
          <div className="flex size-11 items-center justify-center rounded-xl bg-primary text-primary-foreground">
            <Boxes className="size-6" />
          </div>
          <div>
            <h1 className="text-lg font-semibold">Auxilium Manus</h1>
            <p className="text-sm text-muted-foreground">Account pending approval</p>
          </div>
        </div>

        <div className="flex justify-center py-6">
          <Clock3 className="size-10 text-muted-foreground" />
        </div>

        <p className="text-center text-sm text-muted-foreground">
          Your account{username ? ` for ${username}` : ""}
          {email ? ` (${email})` : ""} was created via {provider ? `${provider} ` : ""}single
          sign-on, but it isn&apos;t active yet. An administrator needs to approve it under
          Settings &gt; Users before you can sign in.
        </p>

        <Button asChild className="mt-6 w-full">
          <Link href="/login">Return to login</Link>
        </Button>
      </section>
    </main>
  );
}

export function ApprovalPendingPage() {
  return (
    <Suspense fallback={null}>
      <ApprovalPendingContent />
    </Suspense>
  );
}
