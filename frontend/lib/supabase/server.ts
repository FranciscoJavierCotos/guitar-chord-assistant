import "server-only";

/**
 * Server-side Supabase client (B1 — #26). Reads/writes the auth session from
 * httpOnly cookies via @supabase/ssr, so route handlers, server components, and
 * the same-origin backend proxy can see the signed-in user without the token ever
 * touching client JS.
 *
 * SECURITY: this module is `server-only` — importing it from a client component is
 * a build error. It uses the anon/publishable key (RLS-gated), never the
 * service-role key.
 */
import { createServerClient, type CookieOptions } from "@supabase/ssr";
import { cookies } from "next/headers";
import { SUPABASE_ANON_KEY, SUPABASE_URL } from "./env";

type CookieToSet = { name: string; value: string; options: CookieOptions };

export function createClient() {
  const cookieStore = cookies();
  return createServerClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
    cookies: {
      getAll() {
        return cookieStore.getAll();
      },
      setAll(cookiesToSet: CookieToSet[]) {
        // In a Server Component the cookie store is read-only; the middleware
        // (lib/supabase/middleware.ts) is what actually refreshes the session
        // cookies, so we swallow the error here per the @supabase/ssr guidance.
        try {
          cookiesToSet.forEach(({ name, value, options }) =>
            cookieStore.set(name, value, options),
          );
        } catch {
          /* called from a Server Component — safe to ignore */
        }
      },
    },
  });
}

/**
 * The signed-in user's Supabase access token, or null when anonymous. Read by the
 * same-origin proxy to forward identity to the backend as a Bearer token (the
 * backend then verifies it and applies RLS). `getUser()` re-validates the JWT with
 * Supabase rather than trusting the raw cookie, so a tampered cookie yields null.
 */
export async function getUserAccessToken(): Promise<string | null> {
  const supabase = createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return null;
  const {
    data: { session },
  } = await supabase.auth.getSession();
  return session?.access_token ?? null;
}
