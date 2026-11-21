-- Post-restore checks: schema version, row-level security, critical functions, data present.
\set QUIET on
DO $$
DECLARE missing text;
BEGIN
  IF (SELECT version_num FROM alembic_version) IS NULL THEN RAISE EXCEPTION 'no alembic version'; END IF;
  SELECT string_agg(c.relname, ', ') INTO missing
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    JOIN information_schema.columns col ON col.table_name = c.relname AND col.column_name = 'org_id' AND col.table_schema = 'public'
   WHERE n.nspname = 'public' AND c.relkind = 'r' AND NOT c.relrowsecurity AND c.relname NOT IN ('auth_sessions');  -- user-scoped by design (see tests/test_rls.py)
  IF missing IS NOT NULL THEN RAISE EXCEPTION 'tables without RLS after restore: %', missing; END IF;
  PERFORM 'claimable_executions(integer)'::regprocedure, 'due_report_schedules(integer)'::regprocedure,
          'due_credit_periods(integer)'::regprocedure, 'ops_execution_counts()'::regprocedure;
  SELECT string_agg(c.relname, ', ') INTO missing FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
   WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relrowsecurity
     AND NOT EXISTS (SELECT 1 FROM pg_policies p WHERE p.schemaname = 'public' AND p.tablename = c.relname);
  IF missing IS NOT NULL THEN RAISE EXCEPTION 'RLS tables without a policy: %', missing; END IF;
  IF (SELECT count(*) FROM plans WHERE key = 'free') <> 1 THEN RAISE EXCEPTION 'free plan missing'; END IF;
END $$;
SELECT 'schema ' || version_num AS check FROM alembic_version
UNION ALL SELECT 'organizations ' || count(*) FROM organizations
UNION ALL SELECT 'users ' || count(*) FROM users
UNION ALL SELECT 'tasks ' || count(*) FROM tasks
UNION ALL SELECT 'execution_events ' || count(*) FROM execution_events
UNION ALL SELECT 'audit_logs ' || count(*) FROM audit_logs
UNION ALL SELECT 'credit_ledger ' || count(*) FROM credit_ledger
UNION ALL SELECT 'policies ' || count(*) FROM pg_policies WHERE schemaname = 'public';
