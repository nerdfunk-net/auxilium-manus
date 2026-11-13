import type { AuthUser } from "@/lib/auth";
import { hasPermission } from "@/lib/permissions";

import { ASK_THE_NET_DATA_PERMISSIONS } from "../constants/ask-the-net";

/**
 * Whether the user holds a permission that gives Ask the Net something to read.
 *
 * `sources.nautobot:read` counts only when a Nautobot source is configured: without one the backend
 * attaches no Nautobot tools (`can_read_nautobot` in routers/ai_assistant.py). `nautobotConfigured`
 * is `undefined` while that is not known (loading, or the request failed): the user is then given the
 * benefit of the doubt, so the note never flashes up and never rests on a failed request.
 */
export function hasAskTheNetData(
  user: AuthUser | null,
  nautobotConfigured: boolean | undefined,
): boolean {
  return ASK_THE_NET_DATA_PERMISSIONS.some(([resource, action]) => {
    if (!hasPermission(user, resource, action)) {
      return false;
    }
    return resource === "sources.nautobot"
      ? nautobotConfigured !== false
      : true;
  });
}
