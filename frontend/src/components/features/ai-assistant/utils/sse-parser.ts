export interface SseEvent {
  event: string;
  data: unknown;
}

export interface SseParseResult {
  events: SseEvent[];
  /** Trailing bytes of an incomplete event; prepend to the next chunk. */
  rest: string;
}

/**
 * Parses the `event:` / `data:` frames the backend emits (one JSON object per `data:`).
 * Frames end with a blank line. Malformed JSON frames are skipped, not thrown, so one bad
 * frame cannot kill a stream.
 */
export function parseSseBuffer(buffer: string): SseParseResult {
  const normalized = buffer.replace(/\r\n/g, "\n");
  const frames = normalized.split("\n\n");
  const rest = frames.pop() ?? "";
  const events: SseEvent[] = [];

  for (const frame of frames) {
    let event = "message";
    const dataLines: string[] = [];
    for (const line of frame.split("\n")) {
      if (line.startsWith("event:")) {
        event = line.slice("event:".length).trim();
      } else if (line.startsWith("data:")) {
        dataLines.push(line.slice("data:".length).trimStart());
      }
    }
    if (dataLines.length === 0) {
      continue;
    }
    try {
      events.push({ event, data: JSON.parse(dataLines.join("\n")) });
    } catch {
      continue;
    }
  }

  return { events, rest };
}
