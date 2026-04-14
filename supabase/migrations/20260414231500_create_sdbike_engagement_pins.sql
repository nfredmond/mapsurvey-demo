create extension if not exists pgcrypto;

create table if not exists public.sdbike_engagement_pins (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  category text not null check (char_length(category) <= 80),
  title text not null check (char_length(title) <= 120),
  note text not null default '' check (char_length(note) <= 1000),
  lng double precision not null check (lng between -118.2 and -116.0),
  lat double precision not null check (lat between 32.3 and 33.6),
  photo_data_url text not null default '' check (char_length(photo_data_url) <= 750000),
  client_id text not null check (char_length(client_id) <= 80),
  source text not null default 'sdbike-vercel',
  status text not null default 'active' check (status in ('active', 'removed', 'flagged'))
);

create index if not exists sdbike_engagement_pins_status_created_idx
  on public.sdbike_engagement_pins (status, created_at desc);

create index if not exists sdbike_engagement_pins_client_idx
  on public.sdbike_engagement_pins (client_id);

create or replace function public.set_sdbike_engagement_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists set_sdbike_engagement_updated_at on public.sdbike_engagement_pins;
create trigger set_sdbike_engagement_updated_at
before update on public.sdbike_engagement_pins
for each row
execute function public.set_sdbike_engagement_updated_at();

alter table public.sdbike_engagement_pins enable row level security;

revoke all on public.sdbike_engagement_pins from anon, authenticated;
