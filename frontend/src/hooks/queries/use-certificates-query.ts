"use client";

import { useQuery } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";
import { queryKeys } from "@/lib/query-keys";

export interface CertificateInfo {
  filename: string;
  path: string;
  size: number;
  exists_in_system: boolean;
}

export interface CertificateScanResult {
  certificates: CertificateInfo[];
  certs_directory: string;
}

export function useCertificatesQuery() {
  const { apiCall } = useApi();

  return useQuery<CertificateScanResult>({
    queryKey: queryKeys.certificates.scan(),
    queryFn: () => apiCall("certificates/scan", { method: "GET" }),
    staleTime: 10 * 1000,
  });
}
