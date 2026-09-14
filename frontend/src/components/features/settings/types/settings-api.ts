export interface SettingRecord {
  id: number;
  key: string;
  value: Record<string, unknown>;
  description: string | null;
  created_at: string;
  updated_at: string;
}

export interface SettingListResponse {
  settings: SettingRecord[];
  total: number;
}

export interface NautobotSourceValue {
  sourceId: string;
  url: string;
  tokenConfigured: boolean;
  credentialId: number | null;
  verifySsl: boolean;
}

export interface NautobotSourceConfig extends NautobotSourceValue {
  key: string;
  description: string | null;
  updatedAt: string;
  credentialName: string | null;
}

export interface SettingCreatePayload {
  key: string;
  value: Record<string, unknown>;
  description?: string;
}

export interface SettingUpdatePayload {
  value?: Record<string, unknown>;
  description?: string;
}

export interface ISESourceResponse {
  source_id: string;
  url: string;
  verify_ssl: boolean;
  timeout: number;
  credential_id: number | null;
  credential_name: string | null;
}

export interface ISESourceListResponse {
  sources: ISESourceResponse[];
  total: number;
}

export interface ISESourceCreatePayload {
  source_id: string;
  url: string;
  credential_id: number;
  verify_ssl: boolean;
  timeout: number;
}

export interface ISESourceUpdatePayload {
  url?: string;
  credential_id?: number;
  verify_ssl?: boolean;
  timeout?: number;
}

export interface ISETestConnectionResponse {
  success: boolean;
  message: string;
}

export interface SourceTestConnectionResponse {
  success: boolean;
  message: string;
}

/**
 * Test either a saved source (`{ source_id }`) or unsaved dialog values
 * (`{ url, credential_id, verify_ssl, timeout }`) — never both (backend XOR).
 */
export type SourceTestConnectionPayload =
  | { source_id: string }
  | { url: string; credential_id: number; verify_ssl: boolean; timeout: number };

export interface PyATSSourceResponse {
  source_id: string;
  url: string;
  verify_ssl: boolean;
  timeout: number;
  credential_id: number | null;
  credential_name: string | null;
}

export interface PyATSSourceListResponse {
  sources: PyATSSourceResponse[];
  total: number;
}

export interface PyATSSourceCreatePayload {
  source_id: string;
  url: string;
  credential_id: number;
  verify_ssl: boolean;
  timeout: number;
}

export interface PyATSSourceUpdatePayload {
  url?: string;
  credential_id?: number;
  verify_ssl?: boolean;
  timeout?: number;
}

export interface PyATSTestConnectionResponse {
  success: boolean;
  message: string;
}

export interface MattermostSourceResponse {
  source_id: string;
  url: string;
  verify_ssl: boolean;
  timeout: number;
  credential_id: number | null;
  credential_name: string | null;
}

export interface MattermostSourceListResponse {
  sources: MattermostSourceResponse[];
  total: number;
}

export interface MattermostSourceCreatePayload {
  source_id: string;
  url: string;
  credential_id: number;
  verify_ssl: boolean;
  timeout: number;
}

export interface MattermostSourceUpdatePayload {
  url?: string;
  credential_id?: number;
  verify_ssl?: boolean;
  timeout?: number;
}

export interface MattermostTestConnectionResponse {
  success: boolean;
  message: string;
}

export interface BatfishSourceResponse {
  source_id: string;
  host: string;
  port: number;
}

export interface BatfishSourceListResponse {
  sources: BatfishSourceResponse[];
  total: number;
}

export interface BatfishSourceCreatePayload {
  source_id: string;
  host: string;
  port: number;
}

export interface BatfishSourceUpdatePayload {
  host?: string;
  port?: number;
}

export interface BatfishTestConnectionResponse {
  success: boolean;
  message: string;
}

/**
 * Test either a saved source (`{ source_id }`) or unsaved dialog values
 * (`{ host, port }`) — never both. Deliberately its own type, not a reuse of
 * `SourceTestConnectionPayload`: the Batfish coordinator has no
 * credential/verify_ssl/timeout, so its inline shape doesn't fit that one.
 */
export type BatfishTestConnectionPayload =
  | { source_id: string }
  | { host: string; port: number };

export interface BatfishNetworksResponse {
  networks: string[];
}

export interface BatfishSnapshotInfo {
  name: string;
  created_at: string | null;
}

/** Sorted most-recent-first by created_at -- the first entry is the latest snapshot. */
export interface BatfishSnapshotsResponse {
  snapshots: BatfishSnapshotInfo[];
}
