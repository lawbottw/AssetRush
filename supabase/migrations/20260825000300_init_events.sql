-- M4 append-only event stream and asynchronous helper state.

create type public.offer_status as enum (
  'pending', 'accepted', 'rejected', 'expired', 'cancelled'
);

create table public.game_events (
  id bigint generated always as identity primary key,
  game_id uuid not null references public.games(id) on delete cascade,
  event_seq integer not null check (event_seq > 0),
  turn_seq integer not null check (turn_seq >= 0),
  round_no integer not null default 0 check (round_no >= 0),
  actor_id uuid references public.game_players(id),
  event_type text not null,
  payload jsonb not null,
  created_at timestamptz not null default now(),
  unique (game_id, event_seq),
  constraint game_events_payload_object check (jsonb_typeof(payload) = 'object'),
  constraint game_events_payload_type_matches check (
    payload ? 'type' and payload ->> 'type' = event_type
  ),
  constraint game_events_payload_seq_matches check (
    payload ? 'seq'
    and jsonb_typeof(payload -> 'seq') = 'number'
    and (payload ->> 'seq')::integer = event_seq
  )
);

create index game_events_game_id_idx on public.game_events (game_id, id);
create index game_events_type_idx on public.game_events (game_id, event_type);

create table public.trade_offers (
  id uuid primary key,
  game_id uuid not null references public.games(id) on delete cascade,
  from_player uuid not null references public.game_players(id),
  to_player uuid not null references public.game_players(id),
  cash_frozen numeric(14, 0) not null default 0 check (cash_frozen >= 0),
  property_tile_indices integer[] not null default '{}',
  give_payload jsonb not null default '{}',
  want_payload jsonb not null default '{}',
  status public.offer_status not null default 'pending',
  expires_at timestamptz,
  message text,
  created_at timestamptz not null default now(),
  resolved_at timestamptz,
  constraint trade_offers_distinct_players check (from_player <> to_player),
  constraint trade_offers_give_object check (jsonb_typeof(give_payload) = 'object'),
  constraint trade_offers_want_object check (jsonb_typeof(want_payload) = 'object'),
  constraint trade_offers_resolution check (
    (status = 'pending' and resolved_at is null)
    or (status <> 'pending' and resolved_at is not null)
  )
);

create index trade_offers_pending_recipient_idx
  on public.trade_offers (game_id, to_player)
  where status = 'pending';
create index trade_offers_pending_expiry_idx
  on public.trade_offers (expires_at)
  where status = 'pending' and expires_at is not null;

alter table public.properties
  add constraint properties_frozen_offer_fk
  foreign key (frozen_by_offer) references public.trade_offers(id);

create table public.standing_orders (
  game_id uuid not null references public.games(id) on delete cascade,
  player_id uuid not null,
  slot smallint not null default 0 check (slot between 0 and 7),
  rule jsonb not null default '{}',
  bid_policy text not null default 'none' check (bid_policy in ('none', 'base_price')),
  cash_floor numeric(14, 0) not null default 0 check (cash_floor >= 0),
  max_bid_ratio numeric(8, 6) not null default 1 check (max_bid_ratio >= 0),
  is_enabled boolean not null default true,
  primary key (game_id, player_id, slot),
  foreign key (game_id, player_id)
    references public.game_players(game_id, id) on delete cascade,
  constraint standing_orders_rule_object check (jsonb_typeof(rule) = 'object')
);

comment on table public.game_events is
  'Append-only authority. payload uses assetrush.engine.event_codec event names.';
comment on table public.game_snapshots is
  'Private lossless initial/current GameState JSON; never expose through PostgREST.';
