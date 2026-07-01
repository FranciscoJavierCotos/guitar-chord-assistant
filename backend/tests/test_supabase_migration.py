"""B0 data-layer guards (#25): lock the Supabase migration's security baseline.

The acceptance criterion "RLS enabled on every user-scoped table, owner-only,
verified with a denial test" was proven live against the project (two authenticated
users could each see only their own conversation; anon saw nothing) and recorded in
the engineering journal. These offline tests are the *regression* guard — they parse
the committed migrations so a later edit can't silently drop RLS, an owner policy, or
the pgvector extension. They need no DB, secrets, or network, so they run in CI.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "supabase" / "migrations"

# Every table that holds per-user data and therefore must be locked by RLS.
USER_SCOPED_TABLES = ["profiles", "conversations", "messages", "practice_events"]


def _sql() -> str:
    """All migration SQL concatenated (in filename order) and lowercased."""
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    assert files, f"no migration files found in {MIGRATIONS_DIR}"
    return "\n".join(f.read_text(encoding="utf-8") for f in files).lower()


def _normalize(text: str) -> str:
    """Collapse all runs of whitespace so multi-line SQL matches single-line patterns."""
    return re.sub(r"\s+", " ", text)


def test_migration_files_exist():
    assert MIGRATIONS_DIR.is_dir()
    assert list(MIGRATIONS_DIR.glob("*.sql"))


def test_pgvector_extension_enabled():
    # Enables Epic C (RAG) — the embeddings table itself is deferred to C0.
    assert re.search(r"create extension if not exists vector", _sql())


def test_all_user_tables_created():
    sql = _sql()
    for table in USER_SCOPED_TABLES:
        assert re.search(rf"create table public\.{table}\b", sql), f"missing table {table}"


@pytest.mark.parametrize("table", USER_SCOPED_TABLES)
def test_rls_enabled_on_every_user_table(table):
    sql = _normalize(_sql())
    assert f"alter table public.{table} enable row level security" in sql, (
        f"RLS not enabled on {table}"
    )


@pytest.mark.parametrize("table", USER_SCOPED_TABLES)
def test_owner_scoped_policies_reference_auth_uid(table):
    """Each table must have at least select + insert policies, all gated on auth.uid()."""
    sql = _normalize(_sql())
    policies = re.findall(rf'create policy "[^"]+" on public\.{table}\b.*?(?=create policy|alter table|$)', sql)
    assert policies, f"no policies defined for {table}"
    kinds = {re.search(r"for (select|insert|update|delete)", p).group(1) for p in policies if re.search(r"for (select|insert|update|delete)", p)}
    assert {"select", "insert"} <= kinds, f"{table} missing select/insert policy (has {kinds})"
    for p in policies:
        assert "auth.uid()" in p, f"a {table} policy is not gated on auth.uid(): {p[:80]}"


def test_messages_ownership_derived_from_parent_conversation():
    # messages has no user_id; its policies must join through conversations.
    sql = _normalize(_sql())
    msg_policies = re.findall(r'create policy "[^"]+" on public\.messages\b.*?(?=create policy|alter table|$)', sql)
    assert msg_policies
    for p in msg_policies:
        assert "public.conversations" in p and "auth.uid()" in p


@pytest.mark.parametrize("table", USER_SCOPED_TABLES)
def test_no_user_table_is_left_world_readable(table):
    """Defense check: no user-scoped table's policy has `using (true)` / `with check
    (true)` slipped in. Scoped to USER_SCOPED_TABLES (not the whole SQL blob) since
    `kb_chunks` (story C0 — #30) is intentionally public-read reference data, not
    user data — see test_kb_chunks_has_no_write_policy_for_anon below."""
    sql = _normalize(_sql())
    policies = re.findall(
        rf'create policy "[^"]+" on public\.{table}\b.*?(?=create policy|alter table|$)', sql
    )
    assert policies, f"no policies defined for {table}"
    for p in policies:
        assert "using (true)" not in p, f"{table} has a world-readable policy: {p[:80]}"
        assert "with check (true)" not in p, f"{table} has an unchecked write policy: {p[:80]}"


def test_kb_chunks_table_and_hnsw_index_exist():
    """C0 (#30): the embeddings table + its HNSW cosine index must exist."""
    sql = _normalize(_sql())
    assert re.search(r"create table public\.kb_chunks\b", sql)
    assert "using hnsw" in sql
    assert "vector_cosine_ops" in sql


def test_kb_chunks_has_no_write_policy_for_anon():
    """C0 (#30): kb_chunks is shared reference data — RLS enabled, public read, but
    only the service-role key (which bypasses RLS) may ever write it. Proving no
    insert/update/delete policy exists is what guarantees anon/authenticated roles
    can never modify the corpus."""
    sql = _normalize(_sql())
    assert "alter table public.kb_chunks enable row level security" in sql

    policies = re.findall(
        r'create policy "[^"]+" on public\.kb_chunks\b.*?(?=create policy|alter table|$)', sql
    )
    assert policies, "kb_chunks has no policies at all"
    kinds = {
        m.group(1)
        for p in policies
        if (m := re.search(r"for (select|insert|update|delete)", p))
    }
    assert kinds == {"select"}, f"kb_chunks should only have a select policy, found {kinds}"


def test_match_kb_chunks_rpc_exists_and_is_callable():
    """C1 (#31): the retrieval tool queries kb_chunks via this RPC (PostgREST can't
    express pgvector's `<=>` ordering through the table query builder), so it must
    exist, be readable, and stay grantable to the roles the API actually uses."""
    sql = _normalize(_sql())
    assert "create or replace function public.match_kb_chunks" in sql
    assert "order by kb_chunks.embedding operator(extensions.<=>) query_embedding" in sql
    assert (
        "grant execute on function public.match_kb_chunks(extensions.vector, int) "
        "to anon, authenticated, service_role" in sql
    )
