-- M4 read security. Browser roles may read approved projections only; every
-- game-state write remains a FastAPI/service_role responsibility.

create or replace function public.is_in_game(target_game_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
      from public.game_players
     where game_id = target_game_id
       and user_id = auth.uid()
  );
$$;

create or replace function public.can_read_game(target_game_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
      from public.games
     where id = target_game_id
       and host_user_id = auth.uid()
  ) or public.is_in_game(target_game_id);
$$;

create or replace function public.is_own_player(target_player_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
      from public.game_players
     where id = target_player_id
       and user_id = auth.uid()
  );
$$;

create or replace function public.is_alliance_member(target_alliance_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
      from public.alliance_members am
      join public.game_players gp on gp.id = am.player_id
     where am.alliance_id = target_alliance_id
       and am.left_at_seq is null
       and gp.user_id = auth.uid()
  );
$$;

revoke all on function public.is_in_game(uuid) from public;
revoke all on function public.can_read_game(uuid) from public;
revoke all on function public.is_own_player(uuid) from public;
revoke all on function public.is_alliance_member(uuid) from public;
grant execute on function public.is_in_game(uuid) to authenticated;
grant execute on function public.can_read_game(uuid) to authenticated;
grant execute on function public.is_own_player(uuid) to authenticated;
grant execute on function public.is_alliance_member(uuid) to authenticated;

alter table public.users enable row level security;
alter table public.games enable row level security;
alter table public.game_snapshots enable row level security;
alter table public.game_players enable row level security;
alter table public.board_tiles enable row level security;
alter table public.properties enable row level security;
alter table public.property_claims enable row level security;
alter table public.holdings enable row level security;
alter table public.game_stock_prices enable row level security;
alter table public.alliances enable row level security;
alter table public.alliance_members enable row level security;
alter table public.alliance_proposals enable row level security;
alter table public.loans enable row level security;
alter table public.player_vehicles enable row level security;
alter table public.insurance_policies enable row level security;
alter table public.player_modifiers enable row level security;
alter table public.pending_effects enable row level security;
alter table public.bankruptcy_records enable row level security;
alter table public.game_events enable row level security;
alter table public.trade_offers enable row level security;
alter table public.standing_orders enable row level security;

create policy users_select_self on public.users
  for select to authenticated
  using (id = auth.uid());

create policy users_update_self on public.users
  for update to authenticated
  using (id = auth.uid())
  with check (id = auth.uid());

create policy games_select_participant on public.games
  for select to authenticated
  using (public.can_read_game(id));

create policy game_players_select_participant on public.game_players
  for select to authenticated
  using (public.is_in_game(game_id));

create policy board_tiles_select_participant on public.board_tiles
  for select to authenticated
  using (public.is_in_game(game_id));

create policy properties_select_participant on public.properties
  for select to authenticated
  using (public.is_in_game(game_id));

create policy property_claims_select_participant on public.property_claims
  for select to authenticated
  using (public.is_in_game(game_id));

create policy holdings_select_participant on public.holdings
  for select to authenticated
  using (public.is_in_game(game_id));

create policy game_stock_prices_select_participant on public.game_stock_prices
  for select to authenticated
  using (public.is_in_game(game_id));

create policy alliances_select_participant on public.alliances
  for select to authenticated
  using (public.is_in_game(game_id));

create policy alliance_members_select_participant on public.alliance_members
  for select to authenticated
  using (
    exists (
      select 1
        from public.alliances
       where alliances.id = alliance_members.alliance_id
         and public.is_in_game(alliances.game_id)
    )
  );

create policy alliance_proposals_select_party on public.alliance_proposals
  for select to authenticated
  using (
    public.is_own_player(from_player_id)
    or public.is_own_player(to_player_id)
  );

create policy loans_select_owner on public.loans
  for select to authenticated
  using (public.is_own_player(player_id));

create policy player_vehicles_select_participant on public.player_vehicles
  for select to authenticated
  using (public.is_in_game(game_id));

create policy insurance_policies_select_participant on public.insurance_policies
  for select to authenticated
  using (public.is_in_game(game_id));

create policy player_modifiers_select_participant on public.player_modifiers
  for select to authenticated
  using (public.is_in_game(game_id));

create policy pending_effects_select_owner on public.pending_effects
  for select to authenticated
  using (public.is_own_player(player_id));

create policy bankruptcy_records_select_participant on public.bankruptcy_records
  for select to authenticated
  using (public.is_in_game(game_id));

create policy game_events_select_participant on public.game_events
  for select to authenticated
  using (public.is_in_game(game_id));

create policy trade_offers_select_party on public.trade_offers
  for select to authenticated
  using (
    public.is_own_player(from_player)
    or public.is_own_player(to_player)
  );

create policy standing_orders_select_owner on public.standing_orders
  for select to authenticated
  using (public.is_own_player(player_id));

