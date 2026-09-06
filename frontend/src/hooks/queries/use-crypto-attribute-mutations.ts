"use client";

import { useMutation } from "@tanstack/react-query";

import { useApi } from "@/hooks/use-api";

export interface EncryptAttributeTestRequest {
  plaintext: string;
  shared_secret: string;
  algorithm?: string;
}

export interface EncryptAttributeTestResponse {
  ciphertext: string;
  algorithm: string;
}

export interface DecryptAttributeTestRequest {
  ciphertext: string;
  shared_secret: string;
  algorithm?: string;
}

export interface DecryptAttributeTestResponse {
  plaintext: string;
  algorithm: string;
}

/** "Test Encryption" modal — stateless crypto calculator, secret typed by the user. */
export function useEncryptAttributeTestMutation() {
  const { apiCall } = useApi();
  return useMutation<EncryptAttributeTestResponse, Error, EncryptAttributeTestRequest>({
    mutationFn: async (payload) =>
      apiCall<EncryptAttributeTestResponse>("workflow-steps/encrypt-attribute/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }),
  });
}

/** "Test Decryption" modal — stateless crypto calculator, secret typed by the user. */
export function useDecryptAttributeTestMutation() {
  const { apiCall } = useApi();
  return useMutation<DecryptAttributeTestResponse, Error, DecryptAttributeTestRequest>({
    mutationFn: async (payload) =>
      apiCall<DecryptAttributeTestResponse>("workflow-steps/decrypt-attribute/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }),
  });
}
