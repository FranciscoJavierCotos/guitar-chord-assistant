"use client";

import React, { useEffect, useState } from "react";

interface MeResponse {
  id: string;
  email: string | null;
  profile: { username: string | null; display_name: string | null } | null;
}

/**
 * Calls the backend's authenticated `GET /api/me` via the same-origin proxy
 * (B1 — #26). The proxy attaches the user's verified JWT; the backend checks it
 * (asymmetric JWKS) and reads the profile through RLS. Rendering this confirms the
 * full browser → proxy → backend → RLS identity path end-to-end.
 */
export default function BackendIdentity() {
  const [data, setData] = useState<MeResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    fetch("/api/backend/api/me")
      .then(async (res) => {
        if (!res.ok) throw new Error(`Backend returned ${res.status}`);
        return res.json();
      })
      .then((json: MeResponse) => active && setData(json))
      .catch((err: Error) => active && setError(err.message));
    return () => {
      active = false;
    };
  }, []);

  return (
    <div className="mt-4 rounded-xl border border-border-dark bg-bg-surface p-4">
      <p className="text-xs font-mono uppercase tracking-widest text-text-muted">
        Backend identity (verified)
      </p>
      {error && <p className="mt-2 text-sm text-red-400">Couldn&apos;t reach backend: {error}</p>}
      {data ? (
        <p className="mt-2 text-sm text-text-warm">
          Backend recognizes you as{" "}
          <span className="font-mono text-accent-gold">{data.email ?? data.id}</span>.
        </p>
      ) : (
        !error && <p className="mt-2 text-sm text-text-muted">Checking…</p>
      )}
    </div>
  );
}
