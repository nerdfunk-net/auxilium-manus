/** Default run-parameter name — keep in sync with
 * backend/workflow_steps/get_from_user/config.py. */
export const DEFAULT_GET_FROM_USER_DEVICE_PARAM = "target_devices";

/** Default pluginConfig for a new Get from User canvas node — keep in sync with
 * backend/workflow_steps/get_from_user/config.py. */
export const DEFAULT_GET_FROM_USER_CONFIG = {
  device_param: DEFAULT_GET_FROM_USER_DEVICE_PARAM,
  lookup_mode: "manual",
  nautobot_source_id: "",
  fan_out: {
    enabled: false,
    mode: "per_device" as const,
    chunk_size: 1,
    max_concurrency: 0,
  },
};
