import { NextRequest, NextResponse } from "next/server";
import { BACKEND_URL, backendHeaders, bearerHeader, relay } from "@/lib/serverBackend";
import { getUserAccessToken } from "@/lib/supabase/server";

/**
 * Catch-all server-side proxy for the non-chat backend endpoints the UI reads
 * (/api/chords, /api/chord/..., /api/progressions, /api/session/...). It exists
 * because every backend route now requires the X-Internal-Token header, and only
 * a route handler — not a next.config rewrite — can attach that server-only secret.
 *
 * Browser calls /api/backend/<backend-path>; we forward to BACKEND_URL/<backend-path>
 * with the token + the real client IP.
 */
export const dynamic = "force-dynamic";

async function proxy(
  req: NextRequest,
  path: string[],
  method: "GET" | "DELETE",
): Promise<Response> {
  const target = `${BACKEND_URL}/${path.join("/")}${req.nextUrl.search}`;
  try {
    // Forward the signed-in user's token so authenticated backend routes (e.g.
    // /api/me) see the real user and RLS applies; omitted when anonymous.
    const token = await getUserAccessToken();
    const res = await fetch(target, {
      method,
      headers: backendHeaders(req, bearerHeader(token)),
    });
    return relay(res);
  } catch {
    return NextResponse.json({ detail: "Failed to reach backend" }, { status: 502 });
  }
}

export async function GET(req: NextRequest, { params }: { params: { path: string[] } }) {
  return proxy(req, params.path, "GET");
}

export async function DELETE(req: NextRequest, { params }: { params: { path: string[] } }) {
  return proxy(req, params.path, "DELETE");
}
