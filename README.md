# Ride San Diego Engagement Hub

This repository is a San Diego County Bicycle Coalition demo built on the open-source [Mapsurvey](https://github.com/ganjasan/mapsurvey) Django/GeoDjango platform.

The demo turns Mapsurvey into a public engagement hub where residents can map dangerous crossings, missing bikeway links, school routes, bike parking needs, and weekly car trips that could shift to biking.

## What Is Included

- Custom landing page for a "Bike for a Better San Diego" campaign.
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

The seed command prints the public survey URL and creates a demo staff account:

```text
sdbike_admin / sdbike-demo-admin
```

## Tests

```bash
./run_tests.sh survey -v2
```

Tests require the PostGIS container started by the script.

## Supabase Configuration

Keep Supabase credentials out of git. Put them in `.env` or deployment secrets:

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

This demo is a Dockerized Django/GeoDjango app. Render, Fly.io, or Railway are still the best fit for the full long-running service. The repo also includes a Vercel serverless entrypoint in `vercel.json` and root `wsgi.py` so GitHub deployments to Vercel route traffic to Django instead of returning a platform 404.

On Vercel, run migrations and seed data against Supabase separately before sharing the demo:

```bash
python manage.py migrate
python manage.py seed_sdbike_demo
```

For Vercel, Render, or another host, set:

- `SECRET_KEY`
- `DEBUG=0`
- `DJANGO_ALLOWED_HOSTS`
- `DATABASE_URL`
- `MAPBOX_ACCESS_TOKEN` if using Mapbox tiles
- `DEMO_SURVEY_URL` after seeding, if the landing page CTA should point to a fixed survey URL

Docker hosts should also set `CELERY_BROKER_URL` and `CELERY_RESULT_BACKEND`.

## License

The underlying Mapsurvey code is AGPLv3. See `LICENSE`.
