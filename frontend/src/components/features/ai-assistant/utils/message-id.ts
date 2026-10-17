let messageCounter = 0;

/** Unique within the page's lifetime; ids only need to be stable while messages are in memory. */
export function nextMessageId(): string {
  messageCounter += 1;
  return `m${messageCounter}`;
}
