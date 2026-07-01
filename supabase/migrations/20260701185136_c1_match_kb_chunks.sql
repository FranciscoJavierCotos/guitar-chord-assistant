-- C1: vector-similarity search RPC over the corpus (GitHub #31, Epic #24).
--
-- PostgREST's table query builder can't express pgvector's `<=>` distance operator
-- or an ORDER BY on it, so the retrieval tool (backend/rag/retrieval.py) calls this
-- function via `.rpc(...)` instead of `.table("kb_chunks")`. `language sql` (not
-- plpgsql) since it's a single query; `stable` because it only reads; `search_path`
-- pinned to '' per the B0 hardening convention, so every identifier is schema-qualified.
create or replace function public.match_kb_chunks(
  query_embedding extensions.vector(768),
  match_count int default 5
)
returns table (
  source text,
  title text,
  url text,
  content text,
  similarity float
)
language sql
stable
set search_path = ''
as $$
  select
    kb_chunks.source,
    kb_chunks.title,
    kb_chunks.url,
    kb_chunks.content,
    1 - (kb_chunks.embedding <=> query_embedding) as similarity
  from public.kb_chunks
  order by kb_chunks.embedding <=> query_embedding
  limit least(greatest(match_count, 1), 20)
$$;

-- kb_chunks itself is public-read (see C0's "kb_chunks_select_all" policy), so this
-- function is just as safe to expose the same way: explicit grant (rather than
-- relying on Postgres's PUBLIC-execute default) to document that intent, matching
-- the explicit revoke in 20260625180000_b0_harden_functions.sql for the opposite case.
grant execute on function public.match_kb_chunks(extensions.vector, int) to anon, authenticated, service_role;
