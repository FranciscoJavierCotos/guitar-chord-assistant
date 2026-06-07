"use client";

import React from "react";
import ChordDiagram from "./ChordDiagram";
import { ActiveProgression } from "@/lib/types";

interface Props {
  progression: ActiveProgression | null;
}

export default function ProgressionDisplay({ progression }: Props) {
  if (!progression) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-center px-8 select-none">
        <div className="text-6xl mb-6 opacity-30">🎸</div>
        <p className="text-[#5A5244] text-sm font-mono uppercase tracking-widest mb-2">
          Chord diagrams appear here
        </p>
        <p className="text-[#5A5244] text-xs max-w-xs">
          Ask ChordCoach to recommend a progression, or request a specific chord.
        </p>
      </div>
    );
  }

  const { chords, chordNames, progressionName, romanNumerals, bpm } = progression;

  return (
    <div className="flex flex-col h-full overflow-y-auto">
      {/* Progression header */}
      <div className="mb-4">
        <h3
          className="text-[#F0EAD6] text-lg font-semibold leading-tight"
          style={{ fontFamily: "'Playfair Display', serif" }}
        >
          {progressionName}
        </h3>
        {bpm && (
          <p className="text-[#5A5244] text-xs font-mono mt-1">
            Suggested tempo: {bpm} BPM
          </p>
        )}
      </div>

      {/* Chord diagrams grid */}
      <div className="grid grid-cols-2 gap-4 mb-4">
        {chords.map((chord, idx) => (
          <div
            key={`${chord.name}-${idx}`}
            className="relative flex flex-col items-center gap-2 p-3 bg-[#1A1712] border border-[#2E2920] rounded-xl
                       hover:border-[#E8820C] hover:shadow-[0_0_12px_rgba(232,130,12,0.15)] transition-all duration-200"
            style={{
              animation: `slideUp 0.3s ease-out ${idx * 80}ms both`,
            }}
          >
            {/* Order number */}
            <span className="absolute top-2.5 left-3 text-[#3E3528] text-[11px] font-mono select-none">
              {idx + 1}
            </span>
            <ChordDiagram chord={chord} size="sm" />
            <div className="text-center">
              <div
                className="text-[#F0EAD6] text-sm font-semibold"
                style={{ fontFamily: "'Playfair Display', serif" }}
              >
                {chord.name}
              </div>
              {romanNumerals?.[idx] && (
                <div className="text-[#E8820C] text-xs font-mono">{romanNumerals[idx]}</div>
              )}
              {chord.difficulty && (
                <div className="text-[#5A5244] text-[10px] mt-0.5">{chord.difficulty}</div>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Theory / quick help placeholder */}
      {chords.length > 1 && (
        <div className="mt-auto pt-3 border-t border-[#2E2920]">
          <p className="text-[#5A5244] text-xs font-mono uppercase tracking-wider mb-1">
            Sequence
          </p>
          <div className="flex flex-wrap gap-1.5">
            {chordNames.map((name, i) => (
              <span
                key={i}
                className="px-2 py-1 bg-[#252017] border border-[#2E2920] rounded text-[#C9A227] text-xs font-mono"
              >
                {name}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
