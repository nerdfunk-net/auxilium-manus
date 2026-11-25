import { makeSourceConfig } from "./source-config";

const source = makeSourceConfig("catalyst_center_source_id");

/** Config key for the Cisco Catalyst Center source reference stored on workflow step nodes. */
export const CATALYST_CENTER_SOURCE_ID_KEY = source.key;
export const catalystCenterSourceIdFromConfig = source.idFromConfig;
