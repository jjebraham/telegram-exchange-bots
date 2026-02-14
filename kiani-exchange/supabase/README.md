# Supabase migration & admin function plan

## Phase 0 (env)
- `frontend/mini-app/.env` includes `VITE_SUPABASE_URL` + `VITE_SUPABASE_ANON_KEY`.
- `adminpanel/.env` includes `VITE_SUPABASE_URL` + `VITE_SUPABASE_ANON_KEY`.
- Edge Functions use `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` from secrets (`functions/.env.example` as template).

## Phase 1 (schema)
Migration: `migrations/20260214_120000_phase1_supabase_core.sql`
- Creates: `profiles`, `exchange_requests`, `audit_logs`, `bot_logs`, `api_keys`, `blacklist`.
- Adds required indexes for auth UID and admin/audit query patterns.
- Adds update trigger for `exchange_requests.updated_at`.

## Phase 2 (RLS)
RLS is enabled on all tables in scope.
- `profiles`: own select/update + admin read-all.
- `exchange_requests`: own select/insert/update (status protected by grant + policy strategy).
- `bot_logs`: own select policy.
- `api_keys` / `audit_logs` / `blacklist`: no direct anon/authenticated permissions.

### Why RLS
RLS enforces authorization in the database itself and prevents privilege bypass from buggy clients. Policies are evaluated for every query with `auth.uid()` and JWT claims, making multi-tenant isolation reliable by default.

## Phase 3 (Edge Functions)
Implemented:
- `admin-get-users`
- `admin-update-user`
- `admin-ban-user`
- `admin-list-exchanges`
- `admin-update-exchange-status`
- `admin-create-api-key`
- `admin-revoke-api-key`

All functions:
- verify caller JWT
- load caller role from DB (never trust client role)
- enforce `admin/superadmin`
- include basic in-memory throttling
- write audit logs for state changes

## Phase 4 (frontend integration)
- Added Supabase client utility in mini-app.
- Added admin panel Supabase client utility + helper to call Edge Functions.
- Admin panel should use Edge Functions instead of direct table access.

## Phase 5 hardening notes
- Use private storage buckets for KYC/receipts.
- Return signed URLs via Edge Function only.
- Add cron jobs for risk scoring and cleanup.
