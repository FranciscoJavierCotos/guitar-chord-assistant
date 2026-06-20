import { AgentAction } from "@/lib/types";

/**
 * Extract the trailing ```json action block that every chord-display response
 * ends with. The frontend uses this to drive the chord diagram panel, so the
 * contract is significant — see CLAUDE.md "Structured Output Protocol".
 *
 * Returns null when there is no well-formed block (no fence, no `"action"` key,
 * or invalid JSON) so callers can simply render the message text unchanged.
 */
export function parseAgentAction(text: string): AgentAction | null {
  const match = text.match(/```json\s*(\{[\s\S]*?"action"\s*:[\s\S]*?\})\s*```/);
  if (!match) return null;
  try {
    return JSON.parse(match[1]) as AgentAction;
  } catch {
    return null;
  }
}
