import { NextRequest, NextResponse } from "next/server";
import { updateSession } from "@/lib/supabase/middleware";

/**
 * Edge middleware: (1) a coarse per-IP rate limit on /api/* in front of the
 * backend's authoritative slowapi limits, and (2) Supabase auth-session refresh on
 * every request (B1 — #26) so short-lived access tokens stay fresh across navigation.
 */
const WINDOW_MS = 60_000;
const MAX_REQUESTS = 60; // per IP per minute across all /api routes

const hits = new Map<string, { count: number; resetAt: number }>();

function rateLimited(ip: string): boolean {
  const now = Date.now();
  const entry = hits.get(ip);
  if (!entry || now > entry.resetAt) {
    hits.set(ip, { count: 1, resetAt: now + WINDOW_MS });
    return false;
  }
  entry.count += 1;
  return entry.count > MAX_REQUESTS;
}

export async function middleware(req: NextRequest) {
  // Rate-limit /api/* first — cheap, and avoids spending a Supabase round-trip on
  // requests we're about to reject.
  if (req.nextUrl.pathname.startsWith("/api/")) {
    const ip =
      req.headers.get("x-forwarded-for")?.split(",")[0].trim() ||
      req.headers.get("x-real-ip") ||
      "unknown";
    if (rateLimited(ip)) {
      return NextResponse.json({ detail: "Too many requests." }, { status: 429 });
    }
  }

  // Refresh the auth session and return the response carrying any rotated cookies.
  return updateSession(req, NextResponse.next({ request: req }));
}

export const config = {
  // Run on app routes (for session refresh) and /api/* (rate limit), but skip
  // static assets and image optimization to keep the edge path cheap.
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
