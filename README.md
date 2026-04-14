# Ride San Diego Engagement Hub

This repository is a San Diego County Bicycle Coalition engagement mapping tool built on the open-source [Mapsurvey](https://github.com/ganjasan/mapsurvey) Django/GeoDjango platform.

The production Vercel app lets residents map dangerous crossings, missing bikeway links, maintenance problems, and near misses with notes and optional photos. Submissions are stored in Supabase.

## What Is Included

- Custom landing page for a "Bike for a Better San Diego" campaign.
- Vercel-safe public input map backed by Supabase.
- Public Mapsurvey survey seeded with Vision Zero, route gap, school route, and mode-shift questions.
- Staff dashboard, survey editor, analytics, response validation, GeoJSON/CSV export, and campaign tracking inherited from Mapsurvey.
- Supabase-ready `DATABASE_URL` support with `sslmode=require`.

## Local Development

```bash
cp .env.example .env
./run_dev.sh --clean
python manage.py seed_sdbike_demo
```

Open `http://localhost:8000`.

The seed command prints the public survey URL and creates a staff account for the seeded Mapsurvey workspace:

```text
sdbike_admin / sdbike-demo-admin
```

## Tests

```bash
./run_tests.sh survey -v2
```

Tests require the PostGIS container started by the script.

## Supabase Configuration

Keep Supabase credentials out of git. For the Vercel engagement map, set these production environment variables:

```bash
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<service-role-key>
MAPBOX_ACCESS_TOKEN=<mapbox-public-token>
```

Apply the production input table:

```bash
supabase link --project-ref <project-ref>
supabase db push
```

For the full Django/GeoDjango Mapsurvey deployment, put the database URL in `.env` or deployment secrets:

```bash
DATABASE_URL=postgresql://postgres:<password>@db.<project-ref>.supabase.co:5432/postgres?sslmode=require
```

If your host cannot reach Supabase's direct IPv6 database endpoint, use the Supabase connection pooler URL from Project Settings > Database instead.

Before running migrations on Supabase, ensure PostGIS is enabled in the database:

```sql
create extension if not exists postgis;
```

Then run:

```bash
python manage.py migrate
python manage.py seed_sdbike_demo
```

## Deployment Notes

This project has two runtime paths. Vercel runs the production public input tool in `vercel_app.py`, routed by `vercel.json` and root `wsgi.py`, with submissions stored in Supabase. Render, Fly.io, or Railway remain the best fit for the full long-running Django/GeoDjango Mapsurvey service because Vercel's Python runtime does not include native GDAL.

For the full Django/GeoDjango deployment, run migrations and seed data before sharing the Mapsurvey workspace:

```bash
python manage.py migrate
python manage.py seed_sdbike_demo
```

For the Vercel engagement map, set:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `MAPBOX_ACCESS_TOKEN` if using Mapbox tiles

For the full Docker deployment, set:

- `SECRET_KEY`
- `DEBUG=0`
- `DJANGO_ALLOWED_HOSTS`
- `DATABASE_URL`
- `MAPBOX_ACCESS_TOKEN` if using Mapbox tiles
- `DEMO_SURVEY_URL` after seeding, if the landing page CTA should point to a fixed survey URL

Docker hosts should also set `CELERY_BROKER_URL` and `CELERY_RESULT_BACKEND`.

## License

The underlying Mapsurvey code is AGPLv3. See `LICENSE`.
