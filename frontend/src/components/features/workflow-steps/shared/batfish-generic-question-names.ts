/**
 * Suggestion list only -- mirrors GENERIC_QUESTION_ALLOWLIST in
 * backend/services/batfish/query_helpers.py, the actual enforcement point.
 * A name typed here that isn't allow-listed server-side still gets a clean
 * 400, same as anywhere else in this app where a suggestion list is
 * non-exhaustive (see BATFISH_INTERFACE_PROPERTY_KEYS). Each entry was
 * empirically confirmed to answer against a live coordinator -- see
 * doc/BATFISH_INTEGRATION.md "Template Editor integration".
 */
export const BATFISH_GENERIC_QUESTION_NAMES = [
  "bgpPeerConfiguration",
  "bgpProcessConfiguration",
  "bgpEdges",
  "bgpSessionCompatibility",
  "bgpSessionStatus",
  "ospfProcessConfiguration",
  "ospfInterfaceConfiguration",
  "ospfEdges",
  "namedStructures",
  "ipOwners",
  "edges",
  "undefinedReferences",
  "unusedStructures",
  "filterLineReachability",
  "switchedVlanProperties",
] as const;
