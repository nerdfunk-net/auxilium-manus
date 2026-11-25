import { makeSourceConfig } from "./source-config";

const source = makeSourceConfig("aci_source_id");

/** Config key for the Cisco ACI source reference stored on workflow step nodes. */
export const ACI_SOURCE_ID_KEY = source.key;
export const aciSourceIdFromConfig = source.idFromConfig;
export const isAciSourceConfigured = source.isConfigured;
