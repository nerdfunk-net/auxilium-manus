export type ValidationSeverity = "error" | "warning";

export interface ValidationFinding {
  node_id: string | null;
  tier: number;
  severity: ValidationSeverity;
  code: string;
  message: string;
}

export interface WorkflowValidationResult {
  findings: ValidationFinding[];
  has_errors: boolean;
}
