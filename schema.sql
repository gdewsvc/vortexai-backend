create extension if not exists pgcrypto;

create table if not exists sellers (
  seller_id uuid primary key default gen_random_uuid(),
  name text not null,
  email text not null,
  phone text,
  country text,
  region text,
  city text,
  asset_type text not null,
  ask_price numeric,
  currency text,
  description text,
  images jsonb default '[]'::jsonb,
  source_url text,
  created_at timestamptz default now()
);

create table if not exists buyers (
  buyer_id uuid primary key default gen_random_uuid(),
  name text not null,
  email text not null,
  phone text,
  countries jsonb default '[]'::jsonb,
  regions jsonb default '[]'::jsonb,
  categories jsonb default '[]'::jsonb,
  budget_min numeric,
  budget_max numeric,
  notes text,
  created_at timestamptz default now()
);
