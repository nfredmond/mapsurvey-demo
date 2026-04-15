with project as (
  select id from public.engagement_projects where slug = 'bike-better-san-diego'
)
insert into public.engagement_tools (project_id, slug, tool_type, title, config)
select project.id,
       'public-discussion',
       'discussion',
       'Public Conversation',
       '{"prompt":"Share questions, ideas, and lived experiences that should shape the project record.","moderation":"post"}'::jsonb
from project
on conflict (project_id, slug) do update
set title = excluded.title,
    tool_type = excluded.tool_type,
    config = excluded.config,
    is_active = true;