-- Browser-safe projections. security_invoker keeps the caller's RLS context.
create view public.games_public
with (security_invoker = true, security_barrier = true)
as
select
  id,
  mode,
  status,
  config_version,
  game_seed,
  server_seed_hash,
  board_theme,
  host_user_id,
  line_group_id,
  player_count_at_start,
  target_minutes,
  total_tiles,
  lap_limit,
  day_limit,
  rolls_per_day,
  net_worth_threshold,
  bankrupt_threshold,
  current_turn_seq,
  current_event_seq,
  rng_seq,
  current_day,
  current_player_id,
  turn_deadline,
  treasury,
  created_at,
  started_at,
  finished_at,
  end_reason
from public.games;

create view public.holdings_public
with (security_invoker = true, security_barrier = true)
as
select game_id, player_id, stock_code, value, shares
from public.holdings;

create view public.alliance_members_public
with (security_invoker = true, security_barrier = true)
as
select
  alliances.game_id,
  alliance_members.alliance_id,
  alliance_members.player_id,
  alliance_members.relationship_changes,
  alliance_members.joined_at_seq,
  alliance_members.left_at_seq
from public.alliance_members
join public.alliances on alliances.id = alliance_members.alliance_id;

create or replace function public.get_finished_game_seed(target_game_id uuid)
returns text
language sql
stable
security definer
set search_path = ''
as $$
  select server_seed
    from public.games
   where id = target_game_id
     and status = 'finished'
     and public.can_read_game(id);
$$;

create or replace function public.get_my_holdings(target_game_id uuid)
returns table (
  game_id uuid,
  player_id uuid,
  stock_code text,
  value numeric,
  shares integer,
  avg_cost numeric
)
language sql
stable
security definer
set search_path = ''
as $$
  select h.game_id, h.player_id, h.stock_code, h.value, h.shares, h.avg_cost
    from public.holdings h
   where h.game_id = target_game_id
     and public.is_own_player(h.player_id);
$$;

create or replace function public.get_my_alliance_members(target_alliance_id uuid)
returns table (
  alliance_id uuid,
  player_id uuid,
  contributed numeric,
  relationship_changes smallint,
  joined_at_seq integer,
  left_at_seq integer
)
language sql
stable
security definer
set search_path = ''
as $$
  select
    am.alliance_id,
    am.player_id,
    am.contributed,
    am.relationship_changes,
    am.joined_at_seq,
    am.left_at_seq
  from public.alliance_members am
  where am.alliance_id = target_alliance_id
    and public.is_alliance_member(target_alliance_id);
$$;

revoke all on function public.get_finished_game_seed(uuid) from public;
revoke all on function public.get_my_holdings(uuid) from public;
revoke all on function public.get_my_alliance_members(uuid) from public;
grant execute on function public.get_finished_game_seed(uuid) to authenticated;
grant execute on function public.get_my_holdings(uuid) to authenticated;
grant execute on function public.get_my_alliance_members(uuid) to authenticated;

-- Start from no browser privileges. State mutations intentionally receive no grants.
revoke all on all tables in schema public from anon, authenticated;
revoke all on all sequences in schema public from anon, authenticated;

grant usage on schema public to anon, authenticated, service_role;
grant usage on schema auth to authenticated, service_role;
grant execute on function auth.uid() to authenticated, service_role;
grant select on
  public.game_configs,
  public.towns,
  public.town_price_history,
  public.stocks,
  public.stock_prices,
  public.market_calendar
to anon, authenticated;

grant select on public.users to authenticated;
grant update (display_name, avatar_config, locale, push_enabled) on public.users to authenticated;

grant select (
  id, mode, status, config_version, game_seed, server_seed_hash, board_theme,
  host_user_id, line_group_id, player_count_at_start, target_minutes, total_tiles,
  lap_limit, day_limit, rolls_per_day, net_worth_threshold, bankrupt_threshold,
  current_turn_seq, current_event_seq, rng_seq, current_day, current_player_id,
  turn_deadline, treasury, created_at, started_at, finished_at, end_reason
) on public.games to authenticated;

grant select on
  public.game_players,
  public.board_tiles,
  public.properties,
  public.property_claims,
  public.game_stock_prices,
  public.alliances,
  public.alliance_proposals,
  public.loans,
  public.player_vehicles,
  public.insurance_policies,
  public.player_modifiers,
  public.pending_effects,
  public.bankruptcy_records,
  public.game_events,
  public.trade_offers,
  public.standing_orders,
  public.games_public,
  public.holdings_public,
  public.alliance_members_public
to authenticated;

grant select (game_id, player_id, stock_code, value, shares)
  on public.holdings to authenticated;
grant select (
  alliance_id, player_id, relationship_changes, joined_at_seq, left_at_seq
) on public.alliance_members to authenticated;

grant all privileges on all tables in schema public to service_role;
grant all privileges on all sequences in schema public to service_role;
grant execute on all functions in schema public to service_role;
