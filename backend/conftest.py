"""Root pytest config. Tests always run against PostgreSQL (never SQLite) — see docs/TESTING.md."""

import os

os.environ.setdefault("DJANGO_ENV", "test")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
