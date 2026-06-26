import { NextRequest, NextResponse } from "next/server";
import { BACKEND_URL, backendHeaders, bearerHeader } from "@/lib/serverBackend";
import { getUserAccessToken } from "@/lib/supabase/server";

// Always run on the server at request time; never cache token-spending calls.
export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  try {
    const body = await req.text();
    // Chat stays anonymous, but forward the user's identity when signed in so the
    // backend can attribute the turn (used from B2 onward). No session → no header.
    const token = await getUserAccessToken();
    const res = await fetch(`${BACKEND_URL}/api/chat/stream`, {
      method: "POST",
      headers: backendHeaders(req, {
        "Content-Type": "application/json",
        ...bearerHeader(token),
      }),
      body,
    });

    // On error (auth, rate limit, 503…) the backend replies with a JSON body, not
    // a stream — pass it through so the client can surface a sensible message.
    if (!res.ok || !res.body) {
      const text = await res.text();
      return new Response(text, {
        status: res.status,
        headers: { "Content-Type": res.headers.get("content-type") || "application/json" },
      });
    }

    // Pipe the backend's token stream straight to the browser, unbuffered.
    return new Response(res.body, {
      status: 200,
      headers: {
        "Content-Type": "text/plain; charset=utf-8",
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",
      },
    });
  } catch {
    return NextResponse.json({ detail: "Failed to reach backend" }, { status: 502 });
  }
}
