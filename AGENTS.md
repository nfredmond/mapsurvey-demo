# Repository Guidelines

## Current Context

This repo is the San Diego County Bicycle Coalition engagement mapping demo at `https://mapsurvey-demo.vercel.app`. The production Vercel path is the lightweight WSGI app in `vercel_app.py`, routed by root `wsgi.py` and `vercel.json`. The original Django/GeoDjango Mapsurvey app still exists in `mapsurvey/`, `survey/`, and `newsletter/`, but Vercel does not run that path because its Python runtime lacks GDAL.

Latest known production-ready commit after QA: `dc240b5`.

Key live pages:
- `/survey` public engagement tools
- `/staff` staff dashboard
- `/report` printable report
- `/demo` walkthrough script
- `/about` platform vision
- `/api/report.geojson`, `/api/report.csv`, `/api/report.json` exports

## Project Structure & Module Organization

- `vercel_app.py` contains the production public site, API handlers, sample data controls, AI insights, staff dashboard, and report page.
- `wsgi.py` imports the Vercel WSGI app.
- `supabase/migrations/` contains the live Supabase schema migrations for engagement pins, projects, tools, responses, decisions, and audit events.
- `survey/assets/` contains static assets used by the Vercel page, including favicon and demo imagery.
- `mapsurvey/`, `survey/`, and `newsletter/` are the inherited Django app.

## Build, Test, and Development Commands

Run from repo root.

- `python -m py_compile vercel_app.py wsgi.py` checks the Vercel runtime files.
- `git diff --check` catches whitespace errors before commit.
- `vercel ls mapsurvey-demo --scope natford` checks production deployment status.
- `vercel env pull .env.local --yes --environment=production --scope natford` refreshes local Vercel env values. Do not commit `.env.local`.
- `supabase db push --yes` applies pending migrations after confirming the linked project.
- `./run_tests.sh` is for the legacy Django path; it expects `env/` and Python 3.9. It may fail on this machine unless that environment is rebuilt.

Local Vercel-app server:

```bash
python - <<'PY'
import os
from pathlib import Path
for name in ('.env.local', '.env'):
    path = Path(name)
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip() and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ[k.strip()] = v.strip().strip('"').strip("'")
from wsgiref.simple_server import make_server
from vercel_app import app
print('http://127.0.0.1:8765/survey', flush=True)
make_server('127.0.0.1', 8765, app).serve_forever()
PY
```

## Data & Environment Notes

Supabase is used through server-side REST calls with `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`. Vercel also has `MAPBOX_ACCESS_TOKEN`, `AI_GATEWAY_API_KEY`, and `DEMO_ADMIN_TOKEN`. Never print or commit real secrets. The demo data endpoints are protected:

- `POST /api/demo/seed`
- `POST /api/demo/reset`

Use the `x-demo-token` header with the Vercel `DEMO_ADMIN_TOKEN`. Seeded records are tagged with `source='sdbike-sample'` or `client_id='sample-seed'`.

## QA Checklist Before Sending Links

1. `git status --short`
2. `python -m py_compile vercel_app.py wsgi.py`
3. `git diff --check`
4. Verify production endpoints: `/healthz`, `/survey`, `/staff`, `/report`, `/about`, `/demo`, `/api/project`, `/api/pins`, `/api/insights`, `/api/report.geojson`.
5. Browser smoke test: open `/survey`, switch pins/clusters/heatmap, open the map wizard, close it, then check `/staff` and `/report`.
6. Confirm seeded baseline unless intentionally changed: 16 map comments, 2 survey responses, 5 poll votes, 2 discussion posts, 16 GeoJSON features.

## Coding Style & Contribution Notes

Prefer small, scoped edits. Use 4-space indentation for Python and match the existing inline HTML/CSS/JS style in `vercel_app.py`. Use `apply_patch` for manual edits. Keep public copy clear and specific to SDBC. Do not add dependencies unless necessary for the Vercel runtime.
