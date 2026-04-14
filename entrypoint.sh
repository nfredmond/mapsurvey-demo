#!/bin/sh

# If DATABASE_URL is set (Render), skip waiting for local db
if [ -z "$DATABASE_URL" ]; then
    echo "Waiting for postgres..."
    while ! pg_isready -h db -p 5432 -q; do
      sleep 0.1
    done
    echo "PostgreSQL started"
fi

python manage.py migrate
python manage.py collectstatic --no-input --clear

# Create superuser from env vars if set (DJANGO_SUPERUSER_USERNAME, DJANGO_SUPERUSER_EMAIL, DJANGO_SUPERUSER_PASSWORD)
if [ -n "$DJANGO_SUPERUSER_USERNAME" ]; then
    python manage.py shell -c "import os; from django.contrib.auth import get_user_model; User = get_user_model(); username = os.environ['DJANGO_SUPERUSER_USERNAME']; email = os.environ.get('DJANGO_SUPERUSER_EMAIL', ''); password = os.environ.get('DJANGO_SUPERUSER_PASSWORD', ''); User.objects.filter(username=username).exists() or User.objects.create_superuser(username, email, password)"
fi

if [ "$SEED_SDBIKE_DEMO" = "true" ]; then
    python manage.py seed_sdbike_demo
fi

exec "$@"
