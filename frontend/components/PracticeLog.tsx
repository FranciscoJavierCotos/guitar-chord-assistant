"use client";

import React, { useState, useEffect, useCallback } from "react";
import type { PracticeItem } from "@/lib/types";

interface Props {
  sessionId: string;
  refreshTrigger: number;
  forceOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
}

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
const LS_KEY = "chordcoach_practice_log";

const TYPE_ICON: Record<string, string> = {
  progression: "♫",
  song_search: "♪",
  chord: "♩",
};

function loadLocalLog(): PracticeItem[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(LS_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function mergeAndSave(serverItems: PracticeItem[]): PracticeItem[] {
  const local = loadLocalLog();
  const seen = new Set(local.map((i) => i.timestamp));
  const merged = [...local, ...serverItems.filter((i) => !seen.has(i.timestamp))];
  const capped = merged.slice(-100);
  try {
    localStorage.setItem(LS_KEY, JSON.stringify(capped));
  } catch {
    /* ignore storage errors */
  }
  return capped;
}

export default function PracticeLog({ sessionId, refreshTrigger, forceOpen, onOpenChange }: Props) {
  const [log, setLog] = useState<PracticeItem[]>([]);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    setLog(loadLocalLog());
  }, []);

  useEffect(() => {
    if (forceOpen) setOpen(true);
  }, [forceOpen]);

  const toggle = () => {
    const next = !open;
    setOpen(next);
    onOpenChange?.(next);
  };

  const fetchLog = useCallback(async () => {
    if (!sessionId) return;
    try {
      const res = await fetch(`${BACKEND_URL}/api/session/${sessionId}/practice-log`);
      if (res.ok) {
        const data = await res.json();
        const merged = mergeAndSave(data.practice_log ?? []);
        setLog(merged);
      }
    } catch {
      /* silently keep local state */
    }
  }, [sessionId]);

  useEffect(() => {
    fetchLog();
  }, [fetchLog, refreshTrigger]);

  const recentItems = [...log].reverse().slice(0, 8);

  if (log.length === 0) return null;

  return (
    <div className="border-t border-[#2E2920]">
      <button
        onClick={toggle}
        className="w-full text-left px-4 py-2 flex items-center gap-2 text-[10px] font-mono
                   text-[#5A5244] uppercase tracking-widest hover:text-[#9A8F78] transition-colors"
      >
        <span>{open ? "▼" : "▶"}</span>
        <span>Practice log</span>
        <span className="ml-auto bg-[#2E2920] text-[#E8820C] px-1.5 py-0.5 rounded text-[9px]">
          {log.length}
        </span>
      </button>

      {open && (
        <div className="px-4 pb-3 space-y-1.5">
          {recentItems.map((item, i) => {
            const ageMins = Math.round((Date.now() / 1000 - item.timestamp) / 60);
            const ageStr = ageMins < 1 ? "just now" : `${ageMins}m ago`;
            return (
              <div key={i} className="flex items-start gap-2 text-xs">
                <span className="text-[#E8820C] font-mono shrink-0 mt-0.5">
                  {TYPE_ICON[item.type] ?? "♫"}
                </span>
                <div className="min-w-0">
                  <span className="text-[#F0EAD6]">{item.name}</span>
                  {item.chords.length > 0 && (
                    <span className="text-[#5A5244] ml-2 font-mono text-[10px]">
                      {item.chords.join(" → ")}
                    </span>
                  )}
                  <span className="text-[#3A3428] ml-2 text-[10px]">{ageStr}</span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
