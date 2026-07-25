# Activating real Row-Level Security

**Status today:** `schema.sql` defines RLS policies on `users`, `api_keys`,
and (after `schema_migration_008.sql`) `refresh_tokens`, keyed on
`current_setting('app.user_id')`. Production has always connected to
Postgres as the DB **owner**, and Postgres RLS policies never apply to a
table's owner — so these policies have been dead code since they were
written. All tenant isolation in production has really been enforced by
`WHERE user_id = $1` clauses in route handlers, which look correct on
inspection but are one missed clause away from a cross-tenant leak with no
second layer of defense underneath.

## What changed in this pass

`api/db.py` adds `user_scoped(user_id)`, an async context manager that:
1. acquires a pooled connection,
2. opens a transaction,
3. runs `SELECT set_config('app.user_id', $1, true)` — the parametrized
   equivalent of `SET LOCAL app.user_id = ...`, scoped to the transaction
   so it can never leak onto a reused pooled connection,
4. commits or rolls back on exit and releases the connection.

Routes that only ever touch the *already-authenticated* user's own rows
now use it instead of a bare `pool.acquire()`:
`api/routes/user.py`, `api/routes/api_keys.py`,
`POST /v1/auth/refresh`, `POST /v1/auth/logout`.

`schema_migration_008.sql` fixes two gaps found while wiring this up:
- `refresh_tokens` had RLS **enabled** with no **policy** — under RLS that
  means default-deny, not default-allow, for any non-owner role. Without
  this fix, switching the connection role would have silently broken
  login/refresh/logout (every `refresh_tokens` query returns 0 rows).
- `pipeline_runs` and `consumer_reports` (added in migrations 005/007)
  never got the `GRANT INSERT, UPDATE ... TO foodsafe_app` every other
  migration applies to the tables it introduces.

## Why login/register can't be RLS-scoped

`POST /v1/auth/login` and `/register` look up a user **by email**, before
any `user_id` is known — there is no value to put in `app.user_id` yet.
This is a normal, unavoidable shape for any RLS-based auth system: the
credential-check step needs a privileged path (today, the DB owner
connection) precisely because it's the one operation that can't yet know
who it's scoping to. Everything *after* that point — refresh, logout,
profile, API keys — has a verified `user_id` and is scoped.

## Activation steps (not yet done — infra change, not a code change)

1. Apply `schema_migration_008.sql`.
2. Point a **staging** `DATABASE_URL` at `foodsafe_app` (not the owner)
   and run the full auth flow end to end: register → login → profile →
   update location → create/list/revoke an API key → refresh → logout.
   Watch specifically for silent empty results (RLS denial looks like
   "no rows found", not an error) rather than just checking for 5xxs.
   `python -m scripts.verify_rls_activation` automates the register /
   profile / location / refresh / logout path above and checks response
   *content*, not just status codes, against exactly this failure mode.
   It doesn't cover API-key create/list/revoke yet — add those checks the
   same way if you extend it.
3. Audit every other route file for a bare `pool.acquire()` that touches
   `users`, `api_keys`, or `refresh_tokens` outside the four call sites
   above — any such route will need `user_scoped()` too, or it will
   simply stop working once the connection role changes (again: silently,
   as empty results, not an error).
4. Only once (2) and (3) pass, change the real `DATABASE_URL` secret in
   Render / GitHub Actions to the `foodsafe_app` connection string.

This doc exists so that step 4 is a deliberate, tested decision — not
something to do by just editing an env var and hoping.
