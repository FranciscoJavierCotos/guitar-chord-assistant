"use client";

/**
 * Browser-side Supabase client (B1 — #26). Used by the sign-in / sign-up / reset
 * forms in client components. Auth state is persisted by @supabase/ssr into cookies
 * (not localStorage), so the session is readable server-side by the proxy and the
 * access token is never exposed to arbitrary JS as a bare localStorage value.
 */
import { createBrowserClient } from "@supabase/ssr";
import { SUPABASE_ANON_KEY, SUPABASE_URL } from "./env";

export function createClient() {
  return createBrowserClient(SUPABASE_URL, SUPABASE_ANON_KEY);
}
