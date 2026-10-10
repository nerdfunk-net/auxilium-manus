import { describe, expect, it } from "vitest";

import { parseSseBuffer } from "./sse-parser";

describe("parseSseBuffer", () => {
  it("parses complete frames and keeps the incomplete tail", () => {
    const result = parseSseBuffer(
      'event: text\ndata: {"text": "Hel"}\n\nevent: text\ndata: {"te',
    );

    expect(result.events).toEqual([{ event: "text", data: { text: "Hel" } }]);
    expect(result.rest).toBe('event: text\ndata: {"te');
  });

  it("completes a frame split across chunks", () => {
    const first = parseSseBuffer('event: text\ndata: {"text": "a');
    const second = parseSseBuffer(`${first.rest}b"}\n\nevent: done\ndata: {}\n\n`);

    expect(second.events.map((e) => e.event)).toEqual(["text", "done"]);
    expect(second.events[0].data).toEqual({ text: "ab" });
    expect(second.rest).toBe("");
  });

  it("accepts CRLF line endings", () => {
    const result = parseSseBuffer('event: done\r\ndata: {}\r\n\r\n');

    expect(result.events).toEqual([{ event: "done", data: {} }]);
  });

  it("skips malformed JSON and data-less frames without throwing", () => {
    const result = parseSseBuffer(
      'event: text\ndata: {not json}\n\n: comment\n\nevent: done\ndata: {}\n\n',
    );

    expect(result.events).toEqual([{ event: "done", data: {} }]);
  });
});
