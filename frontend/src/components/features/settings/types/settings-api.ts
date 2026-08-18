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
  verifySsl: boolean;
}

export interface GitSourceValue {
  sourceId: string;
  url: string;
  branch: string;
  tokenConfigured: boolean;
  username: string;
  repository_path: string;
  verifySsl: boolean;
}

export interface NautobotSourceConfig extends NautobotSourceValue {
  key: string;
  description: string | null;
  updatedAt: string;
}

export interface GitSourceConfig extends GitSourceValue {
  key: string;
  description: string | null;
  updatedAt: string;
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
}

export interface ISESourceListResponse {
  sources: ISESourceResponse[];
  total: number;
}

export interface ISESourceCreatePayload {
  source_id: string;
  url: string;
  username: string;
  password: string;
  verify_ssl: boolean;
  timeout: number;
}

export interface ISESourceUpdatePayload {
  url?: string;
  username?: string;
  password?: string;
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

export interface PyATSSourceResponse {
  source_id: string;
  url: string;
  verify_ssl: boolean;
  timeout: number;
}

export interface PyATSSourceListResponse {
  sources: PyATSSourceResponse[];
  total: number;
}

export interface PyATSSourceCreatePayload {
  source_id: string;
  url: string;
  token: string;
  verify_ssl: boolean;
  timeout: number;
}

export interface PyATSSourceUpdatePayload {
  url?: string;
  token?: string;
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
}

export interface MattermostSourceListResponse {
  sources: MattermostSourceResponse[];
  total: number;
}

export interface MattermostSourceCreatePayload {
  source_id: string;
  url: string;
  token: string;
  verify_ssl: boolean;
  timeout: number;
}

export interface MattermostSourceUpdatePayload {
  url?: string;
  token?: string;
  verify_ssl?: boolean;
  timeout?: number;
}

export interface MattermostTestConnectionResponse {
  success: boolean;
  message: string;
}
