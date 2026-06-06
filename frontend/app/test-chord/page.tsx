"use client";

import ChordDiagram from "@/components/ChordDiagram";
import { ChordPosition } from "@/lib/types";

const SAMPLE_CHORDS: ChordPosition[] = [
  {
    name: "Am", full_name: "A minor",
    positions: [-1, 0, 2, 2, 1, 0], fingers: [0, 0, 2, 3, 1, 0], base_fret: 1,
  },
  {
    name: "G", full_name: "G major",
    positions: [3, 2, 0, 0, 0, 3], fingers: [2, 1, 0, 0, 0, 3], base_fret: 1,
  },
  {
    name: "F", full_name: "F major (barre)",
    positions: [1, 1, 2, 3, 3, 1], fingers: [1, 1, 2, 3, 4, 1], base_fret: 1,
    barre: { from_string: 0, to_string: 5, fret: 1, finger: 1 },
  },
  {
    name: "Bm", full_name: "B minor (barre)",
    positions: [2, 2, 4, 4, 3, 2], fingers: [1, 1, 3, 4, 2, 1], base_fret: 2,
    barre: { from_string: 0, to_string: 5, fret: 2, finger: 1 },
  },
  {
    name: "Cmaj7", full_name: "C major 7th",
    positions: [-1, 3, 2, 0, 0, 0], fingers: [0, 3, 2, 0, 0, 0], base_fret: 1,
  },
  {
    name: "E", full_name: "E major",
    positions: [0, 2, 2, 1, 0, 0], fingers: [0, 2, 3, 1, 0, 0], base_fret: 1,
  },
];

export default function TestChordPage() {
  return (
    <div className="min-h-screen bg-[#0D0B08] p-8">
      <h1 className="text-[#F0EAD6] text-2xl font-bold mb-2" style={{ fontFamily: "'Playfair Display', serif" }}>
        Chord Diagram Test
      </h1>
      <p className="text-[#9A8F78] text-sm mb-8">Visual test for all chord diagram sizes and types.</p>

      {(["sm", "md", "lg"] as const).map((size) => (
        <div key={size} className="mb-10">
          <h2 className="text-[#E8820C] text-sm font-mono uppercase tracking-widest mb-4">
            Size: {size}
          </h2>
          <div className="flex flex-wrap gap-6">
            {SAMPLE_CHORDS.map((chord) => (
              <div key={`${size}-${chord.name}`} className="flex flex-col items-center gap-2">
                <ChordDiagram chord={chord} size={size} />
                <span className="text-[#9A8F78] text-xs font-mono">{chord.name}</span>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
