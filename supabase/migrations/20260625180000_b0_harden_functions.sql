-- B0 hardening — resolve Supabase security-advisor warnings on the baseline (#25).
--
--   1. set_updated_at had a mutable search_path (lint 0011). Pin it to '' so the
--      function can't be hijacked by a malicious schema on the caller's path.
--   2. handle_new_user is a SECURITY DEFINER trigger function but was also exposed
--      as a callable RPC (/rest/v1/rpc/handle_new_user) to anon + authenticated
--      (lints 0028/0029). It only ever needs to run as the on_auth_user_created
--      trigger, so revoke EXECUTE from the API roles. The trigger still fires.

-- 1. Pin the trigger helper's search_path (now() lives in pg_catalog, always in scope).
create or replace function public.set_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

-- 2. Stop exposing the signup trigger function as a public RPC.
revoke execute on function public.handle_new_user() from anon, authenticated, public;
