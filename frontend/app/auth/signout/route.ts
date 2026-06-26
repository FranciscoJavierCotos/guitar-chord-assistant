import { NextRequest, NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

/**
 * Sign out (B1 — #26). POST-only so a stray <img>/link GET can't be used to log a
 * user out via CSRF. Revokes the Supabase session (clearing the auth cookies) and
 * redirects home.
 */
export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  const supabase = createClient();
  await supabase.auth.signOut();
  return NextResponse.redirect(new URL("/", req.url), { status: 303 });
}
