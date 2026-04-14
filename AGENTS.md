# Repository Guidelines

## Project Structure & Module Organization

The application lives in `mapsurvey-master/`. It is a Django 4.2 + GeoDjango project for geospatial surveys.

- `mapsurvey-master/manage.py` is the main Django entry point.
- `mapsurvey-master/mapsurvey/` contains project settings, root URLs, WSGI, and Celery setup.
- `mapsurvey-master/survey/` contains the main survey domain: models, views, forms, templates, template tags, migrations, analytics, and serialization.
- `mapsurvey-master/newsletter/` contains campaign models, tasks, templates, tests, and admin customizations.
- `mapsurvey-master/docs/` and `mapsurvey-master/openspec/` hold product docs, plans, and feature specs.
- `mapsurvey-master/survey/assets/`, `mapsurvey-master/docs/images/`, and template folders contain UI and documentation assets.

## Build, Test, and Development Commands

Run commands from `mapsurvey-master/`.

- `./run_dev.sh` starts PostgreSQL/PostGIS, Redis, migrations, Celery, and the Django dev server at `http://localhost:8000`.
- `./run_dev.sh --clean` resets Docker volumes, migrates, and creates a clean local database.
- `docker compose up -d db redis` starts backing services only.
- `./run_tests.sh survey -v2` starts the test database container and runs Django tests for the `survey` app.
- `python manage.py migrate` applies migrations when services are already running.
- `python manage.py test newsletter survey` runs selected Django test apps.

## Coding Style & Naming Conventions

Follow existing Django conventions. Use 4-space indentation for Python, `snake_case` for functions and fields, `PascalCase` for classes and models, and descriptive template names such as `survey/templates/editor/survey_detail.html`. Keep views, forms, validators, and serialization logic in their existing modules. No formatter config is present, so match surrounding style and group imports by standard library, third-party, then local imports.

## Testing Guidelines

Tests use Django's test runner and require PostGIS. Put app tests in `survey/tests.py`, `newsletter/tests.py`, or focused test modules if a file becomes too large. Use clear test method names like `test_export_includes_geojson` and keep docstrings in the project's GIVEN/WHEN/THEN style. Run `./run_tests.sh survey -v2` before opening a PR; broaden to `python manage.py test newsletter survey` for cross-app changes.

## Commit & Pull Request Guidelines

This checkout does not include `.git` history, so use concise imperative commits, for example `Add survey export validation`. Keep one feature or fix per PR. PRs should include a short description, linked issue when available, test results, migration notes, and screenshots for editor, survey, or email template UI changes.

## Security & Configuration Tips

Copy `.env.example` to `.env` for local development and never commit secrets. Configure database, Redis, Mapbox, S3, and Django settings through environment variables. See `SECURITY.md` for vulnerability reporting.
