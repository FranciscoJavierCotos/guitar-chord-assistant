"use client";

import React, { useState } from "react";
import Chat from "@/components/Chat";
import ProgressionDisplay from "@/components/ProgressionDisplay";
import AuthNav from "@/components/AuthNav";
import { ActiveProgression } from "@/lib/types";

type MobileView = "chat" | "chords";

export default function Home() {
  const [activeProgression, setActiveProgression] = useState<ActiveProgression | null>(null);

  // Mobile-only: which section fills the screen. Desktop ignores this (both panels show).
  const [mobileView, setMobileView] = useState<MobileView>("chat");
  // Badge on the Chords tab when fresh diagrams arrive while the user is in Chat.
  const [chordsBadge, setChordsBadge] = useState(false);

  function handleProgressionUpdate(prog: ActiveProgression | null) {
    setActiveProgression(prog);
    if (prog) setChordsBadge(true);
  }

  function selectView(view: MobileView) {
    setMobileView(view);
    if (view === "chords") setChordsBadge(false);
  }

  return (
    <div className="flex flex-col h-full bg-[#0D0B08]">
      {/* ─── Header ────────────────────────────────────────────────────────── */}
      <header className="flex-shrink-0 flex items-center justify-between gap-3 px-4 sm:px-6 py-3 border-b border-[#2E2920] bg-[#0D0B08] z-10">
        <div className="flex items-center gap-2.5 min-w-0">
          {/* Logo */}
          <svg className="flex-shrink-0" width="28" height="28" viewBox="0 0 28 28" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path
              d="M14 2C9.2 2 5 6.5 5 12C5 17.5 10 23 14 26C18 23 23 17.5 23 12C23 6.5 18.8 2 14 2Z"
              fill="#E8820C"
              stroke="#B85F00"
              strokeWidth="1.2"
            />
            <line x1="10" y1="12" x2="18" y2="12" stroke="white" strokeWidth="1.5" strokeLinecap="round" />
            <line x1="10" y1="9" x2="18" y2="9" stroke="white" strokeWidth="1" strokeLinecap="round" strokeOpacity="0.6" />
            <line x1="10" y1="15" x2="18" y2="15" stroke="white" strokeWidth="1" strokeLinecap="round" strokeOpacity="0.6" />
          </svg>
          <div className="min-w-0">
            <h1
              className="string-shimmer text-lg sm:text-xl font-bold leading-none"
              style={{ fontFamily: "'Playfair Display', serif" }}
            >
              ChordCoach
            </h1>
            <p className="hidden sm:block text-[#5A5244] text-[10px] font-mono tracking-widest uppercase leading-none mt-0.5">
              Learn the language of music
            </p>
          </div>
        </div>

        <AuthNav />
      </header>

      {/* ─── Mobile section switcher (hidden on desktop) ────────────────────── */}
      <div className="md:hidden flex-shrink-0 flex gap-1 p-1 bg-[#120F0B] border-b border-[#2E2920]">
        <button
          onClick={() => selectView("chat")}
          aria-pressed={mobileView === "chat"}
          className={`flex-1 flex items-center justify-center gap-2 py-2 rounded-lg text-sm font-medium transition-all duration-150 ${
            mobileView === "chat"
              ? "bg-[#252017] text-[#E8820C] shadow-[inset_0_0_0_1px_rgba(232,130,12,0.4)]"
              : "text-[#9A8F78] hover:text-[#F0EAD6]"
          }`}
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none">
            <path d="M21 11.5a8.38 8.38 0 0 1-8.5 8.5 8.5 8.5 0 0 1-3.8-.9L3 21l1.9-5.7A8.38 8.38 0 0 1 4 11.5 8.5 8.5 0 0 1 12.5 3 8.38 8.38 0 0 1 21 11.5z"
              stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          Chat
        </button>
        <button
          onClick={() => selectView("chords")}
          aria-pressed={mobileView === "chords"}
          className={`relative flex-1 flex items-center justify-center gap-2 py-2 rounded-lg text-sm font-medium transition-all duration-150 ${
            mobileView === "chords"
              ? "bg-[#252017] text-[#E8820C] shadow-[inset_0_0_0_1px_rgba(232,130,12,0.4)]"
              : "text-[#9A8F78] hover:text-[#F0EAD6]"
          }`}
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none">
            <rect x="4" y="3" width="16" height="18" rx="2" stroke="currentColor" strokeWidth="2" />
            <path d="M9 7v10M15 7v10M4 11h16" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          </svg>
          Chords
          {chordsBadge && (
            <span className="absolute top-1.5 right-3 w-2 h-2 rounded-full bg-[#E8820C] animate-pulse" />
          )}
        </button>
      </div>

      {/* ─── Main layout ───────────────────────────────────────────────────── */}
      <div className="flex flex-1 overflow-hidden flex-col md:flex-row min-h-0">
        {/* Chat panel (55% on desktop / full screen on mobile when active) */}
        <div
          className={`${
            mobileView === "chat" ? "flex" : "hidden"
          } md:flex flex-col flex-1 md:flex-none md:w-[55%] border-r border-[#2E2920] overflow-hidden min-h-0`}
        >
          <Chat
            onProgressionUpdate={handleProgressionUpdate}
          />
        </div>

        {/* Chord display panel (45% on desktop / full screen on mobile when active) */}
        <div
          className={`${
            mobileView === "chords" ? "flex" : "hidden"
          } md:flex md:w-[45%] flex-col flex-1 md:flex-none bg-[#0D0B08] overflow-hidden min-h-0`}
        >
          <div className="flex-shrink-0 px-5 py-3 border-b border-[#2E2920]">
            <p className="text-[#5A5244] text-xs font-mono uppercase tracking-widest">
              Chord Diagrams
            </p>
          </div>
          <div className="flex-1 overflow-y-auto px-5 py-4">
            <ProgressionDisplay progression={activeProgression} />
          </div>
        </div>
      </div>
    </div>
  );
}
