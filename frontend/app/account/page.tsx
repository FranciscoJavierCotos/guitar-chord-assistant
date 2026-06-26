import { redirect } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase/server";
import BackendIdentity from "@/components/BackendIdentity";

export const metadata = { title: "Account · ChordCoach" };

/**
 * Protected page (B1 — #26): the anonymous-vs-gated decision in action. Chat stays
 * open to everyone, but account-scoped pages like this require a session. The guard
 * runs server-side with `getUser()` (which re-validates the JWT), so an unauthenticated
 * or tampered cookie is bounced to /login before any content renders.
 */
export default async function AccountPage() {
  const supabase = createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) redirect("/login");

  return (
    <main className="min-h-full bg-bg-primary px-4 py-12">
      <div className="mx-auto max-w-lg">
        <div className="flex items-center justify-between">
          <h1 className="font-display text-2xl font-bold text-text-warm">Your account</h1>
          <Link href="/" className="text-sm text-text-muted hover:text-text-warm">
            ← Back to chat
          </Link>
        </div>

        <dl className="mt-6 space-y-2 rounded-xl border border-border-dark bg-bg-surface p-4">
          <div className="flex justify-between gap-4">
            <dt className="text-xs font-mono uppercase tracking-widest text-text-muted">Email</dt>
            <dd className="truncate text-sm text-text-warm">{user.email}</dd>
          </div>
          <div className="flex justify-between gap-4">
            <dt className="text-xs font-mono uppercase tracking-widest text-text-muted">User ID</dt>
            <dd className="truncate font-mono text-xs text-text-muted">{user.id}</dd>
          </div>
        </dl>

        {/* Proves identity propagates all the way to the backend + RLS. */}
        <BackendIdentity />

        <form action="/auth/signout" method="post" className="mt-8">
          <button
            type="submit"
            className="rounded-lg border border-border-dark bg-bg-elevated px-4 py-2 text-sm font-medium text-text-warm hover:border-accent-orange"
          >
            Sign out
          </button>
        </form>
      </div>
    </main>
  );
}
