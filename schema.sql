-- VortexAI (Supabase/Postgres)
create extension if not exists pgcrypto;

create table if not exists sellers (
  seller_id uuid primary key default gen_random_uuid(),
  name text not null,
  email text not null,
  phone text,
  country text,
  region text,
  city text,
  asset_type text not null check (asset_type in ('real_estate','car','wholesale','luxury','equipment')),
  ask_price numeric,
  currency text,
  description text,
  images jsonb default '[]'::jsonb,
  source_url text,
  created_at timestamptz not null default now()
);

create table if not exists buyers (
  buyer_id uuid primary key default gen_random_uuid(),
  name text not null,
  email text not null,
  phone text,
  countries jsonb not null default '[]'::jsonb,
  regions jsonb not null default '[]'::jsonb,
  categories jsonb not null default '[]'::jsonb,
  budget_min numeric,
  budget_max numeric,
  notes text,
  status text not null default 'active',
  created_at timestamptz not null default now()
);

create table if not exists deals (
  deal_id uuid primary key default gen_random_uuid(),
  category text not null check (category in ('real_estate','car','wholesale','luxury','equipment')),
  source text,
  source_url text,
  source_uid text,
  title text,
  description text,
  price numeric,
  currency text,
  country text,
  region text,
  city text,
  postal_code text,
  posted_at timestamptz,
  images jsonb default '[]'::jsonb,
  raw jsonb default '{}'::jsonb,
  ai_score numeric,
  ai_reason text,
  created_at timestamptz not null default now(),
  unique (source, source_uid)
);

create table if not exists deal_sources (
  source_id uuid primary key default gen_random_uuid(),
  source text not null,
  category text not null,
  country text,
  region text,
  url text not null,
  is_enabled boolean not null default true,
  notes text,
  created_at timestamptz not null default now()
);

create table if not exists matches (
  match_id uuid primary key default gen_random_uuid(),
  deal_id uuid not null references deals(deal_id) on delete cascade,
  buyer_id uuid not null references buyers(buyer_id) on delete cascade,
  match_score numeric not null,
  match_breakdown jsonb not null default '{}'::jsonb,
  status text not null default 'pending',
  created_at timestamptz not null default now(),
  unique (deal_id, buyer_id)
);

create table if not exists notifications (
  notification_id uuid primary key default gen_random_uuid(),
  kind text not null check (kind in ('admin','buyer')),
  to_email text not null,
  subject text not null,
  body text not null,
  status text not null default 'queued',
  related_deal_id uuid references deals(deal_id) on delete set null,
  related_buyer_id uuid references buyers(buyer_id) on delete set null,
  provider text,
  provider_message_id text,
  created_at timestamptz not null default now(),
  sent_at timestamptz
);

create table if not exists payments (
  payment_id uuid primary key default gen_random_uuid(),
  buyer_id uuid references buyers(buyer_id) on delete set null,
  deal_id uuid references deals(deal_id) on delete set null,
  payment_type text not null,
  amount numeric not null,
  currency text,
  status text not null default 'pending',
  method text,
  provider text,
  provider_ref text,
  created_at timestamptz not null default now()
);

create table if not exists audit_events (
  event_id uuid primary key default gen_random_uuid(),
  event_type text not null,
  entity_type text,
  entity_id uuid,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

-- Indexes
create index if not exists idx_deals_geo on deals(country, region, city);
create index if not exists idx_deals_posted_at on deals(posted_at desc);
create index if not exists idx_deals_ai_score on deals(ai_score desc);
create index if not exists idx_matches_buyer on matches(buyer_id, match_score desc);
create index if not exists idx_matches_deal on matches(deal_id, match_score desc);
create index if not exists idx_notifications_status on notifications(status, created_at desc);
