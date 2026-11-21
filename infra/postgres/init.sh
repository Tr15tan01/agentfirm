#!/bin/sh
# Runs once on first container start (as the postgres superuser).
# Creates the schema-OWNER role (migrations) and the non-owner APP role (API, subject to RLS).
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
CREATE ROLE agentfirm_owner LOGIN PASSWORD '${AGENTFIRM_OWNER_PASSWORD}' NOSUPERUSER NOBYPASSRLS;
CREATE ROLE agentfirm_app   LOGIN PASSWORD '${AGENTFIRM_APP_PASSWORD}'   NOSUPERUSER NOBYPASSRLS;
-- Read-only statistics for the Prometheus exporter (no table data). Optional outside production.
CREATE ROLE agentfirm_monitor LOGIN PASSWORD '${AGENTFIRM_MONITOR_PASSWORD:-disabled-$(date +%s%N)}' NOSUPERUSER NOBYPASSRLS;
GRANT pg_monitor TO agentfirm_monitor;
CREATE DATABASE agentfirm OWNER agentfirm_owner;
\c agentfirm
CREATE EXTENSION IF NOT EXISTS vector;   -- used by knowledge retrieval from Phase 4
ALTER SCHEMA public OWNER TO agentfirm_owner;
SQL
