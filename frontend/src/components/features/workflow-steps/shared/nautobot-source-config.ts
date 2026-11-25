import { makeSourceConfig } from "./source-config";

const source = makeSourceConfig("nautobot_source_id", { lowercase: true });

/** Config key for the Nautobot source reference stored on workflow step nodes. */
export const NAUTOBOT_SOURCE_ID_KEY = source.key;
export const nautobotSourceIdFromConfig = source.idFromConfig;
export const isNautobotSourceConfigured = source.isConfigured;
