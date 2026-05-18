import { useCallback } from "react";
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
      const id = Math.random().toString(36).substring(2, 11);
      addToast({ id, title, description, variant });
      setTimeout(() => removeToast(id), 5000);
    },
    [addToast, removeToast],
  );

  const dismiss = useCallback((id: string) => removeToast(id), [removeToast]);

  return { toast, dismiss, toasts };
}
