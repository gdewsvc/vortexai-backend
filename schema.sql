create extension if not exists pgcrypto;
create table if not exists buyers (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  email text not null,
  phone text,
  countries text[] default '{}',
  regions text[] default '{}',
  categories text[] default '{}',
  budget_min numeric,
  budget_max numeric,
  notes text,
  created_at timestamptz default now()
);
create table if not exists sellers (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  email text not null,
  phone text,
  country text not null,
  region text,
  city text,
  asset_type text not null,
  price numeric,
  currency text,
  description text,
  images text[] default '{}',
  source_url text,
  created_at timestamptz default now()
);
