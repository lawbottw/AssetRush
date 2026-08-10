create table if not exists game_configs (
  version text primary key,
  payload jsonb not null,
  is_active boolean not null default false,
  released_at timestamptz not null default now(),
  notes text
);

create unique index if not exists game_configs_one_active
  on game_configs (is_active)
  where is_active;
