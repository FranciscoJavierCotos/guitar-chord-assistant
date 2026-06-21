"use client";

import React, { useRef, useEffect, useState, useCallback } from "react";
import { v4 as uuidv4 } from "uuid";
import { ChatMessage, AgentAction, ActiveProgression, ChordPosition } from "@/lib/types";
import { parseAgentAction } from "@/lib/agentAction";
import { createNdjsonParser } from "@/lib/streamFrames";
import MessageBubble from "./MessageBubble";
import PracticeLog from "./PracticeLog";

const QUICK_PROMPTS = [
  "Give me a blues progression in E",
  "How do I play an F chord?",
  "Teach me a beginner pop progression",
  "What's a good jazz ii-V-I?",
  "Explain why Am-F-C-G works",
  "What have I been practicing?",
  "Chords inspired by a song...",
];

// The browser only ever calls our own same-origin /api routes. Those Next.js
// route handlers attach the server-only X-Internal-Token and proxy to the backend,
// so the secret never reaches the client.
const MAX_USER_TURNS = 20;

const WELCOME_MESSAGE: ChatMessage = {
  id: "welcome",
  role: "assistant",
  content:
    "Hey! I'm **ChordCoach** 🎸 — your personal guitar progression mentor.\n\n" +
    "Tell me what you want to play, what style you're into, or just ask me to teach you something. " +
    "I'll recommend progressions and show you interactive chord diagrams right in the panel to the right.\n\n" +
    "What would you like to learn today?",
  timestamp: Date.now(),
};

interface Props {
  onProgressionUpdate: (prog: ActiveProgression | null) => void;
}

