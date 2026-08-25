-- M4 identity and reference data. Real-world ETL rows are populated in M9.

create extension if not exists pgcrypto;

create table public.users (
  id uuid primary key references auth.users(id) on delete cascade,
  display_name text not null check (length(btrim(display_name)) between 1 and 40),
  avatar_config jsonb,
  line_user_id text unique,
  locale text not null default 'zh-TW',
  push_enabled boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint users_avatar_object check (
    avatar_config is null or jsonb_typeof(avatar_config) = 'object'
  )
);

create table public.towns (
  code text primary key,
  name text not null,
  county text not null,
  region text not null,
  population integer not null check (population >= 0),
  avg_price_per_ping numeric(12, 0) check (avg_price_per_ping >= 0),
  price_tier smallint check (price_tier between 1 and 5),
  txn_count integer check (txn_count >= 0),
  is_imputed boolean not null default false,
  is_active boolean not null default true,
  updated_at timestamptz not null default now()
);

create index towns_region_idx on public.towns (region);
create index towns_county_idx on public.towns (county);
create index towns_active_price_tier_idx
  on public.towns (price_tier)
  where is_active;

create table public.town_price_history (
  town_code text not null references public.towns(code) on delete cascade,
  quarter text not null check (quarter ~ '^[0-9]{4}Q[1-4]$'),
  avg_price_per_ping numeric(12, 0) not null check (avg_price_per_ping >= 0),
  txn_count integer check (txn_count >= 0),
  primary key (town_code, quarter)
);

create type public.etf_kind as enum ('none', 'passive', 'active');

create table public.stocks (
  code text primary key,
  name text not null,
  sector text,
  style text,
  etf_kind public.etf_kind not null default 'none',
  seed_price numeric(12, 2) check (seed_price > 0),
  is_active boolean not null default true
);

create table public.stock_prices (
  code text not null references public.stocks(code) on delete cascade,
  trade_date date not null,
  close_price numeric(12, 2) check (close_price >= 0),
  change_amount numeric(12, 2),
  daily_return numeric(8, 6) check (daily_return between -1 and 1),
  raw jsonb,
  primary key (code, trade_date),
  constraint stock_prices_raw_object check (raw is null or jsonb_typeof(raw) = 'object')
);

create index stock_prices_trade_date_idx on public.stock_prices (trade_date desc);

create table public.market_calendar (
  trade_date date primary key,
  is_open boolean not null,
  source text not null check (source in ('api', 'manual', 'inferred'))
);
