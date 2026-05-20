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
  token: string;
}

export interface GitSourceValue {
  sourceId: string;
  url: string;
  branch: string;
  token: string;
  username: string;
  repository_path: string;
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
