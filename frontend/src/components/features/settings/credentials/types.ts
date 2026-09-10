export type CredentialStatus = "active" | "expiring" | "expired" | "unknown";
export type CredentialType =
  | "ssh"
  | "ssh_key"
  | "tacacs"
  | "generic"
  | "token"
  | "shared_secret";
export type CredentialVisibility = "global" | "private";
export type CredentialStorageBackend = "local" | "vault";

export interface Credential {
  id: number;
  name: string;
  username: string;
  type: CredentialType;
  /** Symmetric algorithm for `shared_secret` credentials; null otherwise. */
  algorithm: string | null;
  valid_until: string | null;
  is_active: boolean;
  source: string;
  owner: string | null;
  owner_user_id: number | null;
  owner_username: string | null;
  visibility: CredentialVisibility;
  storage_backend: CredentialStorageBackend;
  vault_path: string | null;
  created_at: string | null;
  updated_at: string | null;
  status: CredentialStatus;
  has_password: boolean;
  has_ssh_key: boolean;
  has_ssh_passphrase: boolean;
}

export interface CredentialListResponse {
  credentials: Credential[];
}

export interface CredentialCreatePayload {
  name: string;
  username: string;
  type: CredentialType;
  password?: string;
  ssh_private_key?: string;
  ssh_passphrase?: string;
  algorithm?: string;
  valid_until?: string;
  visibility: CredentialVisibility;
  storage_backend: CredentialStorageBackend;
}

export interface CredentialUpdatePayload {
  name?: string;
  username?: string;
  type?: CredentialType;
  password?: string;
  ssh_private_key?: string;
  ssh_passphrase?: string;
  algorithm?: string;
  valid_until?: string;
  visibility?: CredentialVisibility;
  /** Reserved for a future local <-> vault move; the backend currently rejects changes. */
  storage_backend?: CredentialStorageBackend;
}
