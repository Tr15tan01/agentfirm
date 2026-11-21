# Restore drill: 17 November 2026

**Result: passed.** An encrypted backup of the development database was restored into an empty database and verified. The drill also found a data problem on its first attempts (see below), which is exactly what drills are for.

| Step | Result |
|---|---|
| Source | Development database, 47 MB: 1,289 organisations, 606 tasks, 25,654 execution events, 4,641 audit entries |
| Backup | `deploy/backup/backup.sh`: `pg_dump -Fc`, encrypted with age to the recipient key, plus a SHA-256 file. **3.8 MB, under 1 s.** The file starts with `age-encryption.org/v1` (ciphertext only). |
| Restore | `deploy/backup/restore.sh` into a new, empty database: checksum, decrypt with the offline identity key, `pg_restore --exit-on-error`. **Under 1 s.** |
| Verification | `verify.sql` passed:<ul><li>schema `0009`;</li><li>row-level security on every organisation table (except `auth_sessions`, which is user-scoped by design);</li><li>every RLS table has a policy;</li><li>worker and ops functions present;</li><li>Free plan present.</li></ul> |
| Data | Row counts match the source for organisations, users, tasks, executions, events, audit logs, usage records and credit balances. |
| Isolation | In the restored database, the app role sees **0** tasks without tenant context and exactly its own organisation's rows with it. |

## Finding: orphaned rows
The first two restore attempts failed on foreign keys. There were 735 orphaned rows:
- approval requests;
- events;
- artifacts;
- step results;
- tool calls;
- 14 executions without a task.

**Cause:** a manual clean-up I ran in Phase 5 used `session_replication_role = replica`. That setting disables foreign-key triggers, so the cascades never ran. It was not an application bug. The orphans were removed, and the third attempt passed.

**Lessons:**
- Never use `session_replication_role` on production data (now forbidden in the runbook).
- `pg_restore --exit-on-error` doubles as a referential-integrity check.
- Run the drill monthly.

## Production estimates
These are extrapolations, to be confirmed by the first drill on the production server.
- **RPO 6 hours:** backups run every 6 hours (`deploy/docker-compose.prod.yml`, backup service).
- **RTO:** under 30 minutes for databases under 5 GB.
  - Download from R2, decrypt and `pg_restore` scale with database size.
  - At about 50 MB/s restore throughput, 5 GB takes about 2 minutes.
  - The rest of the time is provisioning and switching DNS.
- **Point-in-time recovery** (WAL archiving with pgBackRest) is the next step when an RPO under 6 hours is needed.
