"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { useToast } from "@/hooks/use-toast";
import { queryKeys } from "@/lib/query-keys";

import type { CertificateInfo } from "./use-certificates-query";

export interface AddCertificateResult {
  filename: string;
  success: boolean;
  message: string;
  error?: string;
  command_output?: string;
}

function getErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Unexpected error";
}

export function useCertificatesMutations() {
  const { apiCall } = useApi();
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: queryKeys.certificates.scan() });

  const uploadCertificate = useMutation({
    mutationFn: (file: File) => {
      const formData = new FormData();
      formData.append("file", file);
      return apiCall<CertificateInfo>("certificates/upload", {
        method: "POST",
        body: formData,
      });
    },
    onSuccess: () => {
      invalidate();
      toast({ title: "Uploaded", description: "Certificate uploaded." });
    },
    onError: (error: Error) => {
      toast({ title: "Upload failed", description: error.message, variant: "destructive" });
    },
  });

  const addCertificatesToSystem = useMutation({
    mutationFn: async (filenames: string[]): Promise<AddCertificateResult[]> => {
      const results: AddCertificateResult[] = [];
      for (const filename of filenames) {
        try {
          const result = await apiCall<{
            success: boolean;
            message: string;
            error?: string;
            command_output?: string;
          }>("certificates/add-to-system", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ filename }),
          });
          results.push({ filename, ...result });
        } catch (error: unknown) {
          results.push({
            filename,
            success: false,
            message: getErrorMessage(error),
          });
        }
      }
      return results;
    },
    onSuccess: () => invalidate(),
  });

  const deleteCertificate = useMutation({
    mutationFn: (filename: string) =>
      apiCall<void>(`certificates/${encodeURIComponent(filename)}`, { method: "DELETE" }),
    onSuccess: () => {
      invalidate();
      toast({ title: "Deleted", description: "Certificate removed." });
    },
    onError: (error: Error) => {
      toast({ title: "Delete failed", description: error.message, variant: "destructive" });
    },
  });

  return { uploadCertificate, addCertificatesToSystem, deleteCertificate };
}
