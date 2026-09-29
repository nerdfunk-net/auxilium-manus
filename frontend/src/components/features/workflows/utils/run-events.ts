import type { WorkflowRunEvent, WorkflowRunEventPage } from "../types/workflow-runs";

export interface RunEventsState {
  events: WorkflowRunEvent[];
  /** Cursor to pass as ``after_id`` on the next poll. */
  nextAfterId: number;
}

export const EMPTY_RUN_EVENTS: RunEventsState = { events: [], nextAfterId: 0 };

/**
 * Fold one polled page into the accumulated events. Returns the *previous*
 * object when nothing new arrived so React Query keeps referential equality and
 * an idle poll causes no re-render.
 */
export function mergeRunEvents(
  previous: RunEventsState | undefined,
  page: WorkflowRunEventPage,
): RunEventsState {
  const base = previous ?? EMPTY_RUN_EVENTS;
  const knownIds = new Set(base.events.map((event) => event.id));
  const fresh = page.events.filter((event) => !knownIds.has(event.id));
  if (fresh.length === 0) {
    return previous ?? { events: [], nextAfterId: page.next_after_id };
  }
  return { events: [...base.events, ...fresh], nextAfterId: page.next_after_id };
}

export function eventsForStep(
  events: readonly WorkflowRunEvent[],
  stepNodeId: string,
): WorkflowRunEvent[] {
  return events.filter((event) => event.step_node_id === stepNodeId);
}

/** Most recent event per step node id (events arrive in id order). */
export function latestEventsByStep(
  events: readonly WorkflowRunEvent[],
): Map<string, WorkflowRunEvent> {
  const latest = new Map<string, WorkflowRunEvent>();
  for (const event of events) {
    latest.set(event.step_node_id, event);
  }
  return latest;
}

export function formatRunEvent(event: WorkflowRunEvent): string {
  return event.device_name ? `${event.device_name}: ${event.message}` : event.message;
}
