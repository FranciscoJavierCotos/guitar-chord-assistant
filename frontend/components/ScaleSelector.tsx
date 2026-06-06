"use client";

import React from "react";
import { ScaleKey, ScaleType } from "@/lib/types";

const KEYS: ScaleKey[] = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
const SCALES: ScaleType[] = ["Major", "Minor", "Pentatonic", "Blues", "Dorian", "Mixolydian"];

interface Props {
  selectedKey: ScaleKey;
  selectedScale: ScaleType;
  onKeyChange: (k: ScaleKey) => void;
  onScaleChange: (s: ScaleType) => void;
}

const selectClass =
  "bg-[#1A1712] border border-[#2E2920] text-[#F0EAD6] text-xs rounded-lg px-3 py-1.5 " +
  "focus:outline-none focus:border-[#E8820C] focus:ring-1 focus:ring-[#E8820C] " +
  "cursor-pointer hover:border-[#5A5244] transition-colors appearance-none " +
  "bg-[url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='%239A8F78'/%3E%3C/svg%3E\")] " +
  "bg-no-repeat bg-[right_8px_center] pr-7";

export default function ScaleSelector({ selectedKey, selectedScale, onKeyChange, onScaleChange }: Props) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-[#5A5244] text-xs font-mono uppercase tracking-wider">Key</span>
      <select
        value={selectedKey}
        onChange={(e) => onKeyChange(e.target.value as ScaleKey)}
        className={selectClass}
      >
        {KEYS.map((k) => (
          <option key={k} value={k}>{k}</option>
        ))}
      </select>

      <span className="text-[#5A5244] text-xs font-mono uppercase tracking-wider ml-1">Scale</span>
      <select
        value={selectedScale}
        onChange={(e) => onScaleChange(e.target.value as ScaleType)}
        className={selectClass}
      >
        {SCALES.map((s) => (
          <option key={s} value={s}>{s}</option>
        ))}
      </select>
    </div>
  );
}
