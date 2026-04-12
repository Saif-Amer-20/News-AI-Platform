import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")

app = Celery("newsintel")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# Register failure handlers (dead letter queue routing)
import ops.failure_handlers  # noqa: F401, E402

