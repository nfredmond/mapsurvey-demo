"""Vercel WSGI entrypoint.

Docker and local development use ``mapsurvey/wsgi.py`` for the full
Django/GeoDjango app. This root file is only for Vercel, whose Python runtime
does not include native GDAL.
"""

from vercel_app import app

application = app
