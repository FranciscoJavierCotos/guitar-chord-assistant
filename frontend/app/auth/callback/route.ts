import { NextRequest, NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

/**
 * Auth redirect target for email confirmation and password-recovery links
 * (B1 — #26). Supabase appends a one-time `?code=...`; we exchange it for a
 * session (PKCE), which sets the httpOnly auth cookies, then redirect onward.
 *
 * `next` is sanitized to a local path so the confirmation link can't be abused as
 * an open redirect to an external origin.
 */
export const dynamic = "force-dynamic";

function safeNext(raw: string | null): string {
  // Only allow same-origin absolute paths (must start with a single "/").
  if (raw && raw.startsWith("/") && !raw.startsWith("//")) return raw;
  return "/account";
}

export async function GET(req: NextRequest) {
  const { searchParams, origin } = req.nextUrl;
  const code = searchParams.get("code");
  const next = safeNext(searchParams.get("next"));

  if (code) {
    const supabase = createClient();
    const { error } = await supabase.auth.exchangeCodeForSession(code);
    if (!error) {
      return NextResponse.redirect(`${origin}${next}`);
    }
  }

  // No code or exchange failed — send the user to login with a generic error flag.
  return NextResponse.redirect(`${origin}/login?error=auth`);
}
