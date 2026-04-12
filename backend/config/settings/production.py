from .base import *  # noqa: F401,F403

DEBUG = False

if not SECRET_KEY:
    raise RuntimeError("DJANGO_SECRET_KEY must be set.")

if not POSTGRES_PASSWORD:
    raise RuntimeError("POSTGRES_PASSWORD must be set.")

if not NEO4J_PASSWORD:
    raise RuntimeError("NEO4J_PASSWORD must be set.")

