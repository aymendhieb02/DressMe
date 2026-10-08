from redis import Redis
from rq import Queue, Worker
from rq.serializers import JSONSerializer

from ..config import get_settings
from .dispatcher import QUEUE_NAME


def run_worker() -> None:
    redis = Redis.from_url(get_settings().redis_url, socket_connect_timeout=2, socket_timeout=2, health_check_interval=30)
    queue = Queue(QUEUE_NAME, connection=redis, serializer=JSONSerializer)
    Worker([queue], connection=redis, serializer=JSONSerializer).work()


if __name__ == "__main__":
    run_worker()
