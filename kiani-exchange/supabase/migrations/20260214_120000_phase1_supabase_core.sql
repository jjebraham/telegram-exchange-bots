create extension if not exists pgcrypto;

create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  phone text unique,
  email text unique,
  full_name text,
  national_id text,
  dob date,
  card_number text,
  kyc_status text default 'pending',
  risk_score int default 0,
  role text not null default 'user' check (role in ('user','moderator','admin','superadmin')),
  is_active boolean not null default true,
  is_banned boolean not null default false,
  created_at timestamptz not null default now()
);

create table if not exists public.exchange_requests (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles(id) on delete cascade,
  from_currency text,
  to_currency text,
  amount numeric,
  rate numeric,
  fee_amount numeric,
  fee_currency text,
  status text not null default 'pending' check (status in ('pending','review','approved','paid','completed','rejected','cancelled')),
  risk_level text,
  receipt_url text,
  payment_link text,
  admin_note text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.audit_logs (
  id bigserial primary key,
  actor_id uuid references public.profiles(id) on delete set null,
  action text not null,
  entity_type text,
  entity_id text,
  old_value jsonb,
  new_value jsonb,
  ip_address text,
  created_at timestamptz not null default now()
);

create table if not exists public.bot_logs (
  id bigserial primary key,
  user_id uuid references public.profiles(id) on delete set null,
  command text,
  response text,
  session_id text,
  created_at timestamptz not null default now()
);

create table if not exists public.api_keys (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  hashed_key text not null,
  created_by uuid references public.profiles(id) on delete set null,
  last_used_at timestamptz,
  revoked_at timestamptz,
  created_at timestamptz not null default now()
);

create table if not exists public.blacklist (
  id uuid primary key default gen_random_uuid(),
  type text not null check (type in ('ip','phone','card','email')),
  value text unique not null,
  reason text,
  created_by uuid references public.profiles(id) on delete set null,
  created_at timestamptz not null default now()
);

create index if not exists idx_exchange_requests_user_id on public.exchange_requests(user_id);
create index if not exists idx_bot_logs_user_id on public.bot_logs(user_id);
create index if not exists idx_audit_logs_actor_created on public.audit_logs(actor_id, created_at desc);

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists trg_exchange_requests_updated_at on public.exchange_requests;
create trigger trg_exchange_requests_updated_at
before update on public.exchange_requests
for each row execute function public.set_updated_at();

alter table public.profiles enable row level security;
alter table public.exchange_requests enable row level security;
alter table public.bot_logs enable row level security;
alter table public.api_keys enable row level security;
alter table public.audit_logs enable row level security;
alter table public.blacklist enable row level security;

create policy "profiles_select_own"
on public.profiles
for select
using (id = auth.uid());

create policy "profiles_update_own"
on public.profiles
for update
using (id = auth.uid())
with check (id = auth.uid());

create policy "profiles_admin_read_all"
on public.profiles
for select
using (
  exists (
    select 1 from public.profiles p
    where p.id = auth.uid()
      and p.role in ('admin','superadmin')
  )
);

create policy "exchange_select_own"
on public.exchange_requests
for select
using (user_id = auth.uid());

create policy "exchange_insert_own"
on public.exchange_requests
for insert
with check (user_id = auth.uid());

create policy "exchange_update_own"
on public.exchange_requests
for update
using (user_id = auth.uid())
with check (user_id = auth.uid());

create policy "bot_logs_select_own"
on public.bot_logs
for select
using (user_id = auth.uid());

revoke all on table public.api_keys from anon, authenticated;
revoke all on table public.audit_logs from anon, authenticated;
revoke all on table public.blacklist from anon, authenticated;

revoke all on table public.profiles from anon, authenticated;
grant select on public.profiles to authenticated;
grant update (full_name, email, dob) on public.profiles to authenticated;

revoke all on table public.exchange_requests from anon, authenticated;
grant select, insert on public.exchange_requests to authenticated;
grant update (from_currency, to_currency, amount, rate, fee_amount, fee_currency, receipt_url, payment_link) on public.exchange_requests to authenticated;

revoke all on table public.bot_logs from anon, authenticated;
grant select on public.bot_logs to authenticated;
