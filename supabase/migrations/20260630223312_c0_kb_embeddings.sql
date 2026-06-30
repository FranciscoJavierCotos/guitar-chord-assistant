-- C0: music-theory corpus embeddings table + HNSW index (GitHub #30, Epic #24).
--
-- This is reference/catalog data, not user data: it holds the curated corpus the
-- retrieval tool (C1) searches over, identically for every user. That's why its RLS
-- policy shape deliberately differs from every other table in this schema (which are
-- all owner-scoped on auth.uid()) — see the comment on the select policy below.

create table public.kb_chunks (
  id          uuid primary key default gen_random_uuid(),
  source      text not null,        -- corpus file slug, e.g. "diatonic-triads-and-harmonic-function"
  title       text not null,        -- human-readable title for citation rendering (C2)
  url         text,                 -- optional external reference link; null for original notes with no single source
  chunk_index int not null,         -- 0-based ordinal within the source doc
  content     text not null,        -- the chunk text actually embedded
  embedding   extensions.vector(768) not null,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  unique (source, chunk_index)
);

create trigger kb_chunks_set_updated_at
  before update on public.kb_chunks
  for each row execute function public.set_updated_at();

-- HNSW over cosine distance — matches how the retrieval tool (C1) will query
-- (`embedding <=> query_embedding`). No IVFFlat `lists` tuning needed at this scale.
create index kb_chunks_embedding_idx
  on public.kb_chunks
  using hnsw (embedding extensions.vector_cosine_ops);

create index kb_chunks_source_idx on public.kb_chunks (source);

-- RLS: enabled per project convention, but this is shared reference data, not
-- per-user data, so the policy shape is intentionally "public read, service-role-only
-- write" rather than owner-scoped. Read is open (true) because the corpus is
-- non-sensitive published content; there is deliberately no insert/update/delete
-- policy, so only the service-role key (used exclusively by the ingestion script)
-- can write — the anon/authenticated roles can never modify the corpus.
alter table public.kb_chunks enable row level security;

create policy "kb_chunks_select_all" on public.kb_chunks
  for select using (true);
