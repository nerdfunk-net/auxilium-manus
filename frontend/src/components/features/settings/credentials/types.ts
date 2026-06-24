export type CredentialStatus = "active" | "expiring" | "expired" | "unknown";
export type CredentialType = "ssh" | "ssh_key" | "tacacs" | "generic" | "token";

export interface Credential {
  id: number;
  name: string;
  username: string;
  type: CredentialType;
  valid_until: string | null;
  is_active: boolean;
  source: string;
  owner: string | null;
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
  valid_until?: string;
}

export interface CredentialUpdatePayload {
  name?: string;
  username?: string;
  type?: CredentialType;
  password?: string;
  valid_until?: string;
}
