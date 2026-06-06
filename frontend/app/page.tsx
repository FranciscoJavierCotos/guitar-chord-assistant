"use client";

import React, { useState } from "react";
import Chat from "@/components/Chat";
import ProgressionDisplay from "@/components/ProgressionDisplay";
import ScaleSelector from "@/components/ScaleSelector";
import { ActiveProgression, ScaleKey, ScaleType } from "@/lib/types";

export default function Home() {
  const [selectedKey, setSelectedKey] = useState<ScaleKey>("C");
  const [selectedScale, setSelectedScale] = useState<ScaleType>("Major");
  const [activeProgression, setActiveProgression] = useState<ActiveProgression | null>(null);

  return (
    <div className="flex flex-col h-full bg-[#0D0B08]">
      {/* ─── Header ────────────────────────────────────────────────────────── */}
      <header className="flex-shrink-0 flex items-center justify-between px-6 py-3 border-b border-[#2E2920] bg-[#0D0B08] z-10">
        <div className="flex items-center gap-3">
          {/* Logo */}
          <svg width="28" height="28" viewBox="0 0 28 28" fill="none" xmlns="http://www.w3.org/2000/svg">
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
          <div>
            <h1
              className="string-shimmer text-xl font-bold leading-none"
              style={{ fontFamily: "'Playfair Display', serif" }}
            >
              ChordCoach
            </h1>
            <p className="text-[#5A5244] text-[10px] font-mono tracking-widest uppercase leading-none mt-0.5">
              Learn the language of music
            </p>
          </div>
        </div>

        <ScaleSelector
          selectedKey={selectedKey}
          selectedScale={selectedScale}
          onKeyChange={setSelectedKey}
          onScaleChange={setSelectedScale}
        />
      </header>

      {/* ─── Main layout ───────────────────────────────────────────────────── */}
      <div className="flex flex-1 overflow-hidden flex-col md:flex-row">
        {/* Chat panel (55%) */}
        <div className="flex flex-col md:w-[55%] border-r border-[#2E2920] overflow-hidden order-2 md:order-1 h-[50vh] md:h-auto">
          <Chat
            selectedKey={selectedKey}
            selectedScale={selectedScale}
            onProgressionUpdate={setActiveProgression}
          />
        </div>

        {/* Chord display panel (45%) */}
        <div className="md:w-[45%] flex flex-col bg-[#0D0B08] overflow-hidden order-1 md:order-2 h-[50vh] md:h-auto">
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
