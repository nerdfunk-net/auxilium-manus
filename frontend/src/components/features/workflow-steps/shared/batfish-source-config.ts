import { makeSourceConfig } from "./source-config";

const source = makeSourceConfig("batfish_source_id");

/** Config key for the Batfish source reference stored on workflow step nodes. */
export const BATFISH_SOURCE_ID_KEY = source.key;
export const batfishSourceIdFromConfig = source.idFromConfig;
