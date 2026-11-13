/** State of browsing earlier questions with the cursor keys (-1 = not browsing). */
export interface InputHistoryState {
  readonly index: number;
  /** What was typed before the first Up, restored when Down leaves the history. */
  readonly stash: string;
}

export const INITIAL_INPUT_HISTORY: InputHistoryState = { index: -1, stash: "" };

export interface InputHistoryStep {
  readonly state: InputHistoryState;
  /** The new text for the input, or null when the key press is not a history move. */
  readonly value: string | null;
}

/** Up counts only on the first line, Down only on the last, and never over a selection. */
export function caretOnFirstLine(text: string, start: number, end: number): boolean {
  return start === end && !text.slice(0, start).includes("\n");
}

export function caretOnLastLine(text: string, start: number, end: number): boolean {
  return start === end && !text.slice(end).includes("\n");
}

/** One step back (older) through `entries`, which are the sent questions, oldest first. */
export function stepOlder(
  state: InputHistoryState,
  entries: readonly string[],
  current: string,
): InputHistoryStep {
  if (entries.length === 0) {
    return { state, value: null };
  }
  if (state.index === -1) {
    const index = entries.length - 1;
    return { state: { index, stash: current }, value: entries[index] };
  }
  if (state.index === 0) {
    return { state, value: null };
  }
  const index = state.index - 1;
  return { state: { ...state, index }, value: entries[index] };
}

/** One step forward (newer); past the newest entry the stashed draft comes back. */
export function stepNewer(state: InputHistoryState, entries: readonly string[]): InputHistoryStep {
  if (state.index === -1) {
    return { state, value: null };
  }
  if (state.index >= entries.length - 1) {
    return { state: INITIAL_INPUT_HISTORY, value: state.stash };
  }
  const index = state.index + 1;
  return { state: { ...state, index }, value: entries[index] };
}
