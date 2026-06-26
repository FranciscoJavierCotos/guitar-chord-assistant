/**
 * Supabase public client config (B1 — #26). Both values are intentionally
 * NEXT_PUBLIC_: the browser runs Supabase Auth, and the anon/publishable key is
 * a PUBLIC key by design — Row-Level Security is the real boundary. This is the
 * one sanctioned exception to "no NEXT_PUBLIC_ secrets"; the service-role key is
 * a true secret and lives only in the backend.
 */
export const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
export const SUPABASE_ANON_KEY = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "";

/** True when both public Supabase values are present, so auth can run. */
export function supabaseConfigured(): boolean {
  return Boolean(SUPABASE_URL && SUPABASE_ANON_KEY);
}
