-- B0: Supabase foundation — schema, pgvector, RLS baseline (GitHub #25, Epic #23).
--
-- Establishes the migration-driven data layer every later Accounts/RAG story builds on.
-- Reverses the MVP "no DB / ephemeral in-process memory" stance by explicit instruction.
--
-- Design notes:
--   * Every user-scoped table has RLS ENABLED with owner-only policies keyed on
--     auth.uid(). The backend service-role key bypasses RLS for admin work; all
--     browser/user access flows through the anon key + a user JWT, so RLS is the
--     real multi-tenant boundary.
--   * `messages` has no user_id of its own — ownership is derived from its parent
--     conversation, so its policies join through public.conversations.
--   * pgvector is enabled here (unblocks Epic C / RAG); the embeddings table itself
--     is intentionally deferred to story C0.

-- ─── Extensions ────────────────────────────────────────────────────────────────
-- pgvector for RAG embeddings (Epic C). Kept in the dedicated `extensions` schema
-- per Supabase convention rather than polluting `public`.
create extension if not exists vector with schema extensions;

-- ─── updated_at trigger helper ─────────────────────────────────────────────────
create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

-- ─── profiles (1:1 with auth.users) ────────────────────────────────────────────
create table public.profiles (
  id           uuid primary key references auth.users (id) on delete cascade,
  username     text unique,
  display_name text,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

create trigger profiles_set_updated_at
  before update on public.profiles
  for each row execute function public.set_updated_at();

-- Auto-provision a profile row whenever a new auth user signs up (foundation for B1).
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.profiles (id)
  values (new.id)
  on conflict (id) do nothing;
  return new;
end;
$$;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- ─── conversations ─────────────────────────────────────────────────────────────
create table public.conversations (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references auth.users (id) on delete cascade,
  title      text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index conversations_user_updated_idx
  on public.conversations (user_id, updated_at desc);

create trigger conversations_set_updated_at
  before update on public.conversations
  for each row execute function public.set_updated_at();

-- ─── messages ──────────────────────────────────────────────────────────────────
-- agent_action stores the structured AgentAction JSON block of assistant replies
-- (see frontend/lib/types.ts) so the chord panel can be rehydrated from history.
create table public.messages (
  id              uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references public.conversations (id) on delete cascade,
  role            text not null check (role in ('user', 'assistant', 'system')),
  content         text not null,
  agent_action    jsonb,
  created_at      timestamptz not null default now()
);

create index messages_conversation_created_idx
  on public.messages (conversation_id, created_at);

-- ─── practice_events ───────────────────────────────────────────────────────────
-- Append-only log of practice activity (chord drilled, progression played, etc.).
create table public.practice_events (
  id             uuid primary key default gen_random_uuid(),
  user_id        uuid not null references auth.users (id) on delete cascade,
  event_type     text not null,
  chord_id       text,
  progression_id text,
  payload        jsonb,
  created_at     timestamptz not null default now()
);

create index practice_events_user_created_idx
  on public.practice_events (user_id, created_at desc);

-- ─── Row-Level Security ────────────────────────────────────────────────────────
-- Enable RLS on every user-scoped table. With RLS on and no policy, access is
-- denied by default; the policies below grant each user access to ONLY their rows.
alter table public.profiles        enable row level security;
alter table public.conversations   enable row level security;
alter table public.messages        enable row level security;
alter table public.practice_events enable row level security;

-- profiles: owner == row id (== auth.uid()). No delete policy: profiles are
-- removed via the auth.users cascade, not directly by users.
create policy "profiles_select_own" on public.profiles
  for select using (auth.uid() = id);
create policy "profiles_insert_own" on public.profiles
  for insert with check (auth.uid() = id);
create policy "profiles_update_own" on public.profiles
  for update using (auth.uid() = id) with check (auth.uid() = id);

-- conversations: owner == user_id.
create policy "conversations_select_own" on public.conversations
  for select using (auth.uid() = user_id);
create policy "conversations_insert_own" on public.conversations
  for insert with check (auth.uid() = user_id);
create policy "conversations_update_own" on public.conversations
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "conversations_delete_own" on public.conversations
  for delete using (auth.uid() = user_id);

-- messages: ownership derived from the parent conversation.
create policy "messages_select_own" on public.messages
  for select using (
    exists (
      select 1 from public.conversations c
      where c.id = messages.conversation_id and c.user_id = auth.uid()
    )
  );
create policy "messages_insert_own" on public.messages
  for insert with check (
    exists (
      select 1 from public.conversations c
      where c.id = messages.conversation_id and c.user_id = auth.uid()
    )
  );
create policy "messages_update_own" on public.messages
  for update using (
    exists (
      select 1 from public.conversations c
      where c.id = messages.conversation_id and c.user_id = auth.uid()
    )
  );
create policy "messages_delete_own" on public.messages
  for delete using (
    exists (
      select 1 from public.conversations c
      where c.id = messages.conversation_id and c.user_id = auth.uid()
    )
  );

-- practice_events: owner == user_id.
create policy "practice_events_select_own" on public.practice_events
  for select using (auth.uid() = user_id);
create policy "practice_events_insert_own" on public.practice_events
  for insert with check (auth.uid() = user_id);
create policy "practice_events_update_own" on public.practice_events
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "practice_events_delete_own" on public.practice_events
  for delete using (auth.uid() = user_id);
