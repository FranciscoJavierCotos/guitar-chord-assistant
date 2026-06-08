import { NextRequest, NextResponse } from "next/server";
import { BACKEND_URL, backendHeaders, relay } from "@/lib/serverBackend";

// Always run on the server at request time; never cache token-spending calls.
export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  try {
    const body = await req.text();
    const res = await fetch(`${BACKEND_URL}/api/chat`, {
      method: "POST",
      headers: backendHeaders(req, { "Content-Type": "application/json" }),
      body,
    });
    return relay(res);
  } catch {
    return NextResponse.json({ detail: "Failed to reach backend" }, { status: 502 });
  }
}
