# ADR 0002 — Three-layer tenant isolation with PostgreSQL RLS

- **Status:** Accepted (Phase 3), 2026-11-16

## Decision
1. **Application layer:** every service function receives the `Principal`, and every query filters by
   `org_id`. Requests for another organisation's resources return 404, so whether a
   resource exists is never revealed.
2. **Schema layer:** child tables reference `(org_id, id)` through composite foreign keys, so
   rows from different organisations can't reference each other, even through the owner role.
3. **Database layer:** row-level security is enabled on every tenant table. The per-transaction
   setting `app.org_id` (from `set_config(…, true)`) decides which rows are visible and writable. The API connects as
   `agentfirm_app`, which is neither the owner nor a superuser and has no `BYPASSRLS`. At startup
   the API refuses to run if its role could bypass RLS.

A few operations have to cross the RLS boundary on purpose. Each one goes through its own small
`SECURITY DEFINER` function: checking slug uniqueness, finding the organisation for an invitation
token, and writing platform-level audit entries.

The audit log is append-only. The app role has no UPDATE, DELETE or TRUNCATE grant on it, and a
trigger rejects changes even from the owner.

## Verification
`api/tests/test_tenancy.py` fails CI if any new route with a path parameter isn't classified
for cross-tenant behaviour. `test_rls.py` runs unfiltered queries as the app role and
asserts that only the current organisation's rows come back.