export default function Chat({ onProgressionUpdate }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([WELCOME_MESSAGE]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [logRefresh, setLogRefresh] = useState(0);
  const [skillLevel, setSkillLevel] = useState("");
  const [logOpen, setLogOpen] = useState(false);
  // Mobile: suggestion prompts are collapsed by default to keep the chat roomy.
  const [promptsOpen, setPromptsOpen] = useState(false);
  // Mobile: the input sits between two buttons, so the full placeholder sentence
  // overflows. Use a shorter prompt on narrow screens. Starts false to match SSR.
  const [isNarrow, setIsNarrow] = useState(false);
  const [sessionId, setSessionId] = useState<string>(() => {
    if (typeof window !== "undefined") {
      const stored = localStorage.getItem("chordcoach_session");
      if (stored) return stored;
      const id = uuidv4();
      localStorage.setItem("chordcoach_session", id);
      return id;
    }
    return uuidv4();
  });

  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const userTurnCount = messages.filter((m) => m.role === "user").length;
  const contextPct = Math.min((userTurnCount / MAX_USER_TURNS) * 100, 100);
  const isAtLimit = userTurnCount >= MAX_USER_TURNS;

  function startNewChat() {
    const newId = uuidv4();
    localStorage.setItem("chordcoach_session", newId);
    setSessionId(newId);
    setMessages([{ ...WELCOME_MESSAGE, timestamp: Date.now() }]);
    onProgressionUpdate(null);
    setInput("");
    setSkillLevel("");
    setLogRefresh(0);
    setLogOpen(false);
  }

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    const mq = window.matchMedia("(max-width: 640px)");
    const update = () => setIsNarrow(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);

  const fetchSkillLevel = useCallback(async () => {
    if (!sessionId) return;
    try {
      const res = await fetch(`/api/backend/api/session/${sessionId}/practice-log`);
      if (res.ok) {
        const data = await res.json();
        if (data.skill_level) setSkillLevel(data.skill_level);
      }
    } catch { /* ignore */ }
  }, [sessionId]);

  useEffect(() => { fetchSkillLevel(); }, [fetchSkillLevel]);

  async function fetchChordData(chordName: string): Promise<ChordPosition | null> {
    try {
      const res = await fetch(`/api/backend/api/chord/${encodeURIComponent(chordName)}`);
      if (!res.ok) return null;
      return res.json();
    } catch {
      return null;
    }
  }

  async function handleAgentAction(action: AgentAction) {
    if (action.action === "show_chords" && action.chords?.length) {
      const chordDataArr = await Promise.all(action.chords.map(fetchChordData));
      const available = chordDataArr.filter(Boolean) as ChordPosition[];
      if (available.length > 0) {
        onProgressionUpdate({
          chords: available,
          chordNames: action.chords,
          progressionName: action.progression_name ?? "Chord Progression",
          bpm: action.bpm_suggestion,
        });
      }
    } else if (action.action === "show_chord" && action.chord) {
      const chordData = await fetchChordData(action.chord);
      if (chordData) {
        onProgressionUpdate({
          chords: [chordData],
          chordNames: [action.chord],
          progressionName: chordData.full_name ?? action.chord,
        });
      }
    } else if (action.action === "show_practice_log") {
      setLogOpen(true);
    }
  }

  async function sendMessage(text: string) {
    if (isAtLimit) return;
    const assistantId = uuidv4();
    const userMsg: ChatMessage = { id: uuidv4(), role: "user", content: text, timestamp: Date.now() };
    // Placeholder carries a live status label (no content yet) so the bubble shows
    // the typing indicator + "Thinking…" until the first answer token streams in.
    const placeholder: ChatMessage = {
      id: assistantId,
      role: "assistant",
      content: "",
      status: "Thinking…",
      timestamp: Date.now(),
    };

    setMessages((prev) => [...prev, userMsg, placeholder]);
    setLoading(true);
    setInput("");

    try {
      const res = await fetch(`/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text,
          session_id: sessionId,
          context: { skill_level: skillLevel },
        }),
      });

      if (!res.ok || !res.body) {
        throw new Error(`Server responded with ${res.status}`);
      }

      // The stream is NDJSON: one JSON event frame per line. Status frames show
      // progress; token frames carry answer-text deltas; an error frame replaces
      // the message text. Parse line-by-line so text appears as it's generated.
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let responseText = "";

      const applyFrame = (frame: { type?: string; label?: string; text?: string; message?: string }) => {
        if (frame.type === "status") {
          // Only surface status until the answer starts streaming.
          if (!responseText) {
            setMessages((prev) =>
              prev.map((m) => (m.id === assistantId ? { ...m, status: frame.label } : m)),
            );
          }
        } else if (frame.type === "reset") {
          // The text streamed so far was an intermediate planning preamble, not the
          // answer. Clear it and fall back to the typing indicator until the real
          // answer streams in. (See run_agent_stream's run_id tracking.)
          responseText = "";
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId ? { ...m, content: "", status: "Thinking…" } : m,
            ),
          );
        } else if (frame.type === "token" && frame.text) {
          responseText += frame.text;
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId ? { ...m, content: responseText, status: undefined } : m,
            ),
          );
        } else if (frame.type === "error") {
          responseText = frame.message ?? "Sorry, something went wrong.";
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId ? { ...m, content: responseText, status: undefined } : m,
            ),
          );
        }
      };

      const parser = createNdjsonParser(applyFrame);

      // eslint-disable-next-line no-constant-condition
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        parser.push(decoder.decode(value, { stream: true }));
      }
      parser.push(decoder.decode());
      parser.flush();

      if (!responseText) {
        // Stream finished with no token frames — fall back to a placeholder.
        responseText = "Sorry, I didn't get a response.";
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId ? { ...m, content: responseText, status: undefined } : m,
          ),
        );
      }

      const action = parseAgentAction(responseText);
      if (action) await handleAgentAction(action);
      setLogRefresh((n) => n + 1);
      fetchSkillLevel();
    } catch (err) {
      const errorMsg: ChatMessage = {
        id: uuidv4(),
        role: "assistant",
        content:
          "I'm having trouble connecting to the server right now. " +
          "Please try again in a moment.",
        timestamp: Date.now(),
      };
      setMessages((prev) => prev.filter((m) => m.id !== assistantId).concat(errorMsg));
    } finally {
      setLoading(false);
    }
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = input.trim();
    if (!trimmed || loading) return;
    sendMessage(trimmed);
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e as unknown as React.FormEvent);
    }
  }

  // bar color: neutral → amber → orange → red
  const barColor =
    contextPct >= 95
      ? "#EF4444"
      : contextPct >= 80
      ? "#E8820C"
      : contextPct >= 60
      ? "#C9A227"
      : "#3D3525";

  return (
    <div className="flex flex-col h-full">
      {/* Session header: new chat + context bar */}
      <div className="flex-shrink-0 px-4 pt-2 pb-1.5 border-b border-[#2E2920]">
        <div className="flex items-center justify-between gap-3">
          {/* Context bar */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center justify-between mb-1">
              <span className="text-[10px] font-mono text-[#5A5244] uppercase tracking-wider">
                Session
              </span>
              <span
                className="text-[10px] font-mono tracking-wide"
                style={{ color: contextPct >= 80 ? barColor : "#5A5244" }}
              >
                {userTurnCount}/{MAX_USER_TURNS}
                {contextPct >= 80 && " · start new chat soon"}
              </span>
            </div>
            <div className="h-1 rounded-full bg-[#1A1712] overflow-hidden">
              <div
                className="h-full rounded-full transition-all duration-500"
                style={{ width: `${contextPct}%`, backgroundColor: barColor }}
              />
            </div>
          </div>

          {/* New Chat button */}
          <button
            onClick={startNewChat}
            title="Start a new chat session"
            className="flex-shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-lg
                       border border-[#2E2920] bg-[#1A1712] text-[#9A8F78]
                       hover:border-[#E8820C] hover:text-[#E8820C]
                       active:scale-95 transition-all duration-150 text-xs font-medium"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
              <path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
            </svg>
            New Chat
          </button>
        </div>
      </div>

      {/* Message list */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-1">
        {messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} />
        ))}

        {/* Limit reached notice */}
        {isAtLimit && (
          <div className="mx-auto max-w-sm text-center py-4">
            <p className="text-sm text-[#9A8F78] mb-3">
              You&apos;ve reached the session limit. Start a new chat to keep learning!
            </p>
            <button
              onClick={startNewChat}
              className="px-4 py-2 rounded-xl bg-[#E8820C] text-white text-sm font-semibold
                         hover:bg-[#C9A227] active:scale-95 transition-all duration-150"
            >
              Start New Chat
            </button>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Practice log */}
      <PracticeLog
        sessionId={sessionId}
        refreshTrigger={logRefresh}
        forceOpen={logOpen}
        onOpenChange={setLogOpen}
      />

      {/* Quick prompts — always shown on desktop, toggleable on mobile.
          On mobile they scroll horizontally in a single row to save vertical space. */}
      {!isAtLimit && (
        <div
          className={`${promptsOpen ? "flex" : "hidden"} md:flex px-4 pb-2 gap-1.5
                     overflow-x-auto md:flex-wrap whitespace-nowrap md:whitespace-normal
                     [scrollbar-width:none] [-ms-overflow-style:none]`}
        >
          {QUICK_PROMPTS.map((prompt) => (
            <button
              key={prompt}
              onClick={() => {
                setPromptsOpen(false);
                sendMessage(prompt);
              }}
              disabled={loading}
              className="flex-shrink-0 text-xs px-3 py-1.5 rounded-full bg-[#252017] border border-[#2E2920]
                         text-[#9A8F78] hover:border-[#E8820C] hover:text-[#E8820C]
                         transition-colors duration-150 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {prompt}
            </button>
          ))}
        </div>
      )}

      {/* Input area */}
      <div className="px-4 pb-4">
        {isAtLimit ? (
          <div className="flex items-center justify-center h-10 text-xs text-[#5A5244] font-mono">
            Session ended — click &quot;New Chat&quot; to continue
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="flex gap-2 items-end">
            {/* Suggestions toggle — mobile only */}
            <button
              type="button"
              onClick={() => setPromptsOpen((o) => !o)}
              aria-pressed={promptsOpen}
              aria-label="Toggle suggested prompts"
              title="Suggested prompts"
              className={`md:hidden flex-shrink-0 w-10 h-10 rounded-xl border flex items-center justify-center
                          transition-all duration-150 active:scale-95
                          ${promptsOpen
                            ? "border-[#E8820C] text-[#E8820C] bg-[#252017]"
                            : "border-[#2E2920] text-[#9A8F78] bg-[#1A1712] hover:text-[#E8820C]"}`}
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                <path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-4 10.5c.6.6 1 1.2 1 2.5h6c0-1.3.4-1.9 1-2.5A6 6 0 0 0 12 3z"
                  stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={isNarrow ? "Ask about chords or theory…" : "Ask about chords, progressions, or music theory…"}
              rows={1}
              disabled={loading}
              className="flex-1 bg-[#1A1712] border border-[#2E2920] text-[#F0EAD6] placeholder-[#5A5244]
                         rounded-xl px-4 py-3 text-sm resize-none focus:outline-none
                         focus:border-[#E8820C] focus:ring-1 focus:ring-[#E8820C]
                         transition-colors disabled:opacity-60 max-h-36 overflow-y-auto"
              style={{ lineHeight: "1.5" }}
              onInput={(e) => {
                const t = e.currentTarget;
                t.style.height = "auto";
                t.style.height = Math.min(t.scrollHeight, 144) + "px";
              }}
            />
            <button
              type="submit"
              disabled={!input.trim() || loading}
              className="flex-shrink-0 w-10 h-10 rounded-xl bg-[#E8820C] text-white font-bold
                         flex items-center justify-center
                         hover:bg-[#C9A227] active:scale-95
                         disabled:opacity-40 disabled:cursor-not-allowed disabled:active:scale-100
                         transition-all duration-150"
            >
              {loading ? (
                <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="white" strokeWidth="3" />
                  <path className="opacity-75" fill="white" d="M4 12a8 8 0 018-8v8H4z" />
                </svg>
              ) : (
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                  <path d="M22 2L11 13" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
                  <path d="M22 2L15 22L11 13L2 9L22 2Z" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              )}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
