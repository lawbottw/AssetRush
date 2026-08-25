-- M4 materialized game state. The private game_snapshots row is the lossless
-- representation; normalized tables are query/RLS read models.

create type public.game_mode as enum ('blitz', 'daily');
create type public.game_status as enum (
  'lobby', 'recruiting', 'starting', 'active', 'settling', 'finished', 'aborted'
);
create type public.tile_kind as enum (
  'start', 'property', 'opportunity', 'fate', 'leisure', 'tax', 'jail', 'hospital'
);
create type public.claim_status as enum ('pending', 'won', 'lost', 'cancelled');
create type public.confinement_kind as enum ('jail', 'hospital');
create type public.alliance_tier as enum ('couple', 'married', 'family_small', 'family_large');

create table public.games (
  id uuid primary key default gen_random_uuid(),
  mode public.game_mode not null,
  status public.game_status not null default 'lobby',
  config_version text not null references public.game_configs(version),
  game_seed bigint not null,
  server_seed_hash text not null,
  server_seed text not null,
  board_theme text not null default 'standard',
  host_user_id uuid not null references public.users(id),
  line_group_id text,
  player_count_at_start smallint check (player_count_at_start > 0),
  target_minutes smallint check (target_minutes is null or target_minutes > 0),
  total_tiles smallint check (total_tiles is null or total_tiles > 0),
  lap_limit smallint not null default 0 check (lap_limit >= 0),
  day_limit smallint check (day_limit is null or day_limit > 0),
  rolls_per_day smallint check (rolls_per_day is null or rolls_per_day > 0),
  net_worth_threshold numeric(14, 0) not null default 0,
  bankrupt_threshold smallint check (bankrupt_threshold is null or bankrupt_threshold > 0),
  current_turn_seq integer not null default 0 check (current_turn_seq >= 0),
  current_event_seq integer not null default 0 check (current_event_seq >= 0),
  rng_seq integer not null default 0 check (rng_seq >= 0),
  current_day integer not null default 0 check (current_day >= 0),
  current_player_id uuid,
  turn_deadline timestamptz,
  treasury numeric(14, 0) not null default 0,
  created_at timestamptz not null default now(),
  started_at timestamptz,
  finished_at timestamptz,
  end_reason text,
  constraint games_seed_hash_not_blank check (length(btrim(server_seed_hash)) > 0),
  constraint games_config_by_mode check (
    (mode = 'daily' and target_minutes is null)
    or mode = 'blitz'
  )
);

create index games_active_deadline_idx
  on public.games (turn_deadline)
  where status = 'active' and turn_deadline is not null;
create index games_active_day_idx
  on public.games (current_day)
  where status = 'active';
create index games_line_group_idx on public.games (line_group_id);

create table public.game_snapshots (
  game_id uuid primary key references public.games(id) on delete cascade,
  initial_state jsonb not null,
  current_state jsonb not null,
  initial_digest text not null,
  current_digest text not null,
  updated_at timestamptz not null default now(),
  constraint game_snapshots_initial_object check (jsonb_typeof(initial_state) = 'object'),
  constraint game_snapshots_current_object check (jsonb_typeof(current_state) = 'object')
);

create table public.game_players (
  id uuid primary key default gen_random_uuid(),
  game_id uuid not null references public.games(id) on delete cascade,
  user_id uuid not null references public.users(id),
  base_turn_order smallint not null check (base_turn_order >= 0),
  player_color text not null,
  background_key text,
  occupation_key text,
  occupation_tier smallint check (occupation_tier is null or occupation_tier > 0),
  cash numeric(14, 0) not null,
  frozen_cash numeric(14, 0) not null default 0 check (frozen_cash >= 0),
  debt numeric(14, 0) not null default 0 check (debt >= 0),
  net_worth numeric(14, 0) not null default 0,
  position smallint not null default 0 check (position >= 0),
  lap smallint not null default 0 check (lap >= 0),
  monthly_salary numeric(14, 0) not null default 0,
  health smallint not null default 70 check (health between 0 and 100),
  luck smallint not null default 0,
  rolls_used_today smallint not null default 0 check (rolls_used_today >= 0),
  default_count smallint not null default 0 check (default_count >= 0),
  is_blacklisted boolean not null default false,
  is_bankrupt boolean not null default false,
  has_quit boolean not null default false,
  alliance_id uuid,
  relationship_changes smallint not null default 0 check (relationship_changes >= 0),
  confinement_kind public.confinement_kind,
  confinement_remaining smallint check (
    confinement_remaining is null or confinement_remaining >= 0
  ),
  confinement_reason text,
  education_course_key text,
  education_remaining_laps smallint not null default 0 check (education_remaining_laps >= 0),
  education_unlocked_tier smallint check (
    education_unlocked_tier is null or education_unlocked_tier > 0
  ),
  bankrupt_at_seq integer,
  last_acted_day integer not null default 0 check (last_acted_day >= 0),
  acted_at timestamptz,
  joined_at timestamptz not null default now(),
  unique (game_id, user_id),
  unique (game_id, base_turn_order),
  unique (game_id, id),
  constraint game_players_confinement_pair check (
    (confinement_kind is null and confinement_remaining is null)
    or (confinement_kind is not null and confinement_remaining is not null)
  )
);

