export type CredentialStatus = "active" | "expiring" | "expired" | "unknown";
export type CredentialType = "ssh" | "ssh_key" | "tacacs" | "generic" | "token";
export type CredentialVisibility = "global" | "private";

export interface Credential {
  id: number;
  name: string;
  username: string;
  type: CredentialType;
  valid_until: string | null;
  is_active: boolean;
  source: string;
  owner: string | null;
  owner_user_id: number | null;
  owner_username: string | null;
  visibility: CredentialVisibility;
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
  valid_until?: string;
  visibility: CredentialVisibility;
}

export interface CredentialUpdatePayload {
  name?: string;
  username?: string;
  type?: CredentialType;
  password?: string;
  ssh_private_key?: string;
  ssh_passphrase?: string;
  valid_until?: string;
  visibility?: CredentialVisibility;
}
