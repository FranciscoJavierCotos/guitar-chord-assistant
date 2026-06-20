import { describe, it, expect, vi } from "vitest";
import { createNdjsonParser, type StreamFrame } from "@/lib/streamFrames";

/** Collect every frame the parser emits for the given pushes. */
function collect(push: (p: ReturnType<typeof createNdjsonParser>) => void): StreamFrame[] {
  const frames: StreamFrame[] = [];
  const parser = createNdjsonParser((f) => frames.push(f));
  push(parser);
  return frames;
}

describe("createNdjsonParser", () => {
  it("emits one frame per complete newline-terminated line", () => {
    const frames = collect((p) => {
      p.push('{"type":"status","label":"Thinking…"}\n');
      p.push('{"type":"token","text":"Hello"}\n');
    });

    expect(frames).toEqual([
      { type: "status", label: "Thinking…" },
      { type: "token", text: "Hello" },
    ]);
  });

  it("reassembles a frame split across two chunks", () => {
    const frames = collect((p) => {
      p.push('{"type":"token","te');
      p.push('xt":"world"}\n');
    });

    expect(frames).toEqual([{ type: "token", text: "world" }]);
  });

  it("splits multiple frames delivered in a single chunk", () => {
    const frames = collect((p) => {
      p.push('{"type":"token","text":"a"}\n{"type":"token","text":"b"}\n');
    });

    expect(frames).toEqual([
      { type: "token", text: "a" },
      { type: "token", text: "b" },
    ]);
  });

  it("emits a trailing frame with no newline only on flush", () => {
    const frames: StreamFrame[] = [];
    const parser = createNdjsonParser((f) => frames.push(f));

    parser.push('{"type":"token","text":"end"}');
    expect(frames).toEqual([]); // no newline yet — buffered, not emitted

    parser.flush();
    expect(frames).toEqual([{ type: "token", text: "end" }]);
  });

  it("skips blank and malformed lines without aborting the stream", () => {
    const onFrame = vi.fn();
    const parser = createNdjsonParser(onFrame);

    parser.push('\n');                                  // blank
    parser.push('not json at all\n');                   // malformed
    parser.push('{"type":"token","text":"ok"}\n');      // valid
    parser.flush();

    expect(onFrame).toHaveBeenCalledTimes(1);
    expect(onFrame).toHaveBeenCalledWith({ type: "token", text: "ok" });
  });

  it("does not re-emit buffered content on a no-op flush", () => {
    const frames = collect((p) => {
      p.push('{"type":"error","message":"boom"}\n');
      p.flush(); // buffer already empty
    });

    expect(frames).toEqual([{ type: "error", message: "boom" }]);
  });
});
