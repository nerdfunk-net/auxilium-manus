import { useCallback, useMemo } from "react";
import { create } from "zustand";

interface ToastMessage {
  id: string;
  title?: string;
  description: string;
  variant?: "default" | "destructive";
}

interface ToastStore {
  toasts: ToastMessage[];
  addToast: (toast: ToastMessage) => void;
  removeToast: (id: string) => void;
}

export const useToastStore = create<ToastStore>((set) => ({
  toasts: [],
  addToast: (toast) => set((state) => ({ toasts: [...state.toasts, toast] })),
  removeToast: (id) =>
    set((state) => ({ toasts: state.toasts.filter((t) => t.id !== id) })),
}));

// getRandomValues (unlike randomUUID) also works in non-secure contexts, e.g.
// the dev server opened over plain http on a LAN address.
function createToastId(): string {
  const bytes = new Uint8Array(8);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export function useToast() {
  const { addToast, removeToast, toasts } = useToastStore();

  const toast = useCallback(
    ({
      title,
      description,
      variant = "default",
    }: {
      title?: string;
      description: string;
      variant?: "default" | "destructive";
    }) => {
      const id = createToastId();
      addToast({ id, title, description, variant });
      setTimeout(() => removeToast(id), 5000);
    },
    [addToast, removeToast],
  );

  const dismiss = useCallback((id: string) => removeToast(id), [removeToast]);

  return useMemo(() => ({ toast, dismiss, toasts }), [toast, dismiss, toasts]);
}
