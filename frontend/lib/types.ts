export interface ChordPosition {
  name: string;
  full_name: string;
  positions: number[];   // [E, A, D, G, B, e] — -1=muted, 0=open, n=fret
  fingers: number[];     // 0=open/muted, 1–4=finger
  base_fret: number;
  barre?: {
    from_string: number;
    to_string: number;
    fret: number;
    finger: number;
  };
  notes?: string[];
  type?: string;
  difficulty?: string;
}

export interface Progression {
  id: string;
  name: string;
  genre: string[];
  key: string;
  chords: string[];
  roman: string[];
  difficulty: string;
  description: string;
  feel: string;
  tempo_bpm: number;
  tags: string[];
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: number;
}

export interface AgentAction {
  action: "show_chords" | "show_chord";
  chords?: string[];
  chord?: string;
  progression_name?: string;
  bpm_suggestion?: number;
}

export interface ActiveProgression {
  chords: ChordPosition[];
  chordNames: string[];
  progressionName: string;
  romanNumerals?: string[];
  bpm?: number;
}

export type ScaleKey =
  | "C" | "C#" | "D" | "D#" | "E" | "F"
  | "F#" | "G" | "G#" | "A" | "A#" | "B";

export type ScaleType =
  | "Major" | "Minor" | "Pentatonic" | "Blues" | "Dorian" | "Mixolydian";
