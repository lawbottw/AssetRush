-- current_turn_seq is the optimistic write version and advances for every command.
-- engine_turn_seq preserves the engine's domain turn/RNG sequence independently.

alter table public.games
  add column engine_turn_seq integer not null default 0 check (engine_turn_seq >= 0);

drop view public.games_public;

create view public.games_public
with (security_invoker = true, security_barrier = true)
as
select
  id, mode, status, config_version, game_seed, server_seed_hash, board_theme,
  host_user_id, line_group_id, player_count_at_start, target_minutes, total_tiles,
  lap_limit, day_limit, rolls_per_day, net_worth_threshold, bankrupt_threshold,
  current_turn_seq, engine_turn_seq, current_event_seq, rng_seq, current_day,
  current_player_id, turn_deadline, treasury, created_at, started_at, finished_at,
  end_reason
from public.games;

grant select (engine_turn_seq) on public.games to authenticated;
grant select on public.games_public to authenticated;
