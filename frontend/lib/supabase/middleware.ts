import { createServerClient, type CookieOptions } from "@supabase/ssr";
import { NextRequest, NextResponse } from "next/server";
import { SUPABASE_ANON_KEY, SUPABASE_URL, supabaseConfigured } from "./env";

type CookieToSet = { name: string; value: string; options: CookieOptions };

/**
 * Refresh the Supabase auth session on every matched request (B1 — #26).
 *
 * Access tokens are short-lived; without a refresh on navigation the session
 * silently expires. @supabase/ssr handles this by reading the refresh-token cookie
 * and, when needed, writing rotated auth cookies onto the response. We must return
 * THIS response (with its cookies) for the refresh to stick — see the Supabase
 * Next.js middleware guidance. No-ops when Supabase isn't configured so the app
 * still runs DB-less.
 */
export async function updateSession(
  request: NextRequest,
  response: NextResponse,
): Promise<NextResponse> {
  if (!supabaseConfigured()) return response;

  const supabase = createServerClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
    cookies: {
      getAll() {
        return request.cookies.getAll();
      },
      setAll(cookiesToSet: CookieToSet[]) {
        cookiesToSet.forEach(({ name, value, options }) =>
          response.cookies.set(name, value, options),
        );
      },
    },
  });

  // Touch the user to trigger a refresh-if-needed; ignore the result here.
  await supabase.auth.getUser();
  return response;
}
