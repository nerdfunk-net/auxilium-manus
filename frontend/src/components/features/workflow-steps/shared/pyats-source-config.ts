import { makeSourceConfig } from "./source-config";

const source = makeSourceConfig("pyats_source_id");

/** Config key for the pyATS source reference stored on workflow step nodes. */
export const PYATS_SOURCE_ID_KEY = source.key;
export const pyatsSourceIdFromConfig = source.idFromConfig;
