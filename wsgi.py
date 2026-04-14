"""Vercel WSGI entrypoint.

Vercel's Python runtime looks for a top-level WSGI/ASGI application named
``app`` in common entrypoint files. The real Django WSGI module stays inside
the project package for local development and Docker.
"""

from mapsurvey.wsgi import app, application  # noqa: F401
