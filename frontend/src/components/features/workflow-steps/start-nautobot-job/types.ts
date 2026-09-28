import type {
  EnabledValueSpec,
  ValueSpec,
} from "@/components/features/workflow-steps/shared/nautobot-field-rows";
import type { NautobotJobVariable } from "@/hooks/queries/use-nautobot-job-variables-query";

export type { NautobotJobVariable };
export type {
  NautobotUuidResolution,
  NautobotUuidResourceType,
} from "@/components/features/workflow-steps/shared/nautobot-field-rows";

export interface StartNautobotJobParameters {
  required: Record<string, ValueSpec>;
  optional: Record<string, EnabledValueSpec>;
}

export interface StartNautobotJobConfig {
  nautobot_source_id?: string;
  job_id?: string;
  job_name?: string;
  job_variables_schema?: NautobotJobVariable[];
  parameters?: StartNautobotJobParameters;
  task_queue?: string;
}

export const EMPTY_PARAMETERS: StartNautobotJobParameters = {
  required: {},
  optional: {},
};
