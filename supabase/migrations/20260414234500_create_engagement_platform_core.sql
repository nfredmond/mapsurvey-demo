create table if not exists public.engagement_projects (
  id uuid primary key default gen_random_uuid(),
  slug text not null unique,
  title text not null,
  organization text not null,
  description text not null default '',
  status text not null default 'active',
  starts_at date,
  ends_at date,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.engagement_tools (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.engagement_projects(id) on delete cascade,
  slug text not null,
  tool_type text not null check (tool_type in ('map', 'survey', 'poll', 'discussion')),
  title text not null,
  config jsonb not null default '{}'::jsonb,
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  unique(project_id, slug)
);

create table if not exists public.engagement_responses (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.engagement_projects(id) on delete cascade,
  tool_id uuid references public.engagement_tools(id) on delete set null,
  tool_type text not null,
  client_id text not null check (char_length(client_id) <= 80),
  payload jsonb not null default '{}'::jsonb,
  status text not null default 'active' check (status in ('active', 'removed', 'flagged')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.engagement_decisions (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.engagement_projects(id) on delete cascade,
  title text not null,
  description text not null default '',
  source_summary text not null default '',
  status text not null default 'draft',
  created_at timestamptz not null default now()
);

create table if not exists public.engagement_audit_events (
  id uuid primary key default gen_random_uuid(),
  project_id uuid references public.engagement_projects(id) on delete cascade,
  event_type text not null,
  actor text not null default 'public',
  entity_type text not null,
  entity_id uuid,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists engagement_responses_project_created_idx
  on public.engagement_responses (project_id, created_at desc);

create index if not exists engagement_responses_tool_idx
  on public.engagement_responses (tool_type, status);

create index if not exists engagement_audit_project_created_idx
  on public.engagement_audit_events (project_id, created_at desc);

alter table public.engagement_projects enable row level security;
alter table public.engagement_tools enable row level security;
alter table public.engagement_responses enable row level security;
alter table public.engagement_decisions enable row level security;
alter table public.engagement_audit_events enable row level security;

revoke all on public.engagement_projects from anon, authenticated;
revoke all on public.engagement_tools from anon, authenticated;
revoke all on public.engagement_responses from anon, authenticated;
revoke all on public.engagement_decisions from anon, authenticated;
revoke all on public.engagement_audit_events from anon, authenticated;

insert into public.engagement_projects (slug, title, organization, description, status, starts_at, ends_at)
values (
  'bike-better-san-diego',
  'Bike Better San Diego',
  'San Diego County Bicycle Coalition',
  'A public engagement hub for collecting map-based safety input, quick poll responses, and project priorities that can shape stronger bicycle planning outcomes.',
  'active',
  current_date,
  current_date + interval '90 days'
)
on conflict (slug) do update
set title = excluded.title,
    organization = excluded.organization,
    description = excluded.description,
    status = excluded.status,
    updated_at = now();

with project as (
  select id from public.engagement_projects where slug = 'bike-better-san-diego'
)
insert into public.engagement_tools (project_id, slug, tool_type, title, config)
select project.id, tool.slug, tool.tool_type, tool.title, tool.config
from project
cross join (values
  ('safety-map', 'map', 'Safety Map', '{"prompt":"Click the map to identify safety concerns, missing connections, or maintenance needs."}'::jsonb),
  ('rider-priorities', 'survey', 'Rider Priorities', '{"questions":["What would make this corridor easier to bike?","Who is most affected by this issue?"]}'::jsonb),
  ('quick-priority-poll', 'poll', 'Quick Priority Poll', '{"question":"What should be prioritized first?","options":["Safer crossings","Protected bike lanes","Maintenance fixes","Bike parking","School routes"]}'::jsonb)
) as tool(slug, tool_type, title, config)
on conflict (project_id, slug) do update
set title = excluded.title,
    tool_type = excluded.tool_type,
    config = excluded.config,
    is_active = true;

with project as (
  select id from public.engagement_projects where slug = 'bike-better-san-diego'
)
insert into public.engagement_decisions (project_id, title, description, source_summary, status)
select project.id,
       'Engagement record opened',
       'Public input is being collected through map comments, quick polls, and short-form project feedback.',
       'Initial project setup',
       'active'
from project
where not exists (
  select 1 from public.engagement_decisions d
  where d.project_id = project.id and d.title = 'Engagement record opened'
);