alter table public.games
  add constraint games_current_player_fk
  foreign key (current_player_id) references public.game_players(id);

create index game_players_active_order_idx
  on public.game_players (game_id, base_turn_order)
  where not is_bankrupt and not has_quit;
create index game_players_daily_action_idx
  on public.game_players (game_id, last_acted_day)
  where not is_bankrupt and not has_quit;

create table public.board_tiles (
  game_id uuid not null references public.games(id) on delete cascade,
  idx smallint not null check (idx >= 0),
  kind public.tile_kind not null,
  town_code text references public.towns(code),
  town_name text,
  county text,
  region text,
  base_price numeric(12, 0) check (base_price is null or base_price >= 0),
  price_tier smallint check (price_tier is null or price_tier between 1 and 5),
  sponsor jsonb,
  primary key (game_id, idx),
  constraint board_tiles_property_fields check (
    kind <> 'property'
    or (town_code is not null and base_price is not null and price_tier is not null)
  ),
  constraint board_tiles_sponsor_object check (
    sponsor is null or jsonb_typeof(sponsor) = 'object'
  )
);

create table public.properties (
  game_id uuid not null,
  tile_idx smallint not null,
  owner_id uuid,
  level smallint not null default 0 check (level between 0 and 4),
  invested numeric(14, 0) not null default 0 check (invested >= 0),
  is_mortgaged boolean not null default false,
  frozen_by_offer uuid,
  updated_at timestamptz not null default now(),
  primary key (game_id, tile_idx),
  foreign key (game_id, tile_idx)
    references public.board_tiles(game_id, idx) on delete cascade,
  foreign key (game_id, owner_id)
    references public.game_players(game_id, id)
);

create index properties_owner_idx
  on public.properties (game_id, owner_id)
  where owner_id is not null;

create table public.property_claims (
  id uuid primary key default gen_random_uuid(),
  game_id uuid not null references public.games(id) on delete cascade,
  tile_idx smallint not null,
  player_id uuid not null,
  bid_amount numeric(14, 0) not null check (bid_amount >= 0),
  game_day integer not null check (game_day > 0),
  status public.claim_status not null default 'pending',
  created_at timestamptz not null default now(),
  resolved_at timestamptz,
  unique (game_id, tile_idx, player_id, game_day),
  foreign key (game_id, tile_idx)
    references public.board_tiles(game_id, idx) on delete cascade,
  foreign key (game_id, player_id)
    references public.game_players(game_id, id) on delete cascade,
  constraint property_claims_resolution check (
    (status = 'pending' and resolved_at is null)
    or (status <> 'pending' and resolved_at is not null)
  )
);

create index property_claims_pending_tile_idx
  on public.property_claims (game_id, game_day, tile_idx)
  where status = 'pending';
create index property_claims_pending_player_idx
  on public.property_claims (game_id, player_id)
  where status = 'pending';

create table public.holdings (
  game_id uuid not null references public.games(id) on delete cascade,
  player_id uuid not null,
  stock_code text not null references public.stocks(code),
  value numeric(14, 0) not null default 0 check (value >= 0),
  shares integer not null default 0 check (shares >= 0),
  avg_cost numeric(12, 2) not null default 0 check (avg_cost >= 0),
  primary key (game_id, player_id, stock_code),
  foreign key (game_id, player_id)
    references public.game_players(game_id, id) on delete cascade
);

create table public.game_stock_prices (
  game_id uuid not null references public.games(id) on delete cascade,
  stock_code text not null references public.stocks(code),
  price numeric(12, 2) not null check (price >= 0),
  last_return numeric(8, 6),
  updated_lap smallint check (updated_lap is null or updated_lap >= 0),
  updated_at timestamptz not null default now(),
  primary key (game_id, stock_code)
);

