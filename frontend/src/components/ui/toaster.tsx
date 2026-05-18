"use client";

import { AlertCircle, CheckCircle2, X } from "lucide-react";

import { useToastStore } from "@/hooks/use-toast";

export function Toaster() {
  const { toasts, removeToast } = useToastStore();

  if (toasts.length === 0) return null;

  return (
    <div className="fixed bottom-4 right-4 z-[9999] flex w-full max-w-sm flex-col gap-2">
      {toasts.map((t) => (
        <div
          key={t.id}
          className={`flex items-start gap-3 rounded-lg border px-4 py-3 text-sm shadow-lg transition-all ${
            t.variant === "destructive"
              ? "border-red-200 bg-red-50 text-red-900"
              : "border-border bg-card text-card-foreground"
          }`}
        >
          <div className="mt-0.5 shrink-0">
            {t.variant === "destructive" ? (
              <AlertCircle className="size-4 text-red-500" />
            ) : (
              <CheckCircle2 className="size-4 text-green-500" />
            )}
          </div>
          <div className="min-w-0 flex-1">
            {t.title ? (
              <p className="font-semibold leading-snug">{t.title}</p>
            ) : null}
            <p
              className={`whitespace-pre-wrap break-words leading-snug ${t.title ? "mt-0.5 text-xs opacity-80" : ""}`}
            >
              {t.description}
            </p>
          </div>
          <button
            aria-label="Dismiss"
            className="shrink-0 opacity-50 transition-opacity hover:opacity-100"
            onClick={() => removeToast(t.id)}
            type="button"
          >
            <X className="size-3.5" />
          </button>
        </div>
      ))}
    </div>
  );
}
