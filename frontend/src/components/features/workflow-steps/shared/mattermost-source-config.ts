import { makeSourceConfig } from "./source-config";

const source = makeSourceConfig("mattermost_source_id");

/** Config key for the Mattermost source reference stored on workflow step nodes. */
export const MATTERMOST_SOURCE_ID_KEY = source.key;
export const mattermostSourceIdFromConfig = source.idFromConfig;