create table public.alliances (
  id uuid primary key default gen_random_uuid(),
  game_id uuid not null references public.games(id) on delete cascade,
  tier public.alliance_tier not null,
  name text,
  pool_balance numeric(14, 0) not null default 0 check (pool_balance >= 0),
  core_partner_ids uuid[],
  created_at_seq integer not null check (created_at_seq >= 0),
  dissolved_at_seq integer,
  is_active boolean not null default true,
  unique (game_id, id),
  constraint alliances_core_partner_count check (
    core_partner_ids is null or cardinality(core_partner_ids) = 2
  )
);

alter table public.game_players
  add constraint game_players_alliance_fk
  foreign key (game_id, alliance_id) references public.alliances(game_id, id);

create table public.alliance_members (
  alliance_id uuid not null references public.alliances(id) on delete cascade,
  player_id uuid not null references public.game_players(id) on delete cascade,
  contributed numeric(14, 0) not null default 0 check (contributed >= 0),
  relationship_changes smallint not null default 0 check (relationship_changes >= 0),
  joined_at_seq integer not null check (joined_at_seq >= 0),
  left_at_seq integer,
  primary key (alliance_id, player_id)
);

create index alliance_members_player_idx on public.alliance_members (player_id);

create table public.alliance_proposals (
  id uuid primary key,
  game_id uuid not null references public.games(id) on delete cascade,
  from_player_id uuid not null references public.game_players(id),
  to_player_id uuid not null references public.game_players(id),
  tier public.alliance_tier not null,
  game_day integer not null check (game_day >= 0),
  target_alliance_id uuid references public.alliances(id),
  formation_style text,
  created_at timestamptz not null default now(),
  constraint alliance_proposals_distinct_players check (from_player_id <> to_player_id)
);

create table public.loans (
  id uuid primary key default gen_random_uuid(),
  game_id uuid not null references public.games(id) on delete cascade,
  player_id uuid not null,
  product_key text not null,
  principal numeric(14, 0) not null check (principal >= 0),
  balance numeric(14, 0) not null check (balance >= 0),
  rate_per_lap numeric(8, 6) not null check (rate_per_lap >= 0),
  collateral jsonb,
  opened_at_seq integer not null default 0 check (opened_at_seq >= 0),
  closed_at_seq integer,
  foreign key (game_id, player_id)
    references public.game_players(game_id, id) on delete cascade,
  constraint loans_collateral_object check (
    collateral is null or jsonb_typeof(collateral) = 'object'
  )
);

create index loans_active_player_idx
  on public.loans (game_id, player_id)
  where closed_at_seq is null;

create table public.player_vehicles (
  game_id uuid not null references public.games(id) on delete cascade,
  player_id uuid not null,
  vehicle_key text not null,
  acquired_at_seq integer not null default 0 check (acquired_at_seq >= 0),
  primary key (game_id, player_id, vehicle_key),
  foreign key (game_id, player_id)
    references public.game_players(game_id, id) on delete cascade
);

create table public.insurance_policies (
  game_id uuid not null references public.games(id) on delete cascade,
  player_id uuid not null,
  policy_key text not null,
  active_since integer not null default 0 check (active_since >= 0),
  primary key (game_id, player_id, policy_key),
  foreign key (game_id, player_id)
    references public.game_players(game_id, id) on delete cascade
);

create table public.player_modifiers (
  game_id uuid not null references public.games(id) on delete cascade,
  player_id uuid not null,
  key text not null,
  value jsonb,
  laps smallint check (laps is null or laps >= 0),
  primary key (game_id, player_id, key),
  foreign key (game_id, player_id)
    references public.game_players(game_id, id) on delete cascade
);

create table public.pending_effects (
  id bigint generated always as identity primary key,
  game_id uuid not null references public.games(id) on delete cascade,
  player_id uuid not null,
  effect_type text not null,
  reason text,
  ordinal smallint not null check (ordinal >= 0),
  unique (game_id, ordinal),
  foreign key (game_id, player_id)
    references public.game_players(game_id, id) on delete cascade
);

create table public.bankruptcy_records (
  game_id uuid not null references public.games(id) on delete cascade,
  player_id uuid not null,
  game_day integer not null check (game_day >= 0),
  net_worth_before numeric(14, 0) not null,
  counts_for_end_condition boolean not null,
  reason text not null,
  ordinal smallint not null check (ordinal >= 0),
  primary key (game_id, ordinal),
  foreign key (game_id, player_id)
    references public.game_players(game_id, id) on delete cascade
);
