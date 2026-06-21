/**
 * NDJSON stream parsing for /api/chat/stream.
 *
 * The backend streams one JSON event frame per line (see CLAUDE.md "NDJSON
 * stream protocol"). Network chunks don't align to line boundaries, so frames
 * have to be reassembled across reads. This module owns that buffering and
 * line-splitting so it can be unit-tested independently of the React component
 * that consumes the frames.
 */

export type StreamFrame =
  | { type: "status"; label?: string }
  | { type: "token"; text?: string }
  | { type: "reset" }
  | { type: "error"; message?: string };

export interface NdjsonParser {
  /** Feed a decoded chunk; invokes onFrame for each complete line. */
  push(chunk: string): void;
  /** Flush any trailing partial line (a final frame with no newline). */
  flush(): void;
}

/**
 * Create a stateful NDJSON parser. Complete lines are split on "\n", trimmed,
 * JSON-parsed, and handed to onFrame; blank and malformed lines are skipped so
 * one bad frame never aborts the stream.
 */
export function createNdjsonParser(
  onFrame: (frame: StreamFrame) => void,
): NdjsonParser {
  let buffer = "";

  const emit = (line: string) => {
    const trimmed = line.trim();
    if (!trimmed) return;
    try {
      onFrame(JSON.parse(trimmed) as StreamFrame);
    } catch {
      /* skip malformed line */
    }
  };

  return {
    push(chunk: string) {
      buffer += chunk;
      let nl: number;
      while ((nl = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, nl);
        buffer = buffer.slice(nl + 1);
        emit(line);
      }
    },
    flush() {
      const line = buffer;
      buffer = "";
      emit(line);
    },
  };
}
