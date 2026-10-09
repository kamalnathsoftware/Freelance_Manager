from celery import Celery

from app.core.config import get_settings

s = get_settings()
celery_app = Celery("fm", broker=s.redis_url, backend=s.redis_url)
celery_app.conf.update(
    task_serializer="json",
    timezone="UTC",
    # Phase 2+ registers periodic platform syncs here.
    beat_schedule={},
)


@celery_app.task(name="fm.ping")
def ping() -> str:
    return "pong"
