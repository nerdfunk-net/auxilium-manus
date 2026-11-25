import { makeSourceConfig } from "./source-config";

const source = makeSourceConfig("ise_source_id");

/** Config key for the Cisco ISE source reference stored on workflow step nodes. */
export const ISE_SOURCE_ID_KEY = source.key;
export const iseSourceIdFromConfig = source.idFromConfig;
