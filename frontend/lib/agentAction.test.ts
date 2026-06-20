import { describe, it, expect } from "vitest";
import { parseAgentAction } from "@/lib/agentAction";

describe("parseAgentAction", () => {
  it("extracts a show_chords action from the trailing json block", () => {
    const text = [
      "Here's a classic blues progression in E:",
      "",
      "```json",
      '{ "action": "show_chords", "chords": ["E", "A", "B7"], "progression_name": "12-bar blues", "bpm_suggestion": 120 }',
      "```",
    ].join("\n");

    expect(parseAgentAction(text)).toEqual({
      action: "show_chords",
      chords: ["E", "A", "B7"],
      progression_name: "12-bar blues",
      bpm_suggestion: 120,
    });
  });

  it("extracts a single show_chord action", () => {
    const text = 'Play it like this.\n```json\n{"action": "show_chord", "chord": "F"}\n```';
    expect(parseAgentAction(text)).toEqual({ action: "show_chord", chord: "F" });
  });

  it("returns null when there is no json block", () => {
    expect(parseAgentAction("Just some plain prose with no diagram.")).toBeNull();
  });

  it("returns null for a json block missing the action key", () => {
    const text = '```json\n{ "chords": ["C", "G"] }\n```';
    expect(parseAgentAction(text)).toBeNull();
  });

  it("returns null for a malformed json block instead of throwing", () => {
    const text = '```json\n{ "action": "show_chords", "chords": [ }\n```';
    expect(parseAgentAction(text)).toBeNull();
  });

  it("parses the first json block when several are present", () => {
    const text = [
      '```json',
      '{ "action": "show_chord", "chord": "Am" }',
      '```',
      "and later",
      '```json',
      '{ "action": "show_chord", "chord": "G" }',
      '```',
    ].join("\n");

    expect(parseAgentAction(text)).toEqual({ action: "show_chord", chord: "Am" });
  });
});
