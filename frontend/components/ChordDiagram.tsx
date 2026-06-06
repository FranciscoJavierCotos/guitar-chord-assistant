"use client";

import React from "react";
import { ChordPosition } from "@/lib/types";

interface ChordDiagramProps {
  chord: ChordPosition;
  size?: "sm" | "md" | "lg";
  highlighted?: boolean;
}

const SIZE_MAP = {
  sm: { width: 120, height: 180 },
  md: { width: 160, height: 220 },
  lg: { width: 200, height: 275 },
};

const STRING_NAMES = ["E", "A", "D", "G", "B", "e"];

export default function ChordDiagram({
  chord,
  size = "md",
  highlighted = false,
}: ChordDiagramProps) {
  const { width, height } = SIZE_MAP[size];
  const scale = width / 160;

  // Layout constants (at md=160 scale)
  const TOP_PAD = 48;           // space for string names + open/muted indicators
  const LEFT_PAD = 22;          // left margin
  const RIGHT_PAD = 22;         // right margin
  const FRET_HEIGHT = 34 * scale;
  const STRING_SPACING = ((width - LEFT_PAD - RIGHT_PAD) / 5);
  const NUM_FRETS = 5;

  const baseFret = chord.base_fret ?? 1;
  const showNut = baseFret === 1;

  // Chord positions relative to baseFret for rendering
  const relativePositions = chord.positions.map((p) =>
    p <= 0 ? p : p - baseFret + 1
  );

  // Colors
  const COL_NECK = "#1a1a1a";
  const COL_STRING = "#C0A86E";
  const COL_FRET = "#8B8B8B";
  const COL_DOT = "#E8820C";
  const COL_DOT_BORDER = "#B85F00";
  const COL_LABEL = "#aaa";
  const DOT_RADIUS = 12 * scale;
  const OPEN_RADIUS = 6 * scale;

  const svgWidth = width;
  const svgHeight = height;

  // x-coordinate for string index (0=E low, 5=e high)
  const sx = (i: number) => LEFT_PAD + i * STRING_SPACING;
  // y-coordinate for fret (0 = nut line, 1 = between fret 1 and 2, etc.)
  const fy = (fret: number) => TOP_PAD + (fret - 0.5) * FRET_HEIGHT;

  return (
    <svg
      width={svgWidth}
      height={svgHeight}
      viewBox={`0 0 ${svgWidth} ${svgHeight}`}
      xmlns="http://www.w3.org/2000/svg"
      style={{
        filter: highlighted
          ? "drop-shadow(0 0 8px rgba(232,130,12,0.6))"
          : undefined,
      }}
    >
      {/* Neck background */}
      <rect x={LEFT_PAD} y={TOP_PAD} width={width - LEFT_PAD - RIGHT_PAD} height={NUM_FRETS * FRET_HEIGHT} fill={COL_NECK} rx={2} />

      {/* Nut (thick bar at top when baseFret === 1) */}
      {showNut && (
        <rect
          x={LEFT_PAD}
          y={TOP_PAD}
          width={width - LEFT_PAD - RIGHT_PAD}
          height={4 * scale}
          fill="#D4C5A0"
          rx={1}
        />
      )}

      {/* Fret wires */}
      {Array.from({ length: NUM_FRETS }).map((_, i) => (
        <line
          key={`fret-${i}`}
          x1={LEFT_PAD}
          y1={TOP_PAD + (i + 1) * FRET_HEIGHT}
          x2={width - RIGHT_PAD}
          y2={TOP_PAD + (i + 1) * FRET_HEIGHT}
          stroke={COL_FRET}
          strokeWidth={1.5 * scale}
        />
      ))}

      {/* Strings */}
      {STRING_NAMES.map((_, i) => (
        <line
          key={`string-${i}`}
          x1={sx(i)}
          y1={TOP_PAD}
          x2={sx(i)}
          y2={TOP_PAD + NUM_FRETS * FRET_HEIGHT}
          stroke={COL_STRING}
          strokeWidth={i < 3 ? 2.5 * scale : 1.5 * scale}
        />
      ))}

      {/* String name labels */}
      {STRING_NAMES.map((name, i) => (
        <text
          key={`label-${i}`}
          x={sx(i)}
          y={12 * scale}
          textAnchor="middle"
          fontSize={11 * scale}
          fill={COL_LABEL}
          fontFamily="JetBrains Mono, monospace"
        >
          {name}
        </text>
      ))}

      {/* Open/muted indicators */}
      {chord.positions.map((pos, i) => {
        if (pos === 0) {
          return (
            <circle
              key={`open-${i}`}
              cx={sx(i)}
              cy={28 * scale}
              r={OPEN_RADIUS}
              fill="none"
              stroke="white"
              strokeWidth={1.5 * scale}
            />
          );
        }
        if (pos === -1) {
          return (
            <text
              key={`mute-${i}`}
              x={sx(i)}
              y={32 * scale}
              textAnchor="middle"
              fontSize={14 * scale}
              fill="#CC0000"
              fontWeight="bold"
              fontFamily="Arial, sans-serif"
            >
              ×
            </text>
          );
        }
        return null;
      })}

      {/* Barre indicator */}
      {chord.barre && (() => {
        const b = chord.barre;
        const relFret = b.fret - baseFret + 1;
        if (relFret < 1 || relFret > NUM_FRETS) return null;
        const x1 = sx(b.from_string);
        const x2 = sx(b.to_string);
        const y = fy(relFret);
        const barW = Math.abs(x2 - x1);
        return (
          <rect
            key="barre"
            x={Math.min(x1, x2) - DOT_RADIUS * 0.6}
            y={y - DOT_RADIUS}
            width={barW + DOT_RADIUS * 1.2}
            height={DOT_RADIUS * 2}
            rx={DOT_RADIUS}
            fill={COL_DOT}
            stroke={COL_DOT_BORDER}
            strokeWidth={1.5 * scale}
          />
        );
      })()}

      {/* Finger dots */}
      {chord.positions.map((pos, i) => {
        if (pos <= 0) return null;
        const relFret = pos - baseFret + 1;
        if (relFret < 1 || relFret > NUM_FRETS) return null;
        const finger = chord.fingers[i];
        const cx = sx(i);
        const cy = fy(relFret);

        // Skip individual dot if covered by a barre on this exact fret
        if (chord.barre && chord.barre.fret === pos && chord.barre.finger === finger) {
          // Still show if it's an inner string dot on top of barre
        }

        return (
          <g key={`dot-${i}`}>
            <circle
              cx={cx}
              cy={cy}
              r={DOT_RADIUS}
              fill={COL_DOT}
              stroke={COL_DOT_BORDER}
              strokeWidth={1.5 * scale}
            />
            {finger > 0 && (
              <text
                x={cx}
                y={cy + 4 * scale}
                textAnchor="middle"
                fontSize={12 * scale}
                fill="white"
                fontWeight="bold"
                fontFamily="DM Sans, Arial, sans-serif"
              >
                {finger}
              </text>
            )}
          </g>
        );
      })}

      {/* Fret position marker (when baseFret > 1) */}
      {baseFret > 1 && (
        <text
          x={width - RIGHT_PAD + 6 * scale}
          y={TOP_PAD + FRET_HEIGHT * 0.8}
          fontSize={10 * scale}
          fill={COL_LABEL}
          fontFamily="JetBrains Mono, monospace"
        >
          {baseFret}fr
        </text>
      )}
    </svg>
  );
}
